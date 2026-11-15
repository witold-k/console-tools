// SPDX-License-Identifier: Apache-2.0
//! Stable, filtered source collection and formatting using fsscanner.

use crate::config::Config;
use fsscanner::{fsscanner_base::collect_files_all_filtered, pathfilter::Pathfilter};
use std::{collections::HashSet, fs, io, path::{Path, PathBuf}};

fn group(path: &Path) -> usize {
    let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("").to_lowercase();
    if name.ends_with(".md") { 0 }
    else if name.ends_with(".txt") || name.ends_with(".log") { 1 }
    else { 2 }
}

/// Reads only configured file types; returns formatted clipboard text.
pub fn collect(root: &Path, config: &Config) -> io::Result<(String, usize)> {
    let root = root.canonicalize()?;
    if !root.is_dir() { return Err(io::Error::other("scan root is not a directory")); }
    let filter = Pathfilter::new(vec![root.clone()]);
    let mut found = Vec::new();
    collect_files_all_filtered(&root, &filter, &mut found);
    let mut seen = HashSet::<PathBuf>::new();
    let mut files = Vec::new();
    for candidate in found {
        let Ok(real) = candidate.canonicalize() else { continue; };
        // Also enforces root containment for normal paths and symbolic links.
        let Ok(relative) = real.strip_prefix(&root) else { continue; };
        if !config.accepts(relative) || config.is_excluded(relative) || !seen.insert(real.clone()) {
            continue;
        }
        files.push((relative.to_path_buf(), real));
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
        // Avoid binary or invalid UTF-8 clipboard data.
        let contents = match fs::read_to_string(&real) {
            Ok(text) if !text.contains('\0') => text,
            Ok(_) => { eprintln!("Skipping binary file: {}", relative.display()); continue; }
            Err(e) if e.kind() == io::ErrorKind::InvalidData => {
                eprintln!("Skipping non-UTF-8 file: {}", relative.display()); continue;
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
