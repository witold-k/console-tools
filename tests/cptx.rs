// SPDX-License-Identifier: Apache-2.0
use std::process::Command;

fn cptx(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_cptx"))
        .args(args)
        .output()
        .unwrap()
}

#[test]
fn help_describes_tmux_capture() {
    let output = cptx(&["--help"]);
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(text.contains("tmux"));
    assert!(text.contains("scrollback"));
}

#[test]
fn rejects_unknown_arguments() {
    let output = cptx(&["--unknown"]);
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("Usage:"));
}

#[test]
fn rejects_extra_arguments_after_help() {
    let output = cptx(&["--help", "extra"]);
    assert!(!output.status.success());
}

#[test]
fn help_lists_all_modes() {
    let output = cptx(&["-h"]);
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    for option in ["--buffer", "--path", "--version", "REMOTE", "git", "svn", "hg", "Pijul"] {
        assert!(text.to_lowercase().contains(&option.to_lowercase()), "missing {option}");
    }
}

#[test]
fn rejects_unexpected_mode_arguments() {
    for args in [&["-b", "extra"][..], &["-p", "extra"], &["-v", "--help"]] {
        assert!(!cptx(args).status.success(), "accepted {args:?}");
    }
}

#[cfg(unix)]
#[test]
fn copies_path_using_mock_clipboard() {
    use std::{fs, os::unix::fs::PermissionsExt, time::{SystemTime, UNIX_EPOCH}};
    let base = std::env::temp_dir().join(format!("cptx-test-{}-{}", std::process::id(), SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    let bin = base.join("bin");
    fs::create_dir_all(&bin).unwrap();
    let clip = base.join("clipboard.txt");
    let mock = bin.join("wl-copy");
    fs::write(&mock, "#!/bin/sh\ncat > \"$CPTX_TEST_CLIPBOARD\"\n").unwrap();
    let mut permissions = fs::metadata(&mock).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&mock, permissions).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_cptx"))
        .arg("--path").current_dir(&base)
        .env("WAYLAND_DISPLAY", "test")
        .env("CPTX_TEST_CLIPBOARD", &clip)
        .env("PATH", format!("{}:{}", bin.display(), std::env::var("PATH").unwrap_or_default()))
        .output().unwrap();
    assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
    assert_eq!(fs::read_to_string(&clip).unwrap(), base.to_string_lossy());
    fs::remove_dir_all(base).unwrap();
}

#[cfg(unix)]
#[test]
fn copies_git_remote_using_mock_clipboard() {
    use std::{fs, os::unix::fs::PermissionsExt, time::{SystemTime, UNIX_EPOCH}};
    let base = std::env::temp_dir().join(format!("cptx-git-test-{}-{}", std::process::id(), SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    let bin = base.join("bin");
    fs::create_dir_all(&bin).unwrap();
    let clip = base.join("clipboard.txt");
    let mock = bin.join("wl-copy");
    fs::write(&mock, "#!/bin/sh\ncat > \"$CPTX_TEST_CLIPBOARD\"\n").unwrap();
    let mut permissions = fs::metadata(&mock).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&mock, permissions).unwrap();
    let git = |args: &[&str]| Command::new("git").args(args).current_dir(&base).status().unwrap();
    assert!(git(&["init", "-q"] ).success());
    assert!(git(&["remote", "add", "origin", "https://example.org/default.git"]).success());
    assert!(git(&["remote", "add", "upstream", "ssh://example.org/other.git"]).success());
    for (args, expected) in [(&["-v"][..], "https://example.org/default.git"), (&["--version", "upstream"], "ssh://example.org/other.git")] {
        let output = Command::new(env!("CARGO_BIN_EXE_cptx"))
            .args(args).current_dir(&base)
            .env("WAYLAND_DISPLAY", "test")
            .env("CPTX_TEST_CLIPBOARD", &clip)
            .env("PATH", format!("{}:{}", bin.display(), std::env::var("PATH").unwrap_or_default()))
            .output().unwrap();
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        assert_eq!(fs::read_to_string(&clip).unwrap(), expected);
    }
    fs::remove_dir_all(base).unwrap();
}
