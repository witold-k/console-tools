// SPDX-License-Identifier: Apache-2.0
//! Black-box CLI tests; help and argument validation do not require a clipboard.
use std::process::Command;

fn xcat(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_xcat"))
        .args(args)
        .output()
        .expect("xcat binary should run")
}

#[test]
fn help_documents_all_modes() {
    let output = xcat(&["--help"]);
    assert!(output.status.success());
    let stdout = String::from_utf8(output.stdout).unwrap();
    for expected in ["xcat -d <dir>", "xcat -e <file>", "--config", "Justfile", "Makefile", ".ps1"] {
        assert!(stdout.contains(expected), "help missing: {expected}");
    }
}

#[test]
fn unknown_argument_fails() {
    let output = xcat(&["--unknown"]);
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("Unknown argument"));
}

#[test]
fn missing_option_values_fail() {
    for args in [&["-d"][..], &["-e"][..], &["-c"][..]] {
        assert!(!xcat(args).status.success(), "expected failure for {args:?}");
    }
}

#[test]
fn task_arguments_require_execute() {
    let output = xcat(&["--", "anything"]);
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("require -e"));
}
