// SPDX-License-Identifier: Apache-2.0
//! Copy tmux scrollback, the working directory, or a VCS remote to the clipboard.
use console_tools::{clipboard, tmux, vcs};
#[path = "../cli/cptx.rs"]
mod cptx_cli;
use cptx_cli::{parse_args, Mode, HELP};
use std::{
    env,
    error::Error,
    process::ExitCode,
};

fn run() -> Result<(), Box<dyn Error>> {
    let raw_args = env::args_os().skip(1).collect::<Vec<_>>();
    let args = raw_args.iter().map(|arg| arg.to_str().ok_or("Arguments must be UTF-8")).collect::<Result<Vec<_>, _>>()?;
    let mode = parse_args(&args)?;
    let text = match mode {
        Mode::Help => {
            print!("{HELP}");
            return Ok(());
        }
        Mode::Buffer => tmux::capture()?,
        Mode::Path => env::current_dir()?.to_string_lossy().into_owned(),
        Mode::Version(remote) => vcs::remote_url(remote)?,
    };
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

