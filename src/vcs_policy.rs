// SPDX-License-Identifier: Apache-2.0
//! One VCS selection policy for native and WASI/JVM cptx.
//! Executors only run commands; all probing, remote naming and parsing live here.
pub trait Executor {
    fn run(&mut self, args: &[&str], output: &mut [u8]) -> Result<usize, ()>;
}
fn probe<E: Executor>(exec: &mut E, args: &[&str]) -> bool {
    let mut scratch = [0u8; 1024];
    exec.run(args, &mut scratch).is_ok()
}
fn execute<E: Executor>(exec: &mut E, args: &[&str], out: &mut [u8])
    -> Result<usize, &'static str> {
    let len = exec.run(args, out).map_err(|_| "VCS command failed")?;
    if len > out.len() { return Err("VCS output too large"); }
    let text = core::str::from_utf8(&out[..len]).map_err(|_| "VCS output is not UTF-8")?;
    let trimmed = text.trim();
    if trimmed.is_empty() { return Err("Empty VCS remote URL"); }
    let start = trimmed.as_ptr() as usize - out.as_ptr() as usize;
    let count = trimmed.len();
    out.copy_within(start..start + count, 0);
    Ok(count)
}
pub fn remote_url<E: Executor>(remote: &str, exec: &mut E, out: &mut [u8])
    -> Result<usize, &'static str> {
    if probe(exec, &["git", "rev-parse", "--is-inside-work-tree"]) {
        return execute(exec, &["git", "remote", "get-url", remote], out);
    }
    if probe(exec, &["svn", "info", "--show-item", "wc-root"]) {
        if remote != "origin" { return Err("SVN has no named remotes; omit REMOTE"); }
        return execute(exec, &["svn", "info", "--show-item", "url"], out);
    }
    if probe(exec, &["hg", "root"]) {
        return execute(exec, &["hg", "paths", if remote == "origin" { "default" } else { remote }], out);
    }
    if probe(exec, &["pijul", "root"]) {
        let len = exec.run(&["pijul", "remote"], out).map_err(|_| "Pijul remote listing failed")?;
        let listing = core::str::from_utf8(&out[..len]).map_err(|_| "Invalid Pijul output")?;
        let mut selected = None;
        for line in listing.lines() {
            let line = line.trim();
            if let Some(rest) = line.strip_prefix(remote)
                && let Some(url) = rest.strip_prefix(':').or_else(|| rest.strip_prefix(' '))
            {
                let url = url.trim();
                if !url.is_empty() {
                    selected = Some((url.as_ptr() as usize - out.as_ptr() as usize, url.len()));
                    break;
                }
            }
        }
        let (start, count) = selected.ok_or("Pijul remote not found")?;
        out.copy_within(start..start + count, 0);
        return Ok(count);
    }
    Err("No supported version-control working copy found (git, svn, hg, pijul)")
}
