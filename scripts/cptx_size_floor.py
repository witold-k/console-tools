#!/usr/bin/env python3
"""Measure the WASI/Rust standard-library size floor for cptx.

Build isolated, dependency-free Rust fixtures with the same target and release
optimization intent as cptx. No repository sources or release artifacts change.
Fixture sizes are NOT additive attribution of Rust standard-library functions.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGET = "wasm32-wasip1"
FIXTURES = {
    "empty": r"""fn main() {}""",
    "args": r"""fn main() { let mut a = std::env::args().skip(1); if let Some(v) = a.next() { if v == "--help" { print!("help"); } } }""",
    "stdin_stdout_bytes": r"""use std::io::{Read, Write}; fn main() { let mut b = Vec::new(); std::io::stdin().read_to_end(&mut b).unwrap(); std::io::stdout().write_all(&b).unwrap(); }""",
    "stdin_stdout_utf8": r"""use std::io::{Read, Write}; fn main() { let mut b = Vec::new(); std::io::stdin().read_to_end(&mut b).unwrap(); let s = String::from_utf8(b).unwrap(); std::io::stdout().write_all(s.as_bytes()).unwrap(); }""",
    "stdin_stdout_utf8_result": r"""use std::{error::Error,io::{self,Read,Write},process::ExitCode}; fn run()->Result<(),Box<dyn Error>> {let mut b=Vec::new();io::stdin().read_to_end(&mut b)?;let s=String::from_utf8(b)?;io::stdout().write_all(s.as_bytes())?;Ok(())} fn main()->ExitCode{match run(){Ok(())=>ExitCode::SUCCESS,Err(e)=>{eprintln!("cptx: {e}");ExitCode::FAILURE}}}""",
    "args_os": r"""fn main() { let mut a = std::env::args_os().skip(1); if let Some(v) = a.next() { if v == "--help" { print!("help"); } } }""",
    "args_exact": r"""fn main() { let mut a = std::env::args().skip(1); match (a.next().as_deref(), a.next()) { (None,None)=>{}, (Some("-h"|"--help"),None)=>print!("help"), _=>eprintln!("usage") } }""",
    "args_os_exact": r"""fn main() { let mut a = std::env::args_os().skip(1); match (a.next(), a.next()) { (None,None)=>{}, (Some(v),None) if v=="-h" || v=="--help"=>print!("help"), _=>eprintln!("usage") } }""",
    "cptx_args_os": r"""use std::{env,error::Error,io::{self,Read,Write},process::ExitCode}; const HELP:&str="cptx — copy the current tmux pane and its scrollback to the clipboard\\n\\nUsage: cptx [-h|--help]\\n\\nRequires tmux and a supported clipboard backend (xclip, xsel, or wl-copy).\\n";fn run()->Result<(),Box<dyn Error>>{let mut args=env::args_os().skip(1);match(args.next(),args.next()){(None,None)=>{},(Some(v),None) if v=="-h" || v=="--help"=>{print!("{HELP}");return Ok(())},_=>return Err("Usage: cptx [-h|--help]".into())}let mut b=Vec::new();io::stdin().read_to_end(&mut b)?;let s=String::from_utf8(b)?;io::stdout().write_all(s.as_bytes())?;Ok(())}fn main()->ExitCode{match run(){Ok(())=>ExitCode::SUCCESS,Err(e)=>{eprintln!("cptx: {e}");ExitCode::FAILURE}}}""",
    "cptx_borrowed_utf8": r"""use std::{env,error::Error,io::{self,Read,Write},process::ExitCode}; const HELP:&str="cptx — copy the current tmux pane and its scrollback to the clipboard\\n\\nUsage: cptx [-h|--help]\\n\\nRequires tmux and a supported clipboard backend (xclip, xsel, or wl-copy).\\n";fn run()->Result<(),Box<dyn Error>>{let mut args=env::args_os().skip(1);match(args.next(),args.next()){(None,None)=>{},(Some(v),None) if v=="-h" || v=="--help"=>{print!("{HELP}");return Ok(())},_=>return Err("Usage: cptx [-h|--help]".into())}let mut b=Vec::new();io::stdin().read_to_end(&mut b)?;let s=std::str::from_utf8(&b)?;io::stdout().write_all(s.as_bytes())?;Ok(())}fn main()->ExitCode{match run(){Ok(())=>ExitCode::SUCCESS,Err(e)=>{eprintln!("cptx: {e}");ExitCode::FAILURE}}}""",
    "cptx_bytes_unchecked": r"""use std::{env,error::Error,io::{self,Read,Write},process::ExitCode}; const HELP:&str="cptx — copy the current tmux pane and its scrollback to the clipboard\\n\\nUsage: cptx [-h|--help]\\n\\nRequires tmux and a supported clipboard backend (xclip, xsel, or wl-copy).\\n";fn run()->Result<(),Box<dyn Error>>{let mut args=env::args_os().skip(1);match(args.next(),args.next()){(None,None)=>{},(Some(v),None) if v=="-h" || v=="--help"=>{print!("{HELP}");return Ok(())},_=>return Err("Usage: cptx [-h|--help]".into())}let mut b=Vec::new();io::stdin().read_to_end(&mut b)?;io::stdout().write_all(&b)?;Ok(())}fn main()->ExitCode{match run(){Ok(())=>ExitCode::SUCCESS,Err(e)=>{eprintln!("cptx: {e}");ExitCode::FAILURE}}}""",
    "cptx_equivalent": r"""use std::{env,error::Error,io::{self,Read,Write},process::ExitCode}; const HELP:&str="cptx — copy the current tmux pane and its scrollback to the clipboard\n\nUsage: cptx [-h|--help]\n\nRequires tmux and a supported clipboard backend (xclip, xsel, or wl-copy).\n";fn run()->Result<(),Box<dyn Error>>{let mut args=env::args().skip(1);match(args.next().as_deref(),args.next()){(None,None)=>{},(Some("-h"|"--help"),None)=>{print!("{HELP}");return Ok(())},_=>return Err("Usage: cptx [-h|--help]".into())}let mut b=Vec::new();io::stdin().read_to_end(&mut b)?;let s=String::from_utf8(b)?;io::stdout().write_all(s.as_bytes())?;Ok(())}fn main()->ExitCode{match run(){Ok(())=>ExitCode::SUCCESS,Err(e)=>{eprintln!("cptx: {e}");ExitCode::FAILURE}}}""",
}


def run(cmd: list[str], **kwargs) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, **kwargs)


def target_dir() -> Path:
    p = subprocess.run(["cargo", "metadata", "--no-deps", "--format-version", "1"],
                       cwd=ROOT, check=True, capture_output=True, text=True)
    return Path(json.loads(p.stdout)["target_directory"])


def wasm_code_size(path: Path) -> int:
    data = path.read_bytes()
    if data[:8] != b"\0asm\x01\0\0\0":
        raise ValueError(f"Not a WASM v1 module: {path}")
    def uleb(at: int) -> tuple[int, int]:
        val = 0
        for shift in range(0, 70, 7):
            if at >= len(data):
                raise ValueError("Truncated LEB128")
            b = data[at]
            at += 1
            val |= (b & 127) << shift
            if b < 128:
                return val, at
        raise ValueError("LEB128 too long")
    at = 8
    while at < len(data):
        kind = data[at]
        at += 1
        size, at = uleb(at)
        end = at + size
        if end > len(data):
            raise ValueError("Truncated section")
        if kind == 10:
            return size
        at = end
    return 0


def main() -> None:
    target = target_dir()
    baseline = target / TARGET / "release/cptx.wasm"
    if not baseline.is_file():
        raise FileNotFoundError(f"{baseline}; run just build-wasm")
    rustc = shutil.which("rustc")
    if not rustc:
        raise RuntimeError("rustc not found")
    optimizer = shutil.which("wasm-opt")
    rows: list[tuple[str, int, int]] = []
    with tempfile.TemporaryDirectory(prefix="cptx-size-floor-") as d:
        tmp = Path(d)
        for name, code in FIXTURES.items():
            source = tmp / f"{name}.rs"
            wasm = tmp / f"{name}.wasm"
            source.write_text(code, encoding="utf-8")
            run([rustc, "--edition=2024", "--target", TARGET, str(source),
                 "-o", str(wasm), "-C", "opt-level=z", "-C", "lto=fat",
                 "-C", "codegen-units=1", "-C", "panic=abort",
                 "-C", "strip=symbols"])
            if optimizer:
                optimized = tmp / f"{name}.opt.wasm"
                run([optimizer, "-Oz", "--enable-bulk-memory", "--strip-debug",
                     "--strip-producers", str(wasm), "-o", str(optimized)])
                if optimized.stat().st_size < wasm.stat().st_size:
                    wasm = optimized
            rows.append((name, wasm.stat().st_size, wasm_code_size(wasm)))
    rows.append(("ACTUAL cptx", baseline.stat().st_size, wasm_code_size(baseline)))
    print("\nWASI code-size profile (independent builds; NOT additive):")
    print(f"  {'Variant':<28} {'WASM bytes':>12} {'code section':>14}")
    for name, size, code in rows:
        print(f"  {name:<28} {size:>12,} {code:>14,}")
    floor = dict((name, size) for name, size, _ in rows)
    print(f"\n  Actual cptx vs cptx_equivalent fixture: "
          f"{floor['ACTUAL cptx'] - floor['cptx_equivalent']:+,} bytes")
    print(f"  Full cptx args_os vs args(): "
          f"{floor['cptx_args_os'] - floor['cptx_equivalent']:+,} bytes")
    print(f"  Raw byte copy vs UTF-8-checked cptx (both args_os): "
          f"{floor['cptx_bytes_unchecked'] - floor['cptx_args_os']:+,} bytes")
    print(f"  Borrowed UTF-8 validation vs String::from_utf8: "
          f"{floor['cptx_borrowed_utf8'] - floor['cptx_args_os']:+,} bytes")
    print("  Borrowed validation preserves rejection of invalid UTF-8, but error text may differ.")
    print("  WARNING: raw byte copy accepts invalid UTF-8 input; measurement only.")
    print("  Note: args_os handles invalid UTF-8 arguments differently from args().")
    print("  Interpret differences as linked feature costs, not individual function sizes.")
    print("  Fixtures are separately compiled and may have different optimization paths.")
    print("  No generated artifact was promoted to a production build.")


if __name__ == "__main__":
    main()
