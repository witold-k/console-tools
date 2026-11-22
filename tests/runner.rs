// SPDX-License-Identifier: Apache-2.0
use console_tools::runner;
use std::{
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

fn fixture(extension: &str, contents: &[u8]) -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "console-tools-runner-{}-{stamp}.{extension}",
        std::process::id()
    ));
    fs::write(&path, contents).unwrap();
    path
}

#[test]
fn chooses_python_for_non_executable_script() {
    let path = fixture("py", b"print('ok')\n");
    let cmd = runner::command(&path, &[], path.parent().unwrap()).unwrap();
    assert_eq!(cmd.get_program(), "python3");
    assert_eq!(cmd.get_args().next().unwrap(), path.as_os_str());
    fs::remove_file(path).unwrap();
}

#[test]
fn rejects_unknown_non_executable_file() {
    let path = fixture("unknown", b"plain text\n");
    assert!(runner::command(&path, &[], path.parent().unwrap()).is_err());
    fs::remove_file(path).unwrap();
}

#[cfg(unix)]
#[test]
fn executes_executable_without_interpreter() {
    use std::os::unix::fs::PermissionsExt;
    let path = fixture("sh", b"#!/bin/sh\nprintf ok\n");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
    let cmd = runner::command(&path, &[], path.parent().unwrap()).unwrap();
    assert_eq!(cmd.get_program(), path.as_os_str());
    fs::remove_file(path).unwrap();
}
