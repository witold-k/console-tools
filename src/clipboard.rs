// SPDX-License-Identifier: Apache-2.0
//! Copy one complete UTF-8 payload to the desktop clipboard.
//! X11 clipboard owners may stay alive after their input has been written.

#[cfg(not(target_os = "wasi"))]
use std::{io::{self, Write}, process::{Command, Stdio}};

#[cfg(not(target_os = "wasi"))]
fn copy_with(program: &str, args: &[&str], text: &str) -> io::Result<()> {
    // Never pipe stderr from a clipboard owner: X11 tools may fork a daemon
    // which inherits that descriptor, keeping wait_with_output blocked.
    let mut child = Command::new(program)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    let write_result = child.stdin.take().expect("piped stdin").write_all(text.as_bytes());
    // Closing stdin is essential: clipboard tools read until EOF.
    if let Err(error) = write_result {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    // xclip/xsel normally fork an X11 clipboard owner. The initial process
    // exits once ownership has been handed off. Waiting for that initial
    // process is necessary to avoid reporting success before the copy.
    // stderr/stdout are redirected to null so the daemon cannot keep a
    // captured pipe open (the original two-minute hang).
    let status = child.wait()?;
    if status.success() { Ok(()) }
    else { Err(io::Error::other(format!("{program} exited with {status}"))) }
}

/// Copy the complete payload in one operation. Supports Wayland, X11, Windows.
#[cfg(not(target_os = "wasi"))]
pub fn copy(text: &str) -> io::Result<()> {
    #[cfg(windows)]
    {
        let script = "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false); $t=[Console]::In.ReadToEnd(); Set-Clipboard -Value $t";
        return copy_with("powershell.exe", &["-NoProfile", "-NonInteractive", "-Command", script], text);
    }
    #[cfg(not(windows))]
    {
        let mut errors = Vec::new();
        let mut candidates: Vec<(&str, &[&str])> = Vec::new();
        if std::env::var_os("WAYLAND_DISPLAY").is_some() {
            candidates.push(("wl-copy", &["--type", "text/plain;charset=utf-8"]));
        }
        if std::env::var_os("DISPLAY").is_some() {
            candidates.push(("xclip", &["-selection", "clipboard"]));
            candidates.push(("xsel", &["--clipboard", "--input"]));
        }
        if candidates.is_empty() {
            candidates.extend([
                ("wl-copy", &["--type", "text/plain;charset=utf-8"] as &[&str]),
                ("xclip", &["-selection", "clipboard"]),
                ("xsel", &["--clipboard", "--input"]),
            ]);
        }
        for (program, args) in candidates {
            match copy_with(program, args, text) {
                Ok(()) => return Ok(()),
                Err(e) => errors.push(format!("{program}: {e}")),
            }
        }
        Err(io::Error::other(format!("Clipboard unavailable ({})", errors.join("; "))))
    }
}

 
/// WASI has no portable desktop clipboard. The std-only host bridge receives
/// the complete payload from stdout and performs the actual clipboard operation.
#[cfg(target_os = "wasi")]
pub fn copy(text: &str) -> std::io::Result<()> {
    use std::io::Write;
    std::io::stdout().write_all(text.as_bytes())
}
