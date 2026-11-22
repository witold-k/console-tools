// SPDX-License-Identifier: Apache-2.0
//! Capture the entire current tmux pane history into the desktop clipboard.
use console_tools::{clipboard, tmux};
use std::{env, error::Error, process::ExitCode};

const HELP: &str = "cptx — copy the current tmux pane and its scrollback to the clipboard\n\nUsage: cptx [-h|--help]\n\nRequires tmux and a supported clipboard backend (xclip, xsel, or wl-copy).\n";

fn run() -> Result<(), Box<dyn Error>> {
    let mut args = env::args_os().skip(1);
    match (args.next().as_deref(), args.next()) {
        (None, None) => {}
        (Some(arg), None) if arg == "-h" || arg == "--help" => {
            print!("{HELP}");
            return Ok(());
        }
        _ => return Err("Usage: cptx [-h|--help]".into()),
    }
    let text = tmux::capture()?;
    clipboard::copy(&text)?;
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("cptx: {err}");
            ExitCode::FAILURE
        }
    }
}
