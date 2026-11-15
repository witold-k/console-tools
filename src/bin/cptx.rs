// SPDX-License-Identifier: Apache-2.0
//! Capture the entire current tmux pane history into the desktop clipboard.
use console_tools::clipboard;
use std::{env, error::Error, io, process::{Command, ExitCode}};

const HELP: &str = "cptx — copy the current tmux pane and its scrollback to the clipboard\n\nUsage: cptx [-h|--help]\n\nRequires tmux and a supported clipboard backend (xclip, xsel, or wl-copy).\n";

fn capture() -> Result<String, Box<dyn Error>> {
    let output = Command::new("tmux")
        .args(["capture-pane", "-p", "-S", "-"])
        .output()?;
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr);
        return Err(io::Error::other(format!(
            "tmux capture-pane failed ({}): {}", output.status, detail.trim()
        )).into());
    }
    Ok(String::from_utf8(output.stdout)?)
}

fn run() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    match (args.next().as_deref(), args.next()) {
        (None, None) => {}
        (Some("-h" | "--help"), None) => { print!("{HELP}"); return Ok(()); }
        _ => return Err("Usage: cptx [-h|--help]".into()),
    }
    let text = capture()?;
    clipboard::copy(&text)?;
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => { eprintln!("cptx: {err}"); ExitCode::FAILURE }
    }
}
