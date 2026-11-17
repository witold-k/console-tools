// SPDX-License-Identifier: Apache-2.0
use console_tools::{clipboard, config::Config, runner, scan, task_report, xcat_options};
use std::{env, error::Error, fs, path::Path, process::ExitCode};

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

fn run_task(file: &Path, args: &[String], root: &Path) -> Result<(String, bool), Box<dyn Error>> {
    let output = runner::command(file, args, root)?.output()?;
    let status = output.status.code().map_or_else(|| "terminated by signal".to_string(), |code| code.to_string());
    let content = task_report::format_task_output(file, &output.stdout, &output.stderr, &status);
    Ok((content, output.status.success()))
}

fn run() -> Result<bool, Box<dyn Error>> {
    let opts = xcat_options::parse(env::args().skip(1))?;
    if opts.help { print!("{HELP}"); return Ok(true); }
    #[cfg(target_os = "wasi")]
    if opts.execute.is_some() {
        return Err("WASI cannot launch tasks: use wasm-host xcat ...".into());
    }
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

// Formatting runs inside WASM too: the host only launches the task and passes
// its captured streams through preopened temporary files.
#[cfg(target_os = "wasi")]
fn wasm_report(args: &[String]) -> Result<(), Box<dyn Error>> {
    if args.len() != 5 {
        return Err("usage: xcat --wasm-task-report <task> <stdout-file> <stderr-file> <status>".into());
    }
    let stdout = fs::read(&args[2])?;
    let stderr = fs::read(&args[3])?;
    print!("{}", task_report::format_task_output(
        Path::new(&args[1]), &stdout, &stderr, &args[4]));
    Ok(())
}

fn main() -> ExitCode {
    #[cfg(target_os = "wasi")]
    {
        let args: Vec<String> = env::args().skip(1).collect();
        if args.first().is_some_and(|a| a == "--wasm-task-report") {
            return match wasm_report(&args) {
                Ok(()) => ExitCode::SUCCESS,
                Err(err) => { eprintln!("xcat: {err}"); ExitCode::FAILURE }
            };
        }
    }

    match run() {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::FAILURE,
        Err(err) => { eprintln!("xcat: {err}"); ExitCode::FAILURE }
    }
}
