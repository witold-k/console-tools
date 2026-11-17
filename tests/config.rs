// SPDX-License-Identifier: Apache-2.0
//! Integration tests for the public xcat configuration API.
use console_tools::config::Config;
use std::{fs, path::Path};

#[test]
fn accepts_exact_names_and_case_insensitive_suffixes() {
    let config = Config::default();
    assert!(config.accepts(Path::new("Cargo.toml")));
    assert!(config.accepts(Path::new("foo.RS")));
    assert!(!config.accepts(Path::new("foo.rs.bak")));
    assert!(!config.accepts(Path::new("data.bin")));
}

#[test]
fn excludes_nested_directories_but_not_similar_names() {
    let config = Config::default();
    assert!(config.is_excluded(Path::new("src/target/test.rs")));
    assert!(!config.is_excluded(Path::new("src/mytarget/test.rs")));
}

#[test]
fn creates_missing_config_and_preserves_existing_changes() {
    let dir = std::env::temp_dir().join(format!("xcat-test-{}-{:?}", std::process::id(), std::thread::current().id()));
    fs::create_dir_all(&dir).unwrap();
    let path = dir.join("config.json");
    let _ = fs::remove_file(&path);
    let initial = Config::load_or_create(&path).unwrap();
    assert!(initial.accepts(Path::new("hello.rs")));
    assert!(initial.accepts(Path::new("hello.rs")));
    fs::write(&path, r#"{"scanendfilter":[".special"]}"#).unwrap();
    let loaded = Config::load_or_create(&path).unwrap();
    assert!(loaded.accepts(Path::new("hello.special")));
    assert!(!loaded.accepts(Path::new("hello.rs")));
    fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn rejects_invalid_existing_config_without_overwriting_it() {
    let dir = std::env::temp_dir().join(format!("xcat-invalid-{}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    let path = dir.join("config.json");
    fs::write(&path, "{invalid json").unwrap();
    assert!(Config::load_or_create(&path).is_err());
    assert_eq!(fs::read_to_string(&path).unwrap(), "{invalid json");
    fs::remove_dir_all(&dir).unwrap();
}
