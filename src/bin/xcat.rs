// SPDX-License-Identifier: Apache-2.0
use console_tools::{clipboard, config::Config, scan};
use std::{env, error::Error, fs, path::{Path, PathBuf}, process::{Command, ExitCode}};

const HELP: &str = r#"xcat — filtered project files and optional task output to clipboard

Usage:
  xcat
  xcat -d <dir>
  xcat -e <file> [-d <dir>] [-- task-arguments...]
  xcat -h | --help

Options:
  -d, --dir <dir>        Directory to scan (default current directory)
  -e, --execute <file>   Task to execute after the initial clipboard copy
  -c, --config <file>    Override JSON config path
  --                    Pass subsequent arguments unchanged to task

Examples:
  xcat
  xcat -d src
  xcat -e ./test.sh -- --verbose
  xcat -d project -e Justfile -- build
  xcat -e Makefile -- test
  xcat -e script.ps1 -- -Verbose

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
    config: Option<PathBuf>,
    forwarded: Vec<String>,
    help: bool,
}

fn parse(args: impl IntoIterator<Item = String>) -> Result<Options, String> {
    let mut opts = Options {
        dir: PathBuf::from("."), execute: None, config: None,
        forwarded: Vec::new(), help: false,
    };
    let mut args = args.into_iter();
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-h" | "--help" => { opts.help = true; return Ok(opts); }
            "-d" | "--dir" => opts.dir = PathBuf::from(args.next().ok_or("-d requires a directory")?),
            "-e" | "--execute" => opts.execute = Some(PathBuf::from(args.next().ok_or("-e requires a file")?)),
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

fn execution_command(file: &Path, args: &[String], root: &Path) -> Result<Command, Box<dyn Error>> {
    let file = if file.is_absolute() { file.to_path_buf() } else { root.join(file) };
    if !file.is_file() {
        return Err(format!("Task file does not exist: {}", file.display()).into());
    }
    let name = file.file_name().and_then(|x| x.to_str()).unwrap_or("");
    let ext = file.extension().and_then(|x| x.to_str()).unwrap_or("").to_ascii_lowercase();
    let mut cmd = if name.eq_ignore_ascii_case("justfile") {
        let mut c = Command::new("just");
        c.arg("--justfile").arg(&file);
        c
    } else if name == "Makefile" || name == "makefile" || name == "GNUmakefile" {
        let mut c = Command::new("make");
        c.arg("-f").arg(&file);
        c
    } else if ext == "sh" {
        let mut c = Command::new("bash");
        c.arg(&file);
        c
    } else if ext == "ps1" {
        let mut c = Command::new(if cfg!(windows) { "powershell.exe" } else { "pwsh" });
        c.arg("-NoProfile").arg("-File").arg(&file);
        c
    } else {
        Command::new(&file)
    };
    cmd.args(args).current_dir(root);
    Ok(cmd)
}

fn run_task(file: &Path, args: &[String], root: &Path) -> Result<(String, bool), Box<dyn Error>> {
    let output = execution_command(file, args, root)?.output()?;
    // Combined clipboard artifact contains both streams, separated to avoid ambiguity.
    let mut content = format!("\n===== EXECUTABLE OUTPUT: {} =====\n", file.display());
    content.push_str("===== STDOUT =====\n");
    content.push_str(&String::from_utf8_lossy(&output.stdout));
    if !content.ends_with('\n') { content.push('\n'); }
    content.push_str("===== STDERR =====\n");
    content.push_str(&String::from_utf8_lossy(&output.stderr));
    if !content.ends_with('\n') { content.push('\n'); }
    content.push_str(&format!("===== EXIT STATUS: {} =====\n", output.status));
    Ok((content, output.status.success()))
}

fn run() -> Result<bool, Box<dyn Error>> {
    let opts = parse(env::args().skip(1))?;
    if opts.help { print!("{HELP}"); return Ok(true); }
    let root = opts.dir.canonicalize()?;
    if !root.is_dir() {
        return Err(format!("Not a directory: {}", root.display()).into());
    }
    let config_file = match opts.config {
        Some(path) => path, None => Config::default_path()?,
    };
    let config = Config::load_or_create(&config_file)?;
    let (mut text, files) = scan::collect(&root, &config)?;
    let task = match opts.execute {
        Some(path) => {
            let path = if path.is_absolute() { path } else { root.join(path) };
            let canonical = fs::canonicalize(&path)?;
            if !canonical.is_file() {
                return Err(format!("Not a task file: {}", canonical.display()).into());
            }
            Some(canonical)
        }
        None => None,
    };
    clipboard::copy(&text)?;
    eprintln!("Copied {files} scanned files to clipboard.");
    let Some(task) = task else { return Ok(true); };
    let (output, success) = match run_task(&task, &opts.forwarded, &root) {
        Ok(value) => value,
        Err(err) => {
            text.push_str(&format!("\n===== EXECUTION ERROR: {} =====\n{err}\n", task.display()));
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
