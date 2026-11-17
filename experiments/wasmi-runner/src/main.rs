// SPDX-License-Identifier: Apache-2.0
//! Minimal native Wasmi + WASI Preview 1 runner.
//! CLI: console-tools-wasmi-runner run --dir HOST::GUEST MODULE.wasm [args...]
//! The existing wasm-host can select this runner using CONSOLE_TOOLS_WASM_RUNNER.
use std::{env, error::Error, fs, path::Path, process::ExitCode};
use wasmi::{Engine, Instance, Module, Store};
use wasmi_wasi::{ambient_authority, Dir, WasiCtxBuilder};

fn run() -> Result<i32, Box<dyn Error>> {
    let mut args = env::args().skip(1);
    if args.next().as_deref() != Some("run") {
        return Err("usage: console-tools-wasmi-runner run [--dir HOST::GUEST] MODULE.wasm [args...]".into());
    }
    let mut mounts = Vec::new();
    let module_path = loop {
        let arg = args.next().ok_or("missing WASM module")?;
        if arg == "--dir" {
            let spec = args.next().ok_or("--dir needs HOST::GUEST")?;
            let (host, guest) = spec.split_once("::").ok_or("expected HOST::GUEST")?;
            mounts.push((host.to_owned(), guest.to_owned()));
        } else {
            break arg;
        }
    };
    let mut builder = WasiCtxBuilder::new();
    let wasm_args = std::iter::once(module_path.clone()).chain(args).collect::<Vec<_>>();
    builder.args(&wasm_args)?;
    builder.inherit_stdio();
    for (host, guest) in mounts {
        let dir = Dir::open_ambient_dir(Path::new(&host), ambient_authority())?;
        builder.preopened_dir(dir, guest)?;
    }
    let engine = Engine::default();
    let bytes = fs::read(&module_path)?;
    let module = Module::new(&engine, &bytes[..])?;
    let mut store = Store::new(&engine, builder.build());
    let mut externals = Vec::new();
    wasmi_wasi::add_to_externals(&mut store, &module, &mut externals, |ctx| ctx)?;
    let instance = Instance::new(&mut store, &module, &externals)?;
    let start = instance.get_func(&store, "_start").ok_or("missing _start export")?;
    match start.call(&mut store, &[], &mut []) {
        Ok(()) => Ok(0),
        Err(error) => match error.i32_exit_status() {
            Some(code) => Ok(code),
            None => Err(error.into()),
        },
    }
}

fn main() -> ExitCode {
    match run() {
        Ok(0) => ExitCode::SUCCESS,
        Ok(code) => {
            eprintln!("WASM exited with status {code}");
            ExitCode::FAILURE
        }
        Err(error) => {
            eprintln!("wasmi-runner: {error}");
            ExitCode::FAILURE
        }
    }
}
