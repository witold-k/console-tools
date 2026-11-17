// SPDX-License-Identifier: Apache-2.0
//! Native OS-only bridge for the std-only WASI xcat/cptx modules.
//! No duplicate app logic: args, task dispatch, tmux and clipboard are
//! shared Rust modules. WASM performs scanning and output formatting.
use console_tools::{clipboard, config::Config, runner, tmux, xcat_options};
use std::{
    env, error::Error, fs, io::{self, Write},
    path::{Path, PathBuf},
    process::{Command, ExitCode, Stdio},
    thread,
    time::{SystemTime, UNIX_EPOCH},
};

fn module_path(name: &str) -> PathBuf {
    let directory = env::var_os("CONSOLE_TOOLS_WASM_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
            // Cargo puts artifacts in the workspace root, not necessarily
            // in the package directory. Prefer the nearest existing module.
            manifest.ancestors()
                .map(|dir| dir.join("target/wasm32-wasip1/release"))
                .find(|dir| dir.join(format!("{name}.wasm")).is_file())
                .unwrap_or_else(|| manifest.join("target/wasm32-wasip1/release"))
        });
    directory.join(format!("{name}.wasm"))
}

/// Run an actual WASI module. Mounts are host::guest mappings. The host
/// never interprets scanner data, JSON settings or task report contents.
fn wasm_run(
    tool: &str,
    args: &[String],
    mounts: &[(&Path, &str)],
    input: Option<&[u8]>,
) -> Result<Vec<u8>, Box<dyn Error>> {
    let module = module_path(tool);
    if !module.is_file() {
        return Err(format!("missing {}; run 'just build-wasm'", module.display()).into());
    }
    let runner = env::var_os("CONSOLE_TOOLS_WASM_RUNNER")
        .unwrap_or_else(|| "wasmtime".into());
    let mut command = Command::new(runner);
    command.arg("run");
    for (host, guest) in mounts {
        command.arg("--dir").arg(format!("{}::{guest}", host.display()));
    }
    command.arg(&module).args(args)
        .stdout(Stdio::piped()).stderr(Stdio::inherit())
        .stdin(if input.is_some() { Stdio::piped() } else { Stdio::null() });
    let mut child = command.spawn()?;

    // Drain stdout concurrently to avoid deadlocks with large tmux scrollback.
    let writer = if let Some(bytes) = input {
        let mut stdin = child.stdin.take().ok_or("missing WASI stdin pipe")?;
        let bytes = bytes.to_vec();
        Some(thread::spawn(move || stdin.write_all(&bytes)))
    } else {
        None
    };
    let output = child.wait_with_output()?;
    if let Some(writer) = writer {
        writer.join().map_err(|_| "WASI stdin writer panicked")??;
    }
    if !output.status.success() {
        return Err(format!("{tool}.wasm exited with {}", output.status).into());
    }
    Ok(output.stdout)
}

struct TempDirectory(PathBuf);
impl TempDirectory {
    fn new() -> io::Result<Self> {
        let nanos = SystemTime::now().duration_since(UNIX_EPOCH)
            .map_err(io::Error::other)?.as_nanos();
        for suffix in 0..32u32 {
            let path = env::temp_dir().join(format!(
                "console-tools-wasm-{}-{nanos}-{suffix}", std::process::id()));
            match fs::create_dir(&path) {
                Ok(()) => return Ok(Self(path)),
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(e) => return Err(e),
            }
        }
        Err(io::Error::new(io::ErrorKind::AlreadyExists, "temporary directory unavailable"))
    }
}
impl Drop for TempDirectory {
    fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
}

fn report(file: &Path, args: &[String], root: &Path) -> Result<(String, bool), Box<dyn Error>> {
    // Reuse the existing Rust launcher; no second interpreter selection logic.
    let output = runner::command(file, args, root)?.output()?;
    let success = output.status.success();
    let status = output.status.code()
        .map_or_else(|| "terminated by signal".to_string(), |n| n.to_string());
    let temp = TempDirectory::new()?;
    fs::write(temp.0.join("stdout"), &output.stdout)?;
    fs::write(temp.0.join("stderr"), &output.stderr)?;
    let args = vec![
        "--wasm-task-report".to_string(),
        file.to_string_lossy().into_owned(),
        "/report/stdout".to_string(),
        "/report/stderr".to_string(),
        status,
    ];
    let bytes = wasm_run("xcat", &args, &[(&temp.0, "/report")], None)?;
    Ok((String::from_utf8(bytes)?, success))
}

fn cptx(args: &[String]) -> Result<bool, Box<dyn Error>> {
    if !args.is_empty() {
        let result = wasm_run("cptx", args, &[], None)?;
        io::stdout().write_all(&result)?;
        return Ok(true);
    }
    let capture = tmux::capture()?;
    let output = wasm_run("cptx", &[], &[], Some(capture.as_bytes()))?;
    clipboard::copy(std::str::from_utf8(&output)?)?;
    Ok(true)
}

fn xcat(args: &[String]) -> Result<bool, Box<dyn Error>> {
    let opts = xcat_options::parse(args.iter().cloned())?;
    if opts.help {
        let output = wasm_run("xcat", &["--help".to_string()], &[], None)?;
        io::stdout().write_all(&output)?;
        return Ok(true);
    }
    let root = opts.dir.canonicalize()?;
    if !root.is_dir() { return Err(format!("Not a directory: {}", root.display()).into()); }
    let task = if let Some(path) = opts.execute {
        let path = if path.is_absolute() { path } else { root.join(path) };
        let canonical = path.canonicalize()?;
        if !canonical.is_file() {
            return Err(format!("Not a task file: {}", canonical.display()).into());
        }
        Some(canonical)
    } else { None };

    if opts.standalone {
        let task = task.ok_or("-r requires a file")?;
        let (text, success) = report(&task, &opts.forwarded, &root)?;
        clipboard::copy(&text)?;
        eprintln!("Copied task stdout/stderr to clipboard.");
        return Ok(success);
    }

    let config = match opts.config { Some(path) => path, None => Config::default_path()? };
    let config = if config.is_absolute() { config } else { env::current_dir()?.join(config) };
    let config_parent = config.parent().ok_or("configuration has no parent directory")?;
    fs::create_dir_all(config_parent)?;
    let config_name = config.file_name().ok_or("configuration has no filename")?;
    let arguments = vec!["-d".to_string(), "/work".to_string(),
        "-c".to_string(), format!("/cfg/{}", config_name.to_string_lossy())];
    let scan = wasm_run("xcat", &arguments, &[(&root, "/work"), (config_parent, "/cfg")], None)?;
    let mut text = String::from_utf8(scan)?;
    clipboard::copy(&text)?;
    eprintln!("Copied scanned project files to clipboard.");
    let Some(task) = task else { return Ok(true) };

    let (extra, success) = match report(&task, &opts.forwarded, &root) {
        Ok(value) => value,
        Err(err) => {
            text.push_str(&format!(
                "\n===== EXECUTION ERROR: {} =====\n{err}\n", task.display()));
            clipboard::copy(&text)?;
            return Err(err);
        }
    };
    text.push_str(&extra);
    clipboard::copy(&text)?;
    eprintln!("Copied scanned files and task stdout/stderr to clipboard.");
    Ok(success)
}

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let Some(program) = args.next() else {
        eprintln!("Usage: wasm-host {{xcat|cptx}} [arguments...]");
        return ExitCode::FAILURE;
    };
    let rest: Vec<String> = args.collect();
    let result = match program.as_str() {
        "xcat" => xcat(&rest),
        "cptx" => cptx(&rest),
        _ => Err(format!("Unknown tool '{program}' (expected xcat or cptx)").into()),
    };
    match result {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::FAILURE,
        Err(err) => { eprintln!("{program}-wasm: {err}"); ExitCode::FAILURE }
    }
}
