// SPDX-License-Identifier: Apache-2.0
use std::process::Command;

fn cptx(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_cptx")).args(args).output().unwrap()
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
