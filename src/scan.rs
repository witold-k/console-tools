// SPDX-License-Identifier: Apache-2.0
//! Iterative dependency-free directory scanner, shared by native and WASI builds.
use crate::config::Config;
use std::{collections::HashSet, fs, io, path::{Path, PathBuf}};

fn group(path: &Path) -> usize {
    let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("").to_lowercase();
    if name.ends_with(".md") { 0 }
    else if name.ends_with(".txt") || name.ends_with(".log") { 1 }
    else { 2 }
}

/// Collect files under the canonical root, respecting config, directory boundaries,
/// directory exclusions, and deterministic output ordering.
/// File symlinks can point outside the root; directory symlinks cannot.
pub fn collect(root: &Path, config: &Config) -> io::Result<(String, usize)> {
    let root = root.canonicalize()?;
    if !root.is_dir() { return Err(io::Error::other("scan root is not a directory")); }
    let mut dirs = vec![root.clone()];
    let mut visited_dirs = HashSet::<PathBuf>::new();
    let mut visited_files = HashSet::<PathBuf>::new();
    let mut files = Vec::<(PathBuf, PathBuf)>::new();

    while let Some(dir) = dirs.pop() {
        let Ok(real_dir) = dir.canonicalize() else { continue };
        if !real_dir.starts_with(&root) || !visited_dirs.insert(real_dir.clone()) {
            continue;
        }
        let Ok(entries) = fs::read_dir(&real_dir) else { continue };
        for entry in entries.flatten() {
            let candidate = entry.path();
            // Retain the path used to reach the entry for filtering and output.
            // A file symlink may legitimately point outside the scan root.
            let Ok(relative) = candidate.strip_prefix(&root) else { continue };
            if config.is_excluded(relative) { continue; }
            let Ok(real) = candidate.canonicalize() else { continue };
            if real.is_dir() {
                // Do not follow a directory symlink outside the scan root.
                if real.starts_with(&root) && !visited_dirs.contains(&real) {
                    dirs.push(real);
                }
            } else if real.is_file()
                && config.accepts(relative)
                && visited_files.insert(real.clone()) {
                files.push((relative.to_path_buf(), real));
            }
        }
    }

    files.sort_by(|a, b| group(&a.0).cmp(&group(&b.0)).then_with(|| a.0.cmp(&b.0)));
    let mut output = String::new();
    let mut count = 0;
    for (relative, real) in files {
        let metadata = fs::metadata(&real)?;
        if metadata.len() > config.max_file_bytes {
            eprintln!("Skipping oversized file: {}", relative.display());
            continue;
        }
        let contents = match fs::read_to_string(&real) {
            Ok(text) if !text.contains('\0') => text,
            Ok(_) => { eprintln!("Skipping binary file: {}", relative.display()); continue; }
            Err(e) if e.kind() == io::ErrorKind::InvalidData => {
                eprintln!("Skipping non-UTF-8 file: {}", relative.display());
                continue;
            }
            Err(e) => return Err(e),
        };
        output.push_str(&format!("===== ./{name} =====\n", name = relative.display()));
        output.push_str(&contents);
        if !contents.ends_with('\n') { output.push('\n'); }
        output.push('\n');
        count += 1;
    }
    Ok((output, count))
}
