// SPDX-License-Identifier: Apache-2.0
use console_tools::{clipboard, config::Config, runner, scan};
use std::{env, error::Error, fs, path::{Path, PathBuf}, process::ExitCode};

const HELP: &str = r#"xcat — filtered project files and optional task output to clipboard

Usage:
  xcat
  xcat -d <dir>
  xcat -e <file> [-d <dir>] [-- task-arguments...]
  xcat -r <file> [-d <dir>] [-- task-arguments...]
  xcat -h | --help

Options:
  -d, --dir <dir>        Directory to scan (default current directory)
  -e, --execute <file>   Task to execute after the initial clipboard copy
  -r, --run <file>       Run a file standalone; copy its output only
  -c, --config <file>    Override JSON config path
  --                    Pass subsequent arguments unchanged to task

Examples:
  xcat
  xcat -d src
  xcat -e ./test.sh -- --verbose
  xcat -d project -e Justfile -- build
  xcat -e Makefile -- test
  xcat -e script.ps1 -- -Verbose
  xcat -r script.py -- --verbose

Config: XDG_CONFIG_HOME/xcat/config.json or ~/.config/xcat/config.json,
        on Windows APPDATA/xcat/config.json. Automatically created on first use.
Uses aiagents-compatible scanendfilter and scanfullfilter JSON fields.

Execution: Justfile => just --justfile, Makefile => make -f,
           .sh => bash, .ps1 => PowerShell, others => directly.
Copies scan results first, then scan results plus task stdout and stderr.
"#;

#[derive(Debug, PartialEq, Eq)]
struct Options {
    dir: PathBuf,
    execute: Option<PathBuf>,
    standalone: bool,
    config: Option<PathBuf>,
    forwarded: Vec<String>,
    help: bool,
}

fn parse(args: impl IntoIterator<Item = String>) -> Result<Options, String> {
    let mut opts = Options {
        dir: PathBuf::from("."), execute: None, standalone: false, config: None,
        forwarded: Vec::new(), help: false,
    };
    let mut args = args.into_iter();
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-h" | "--help" => { opts.help = true; return Ok(opts); }
            "-d" | "--dir" => opts.dir = PathBuf::from(args.next().ok_or("-d requires a directory")?),
            "-e" | "--execute" => {
                if opts.execute.is_some() { return Err("Only one of -e and -r may be supplied".into()); }
                opts.execute = Some(PathBuf::from(args.next().ok_or("-e requires a file")?));
            },
            "-r" | "--run" => {
                if opts.execute.is_some() { return Err("Only one of -e and -r may be supplied".into()); }
                opts.execute = Some(PathBuf::from(args.next().ok_or("-r requires a file")?));
                opts.standalone = true;
            },
            "-c" | "--config" => opts.config = Some(PathBuf::from(args.next().ok_or("-c requires a file")?)),
            "--" => { opts.forwarded.extend(args); break; }
            _ => return Err(format!("Unknown argument: {arg}. Run xcat --help.")),
        }
    }
    if opts.execute.is_none() && !opts.forwarded.is_empty() {
        return Err("-- arguments require -e".into());
    }
    Ok(opts)
}

fn run_task(file: &Path, args: &[String], root: &Path) -> Result<(String, bool), Box<dyn Error>> {
    let output = runner::command(file, args, root)?.output()?;
    // Combined clipboard artifact contains both streams, separated to avoid ambiguity.
    let mut content = format!("
===== EXECUTABLE OUTPUT: {} =====
", file.display());
    content.push_str("===== STDOUT =====
");
    content.push_str(&String::from_utf8_lossy(&output.stdout));
    if !content.ends_with('\n') { content.push('\n'); }
    content.push_str("===== STDERR =====
");
    content.push_str(&String::from_utf8_lossy(&output.stderr));
    if !content.ends_with('\n') { content.push('\n'); }
    content.push_str(&format!("===== EXIT STATUS: {} =====
", output.status.code().map_or_else(|| "terminated by signal".to_string(), |code| code.to_string())));
    Ok((content, output.status.success()))
}

fn run() -> Result<bool, Box<dyn Error>> {
    let opts = parse(env::args().skip(1))?;
    if opts.help { print!("{HELP}"); return Ok(true); }
    let root = opts.dir.canonicalize()?;
    if !root.is_dir() {
        return Err(format!("Not a directory: {}", root.display()).into());
    }
    let task = match opts.execute {
        Some(path) => {
            let path = if path.is_absolute() { path } else { root.join(path) };
            let canonical = fs::canonicalize(&path)?;
            if !canonical.is_file() { return Err(format!("Not a task file: {}", canonical.display()).into()); }
            Some(canonical)
        }
        None => None,
    };
    if opts.standalone {
        let task = task.expect("-r requires a file");
        let (output, success) = run_task(&task, &opts.forwarded, &root)?;
        clipboard::copy(&output)?;
        eprintln!("Copied task stdout/stderr to clipboard.");
        return Ok(success);
    }
    let config_file = match opts.config {
        Some(path) => path, None => Config::default_path()?,
    };
    let config = Config::load_or_create(&config_file)?;
    let (mut text, files) = scan::collect(&root, &config)?;
    clipboard::copy(&text)?;
    eprintln!("Copied {files} scanned files to clipboard.");
    let Some(task) = task else { return Ok(true); };
    let (output, success) = match run_task(&task, &opts.forwarded, &root) {
        Ok(value) => value,
        Err(err) => {
            text.push_str(&format!("
===== EXECUTION ERROR: {} =====
{err}
", task.display()));
            clipboard::copy(&text)?;
            return Err(err);
        }
    };
    text.push_str(&output);
    clipboard::copy(&text)?;
    eprintln!("Copied scanned files and task stdout/stderr to clipboard.");
    Ok(success)
}

fn main() -> ExitCode {
    match run() {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::FAILURE,
        Err(err) => { eprintln!("xcat: {err}"); ExitCode::FAILURE }
    }
}
