// SPDX-License-Identifier: Apache-2.0
//! Select an appropriate launcher for a local executable, script, or build file.
use std::{fs, io, path::Path, process::Command};

pub fn command(file: &Path, args: &[String], root: &Path) -> io::Result<Command> {
    if !file.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!("Not a file: {}", file.display()),
        ));
    }
    let name = file.file_name().and_then(|s| s.to_str()).unwrap_or("");
    let ext = file
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let mut cmd = if name.eq_ignore_ascii_case("justfile") {
        let mut c = Command::new("just");
        c.arg("--justfile").arg(file);
        c
    } else if ["Makefile", "makefile", "GNUmakefile"].contains(&name) {
        let mut c = Command::new("make");
        c.arg("-f").arg(file);
        c
    } else if is_executable(file)? || looks_binary(file)? {
        Command::new(file)
    } else {
        let interpreter = match ext.as_str() {
            "sh" | "bash" => "bash",
            "py" => "python3",
            "lua" => "lua",
            "rb" => "ruby",
            "pl" => "perl",
            "js" | "mjs" => "node",
            "ps1" => {
                if cfg!(windows) {
                    "powershell.exe"
                } else {
                    "pwsh"
                }
            }
            _ => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!(
                        "Unknown file type: {} (make it executable or use a recognized extension)",
                        file.display()
                    ),
                ));
            }
        };
        let mut c = Command::new(interpreter);
        if ext == "ps1" {
            c.arg("-NoProfile").arg("-File");
        }
        c.arg(file);
        c
    };
    cmd.args(args).current_dir(root);
    Ok(cmd)
}

fn looks_binary(path: &Path) -> io::Result<bool> {
    use std::io::Read;
    let mut file = fs::File::open(path)?;
    let mut bytes = [0u8; 4];
    let n = file.read(&mut bytes)?;
    Ok(n >= 4
        && (&bytes == b"\x7fELF"
            || &bytes[..2] == b"MZ"
            || bytes == [0xfe, 0xed, 0xfa, 0xce]
            || bytes == [0xcf, 0xfa, 0xed, 0xfe]))
}

#[cfg(unix)]
fn is_executable(path: &Path) -> io::Result<bool> {
    use std::os::unix::fs::PermissionsExt;
    Ok(fs::metadata(path)?.permissions().mode() & 0o111 != 0)
}
#[cfg(not(unix))]
fn is_executable(_path: &Path) -> io::Result<bool> {
    Ok(false)
}
