// SPDX-License-Identifier: Apache-2.0
//! Regression coverage for symlinks in xcat's directory scanner.
#![cfg(unix)]

use console_tools::{config::Config, scan};
use std::{
    fs,
    os::unix::fs::symlink,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

static NEXT_ID: AtomicU64 = AtomicU64::new(0);

struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        let dir = std::env::temp_dir().join(format!(
            "xcat-symlinks-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&dir).unwrap();
        Self(dir)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn scans_external_file_symlinks_using_link_names() {
    let temp = Temp::new();
    let root = temp.0.join("x");
    fs::create_dir(&root).unwrap();
    fs::write(temp.0.join("original.md"), "outside root\n").unwrap();
    symlink("../original.md", root.join("alias.md")).unwrap();

    let (output, count) = scan::collect(&root, &Config::default()).unwrap();
    assert_eq!(count, 1);
    assert!(output.contains("===== ./alias.md =====\noutside root\n"));
}

#[test]
fn broken_file_symlinks_are_skipped() {
    let temp = Temp::new();
    symlink("missing.md", temp.0.join("broken.md")).unwrap();
    let (output, count) = scan::collect(&temp.0, &Config::default()).unwrap();
    assert_eq!(count, 0);
    assert!(output.is_empty());
}

#[test]
fn external_directory_symlinks_are_not_traversed() {
    let temp = Temp::new();
    let root = temp.0.join("x");
    let outside = temp.0.join("outside");
    fs::create_dir(&root).unwrap();
    fs::create_dir(&outside).unwrap();
    fs::write(outside.join("secret.md"), "not included").unwrap();
    symlink(&outside, root.join("linked-dir")).unwrap();

    let (output, count) = scan::collect(&root, &Config::default()).unwrap();
    assert_eq!(count, 0);
    assert!(output.is_empty());
}

#[test]
fn aliases_to_same_file_are_included_once() {
    let temp = Temp::new();
    let root = temp.0.join("x");
    fs::create_dir(&root).unwrap();
    fs::write(temp.0.join("original.md"), "one copy").unwrap();
    symlink("../original.md", root.join("a.md")).unwrap();
    symlink("../original.md", root.join("b.md")).unwrap();
    let (output, count) = scan::collect(&root, &Config::default()).unwrap();
    assert_eq!(count, 1);
    assert_eq!(output.matches("one copy").count(), 1);
}
