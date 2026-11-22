// SPDX-License-Identifier: Apache-2.0
//! Copy one complete UTF-8 payload to the desktop clipboard.
//! X11 clipboard owners may stay alive after their input has been written.

#[cfg(not(target_os = "wasi"))]
use std::{
    io::{self, Write},
    process::{Command, Stdio},
};

/// Ordered clipboard commands, shared between native Rust and JVM/WASI.
fn candidates() -> Vec<(&'static str, &'static [&'static str])> {
    let mut result = Vec::new();
    if std::env::var_os("WAYLAND_DISPLAY").is_some() {
        result.push((
            "wl-copy",
            &["--type", "text/plain;charset=utf-8"] as &[&str],
        ));
    }
    if std::env::var_os("DISPLAY").is_some() {
        result.push(("xclip", &["-selection", "clipboard"]));
        result.push(("xsel", &["--clipboard", "--input"]));
    }
    if result.is_empty() {
        result.extend([
            (
                "wl-copy",
                &["--type", "text/plain;charset=utf-8"] as &[&str],
            ),
            ("xclip", &["-selection", "clipboard"]),
            ("xsel", &["--clipboard", "--input"]),
        ]);
    }
    result
}

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
    let write_result = child
        .stdin
        .take()
        .expect("piped stdin")
        .write_all(text.as_bytes());
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
    if status.success() {
        Ok(())
    } else {
        Err(io::Error::other(format!("{program} exited with {status}")))
    }
}

/// Copy the complete payload in one operation. Supports Wayland, X11, Windows.
#[cfg(not(target_os = "wasi"))]
pub fn copy(text: &str) -> io::Result<()> {
    #[cfg(windows)]
    {
        let script = "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false); $t=[Console]::In.ReadToEnd(); Set-Clipboard -Value $t";
        return copy_with(
            "powershell.exe",
            &["-NoProfile", "-NonInteractive", "-Command", script],
            text,
        );
    }
    #[cfg(not(windows))]
    {
        let mut errors = Vec::new();
        for (program, args) in candidates() {
            match copy_with(program, args, text) {
                Ok(()) => return Ok(()),
                Err(e) => errors.push(format!("{program}: {e}")),
            }
        }
        Err(io::Error::other(format!(
            "Clipboard unavailable ({})",
            errors.join("; ")
        )))
    }
}

/// WASI has no portable desktop clipboard. The std-only host bridge receives
/// the complete payload from stdout and performs the actual clipboard operation.
#[cfg(target_os = "wasi")]
pub fn copy(text: &str) -> std::io::Result<()> {
    use std::io::Write;
    let mut output = std::io::stdout().lock();
    if std::env::var_os("CONSOLE_TOOLS_JVM_CLIPBOARD").is_some() {
        output.write_all(b"CTCLIP1\0")?;
        let commands = candidates();
        output.write_all(&[commands.len() as u8])?;
        for (program, args) in commands {
            output.write_all(program.as_bytes())?;
            output.write_all(&[0, args.len() as u8])?;
            for arg in args {
                output.write_all(arg.as_bytes())?;
                output.write_all(&[0])?;
            }
        }
    }
    output.write_all(text.as_bytes())
}
