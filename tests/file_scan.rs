// SPDX-License-Identifier: Apache-2.0
//! Single-file scan regression tests; no desktop clipboard required.
use console_tools::{config::Config, scan, xcat_options};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

static NEXT_ID: AtomicU64 = AtomicU64::new(0);
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "xcat-single-file-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        Self(root)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn explicit_file_bypasses_extension_and_excluded_directory_filters() {
    let temp = Temp::new();
    let excluded = temp.0.join("target");
    fs::create_dir(&excluded).unwrap();
    let selected = excluded.join("notes.custom");
    fs::write(&selected, "selected text\n").unwrap();
    let (text, count) = scan::collect_file(&selected, &Config::default()).unwrap();
    assert_eq!(count, 1);
    assert_eq!(text, "===== ./notes.custom =====\nselected text\n\n");
    let (_, directory_count) = scan::collect(&temp.0, &Config::default()).unwrap();
    assert_eq!(directory_count, 0);
}

#[test]
fn explicit_file_enforces_size_and_text_constraints() {
    let temp = Temp::new();
    let selected = temp.0.join("sample.dat");
    let mut config = Config::default();
    config.max_file_bytes = 4;
    fs::write(&selected, "12345").unwrap();
    assert_eq!(
        scan::collect_file(&selected, &config).unwrap(),
        (String::new(), 0)
    );
    fs::write(&selected, b"a\0b").unwrap();
    assert_eq!(
        scan::collect_file(&selected, &config).unwrap(),
        (String::new(), 0)
    );
    fs::write(&selected, [0xff, 0xfe]).unwrap();
    assert_eq!(
        scan::collect_file(&selected, &config).unwrap(),
        (String::new(), 0)
    );
}

#[test]
fn explicit_file_rejects_directories() {
    let temp = Temp::new();
    assert!(scan::collect_file(&temp.0, &Config::default()).is_err());
}

#[test]
fn parser_selects_single_file_and_rejects_task_combinations() {
    let opts = xcat_options::parse(
        ["-d", "project", "--file", "src/main.rs"]
            .into_iter()
            .map(str::to_string),
    )
    .unwrap();
    assert_eq!(opts.dir, PathBuf::from("project"));
    assert_eq!(opts.file, Some(PathBuf::from("src/main.rs")));
    for args in [
        vec!["-f", "a", "-e", "b"],
        vec!["-r", "b", "-f", "a"],
        vec!["-f", "a", "-f", "b"],
    ] {
        assert!(xcat_options::parse(args.into_iter().map(str::to_string)).is_err());
    }
}
