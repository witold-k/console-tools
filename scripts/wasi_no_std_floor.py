#!/usr/bin/env python3
"""Measure a minimal no_std WASI entrypoint against the Rust std size floor.

These are isolated ABI experiments, NOT replacements for cptx. They omit
argument handling, allocation, UTF-8 validation and ordinary error reporting.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from cptx_size_floor import FIXTURES, ROOT, TARGET, wasm_code_size

NO_STD = {
    "no_std_start": r"""
#![no_std]
#![no_main]
use core::panic::PanicInfo;
#[panic_handler] fn panic(_: &PanicInfo) -> ! { loop {} }
#[unsafe(no_mangle)] pub extern "C" fn _start() {}
""",
    "no_std_stream": r"""
#![no_std]
#![no_main]
use core::panic::PanicInfo;
#[panic_handler] fn panic(_: &PanicInfo) -> ! { loop {} }
#[repr(C)] struct Iovec { buf: *mut u8, len: usize }
#[repr(C)] struct Ciovec { buf: *const u8, len: usize }
#[link(wasm_import_module = "wasi_snapshot_preview1")]
unsafe extern "C" {
    fn fd_read(fd: i32, iovs: *const Iovec, count: i32, nread: *mut i32) -> i32;
    fn fd_write(fd: i32, iovs: *const Ciovec, count: i32, nwritten: *mut i32) -> i32;
    fn proc_exit(code: i32) -> !;
}
#[unsafe(no_mangle)]
pub extern "C" fn _start() {
    let mut buf = [0u8; 4096];
    loop {
        let input = Iovec { buf: buf.as_mut_ptr(), len: buf.len() };
        let mut read = 0i32;
        if unsafe { fd_read(0, &input, 1, &mut read) } != 0 {
            unsafe { proc_exit(1) }
        }
        if read == 0 { return; }
        let mut offset = 0usize;
        while offset < read as usize {
            let output = Ciovec { buf: unsafe { buf.as_ptr().add(offset) },
                                  len: read as usize - offset };
            let mut written = 0i32;
            if unsafe { fd_write(1, &output, 1, &mut written) } != 0 || written <= 0 {
                unsafe { proc_exit(1) }
            }
            offset += written as usize;
        }
    }
}
""",
    "no_std_fd_write": r"""
#![no_std]
#![no_main]
use core::panic::PanicInfo;
#[panic_handler] fn panic(_: &PanicInfo) -> ! { loop {} }
#[repr(C)] struct Ciovec { buf: *const u8, len: usize }
#[link(wasm_import_module = "wasi_snapshot_preview1")]
unsafe extern "C" {
    fn fd_write(fd: i32, iovs: *const Ciovec, count: i32, nwritten: *mut i32) -> i32;
}
#[unsafe(no_mangle)]
pub extern "C" fn _start() {
    let message = b"hello from no_std WASI\n";
    let vec = Ciovec { buf: message.as_ptr(), len: message.len() };
    let mut written = 0i32;
    unsafe { let _ = fd_write(1, &vec, 1, &mut written); }
}
""",
}
STD = {"std_empty": FIXTURES["empty"], "std_stdout": FIXTURES["stdin_stdout_bytes"]}


def run(argv: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, cwd=cwd, check=True)


def target_dir() -> Path:
    result = subprocess.run(["cargo", "metadata", "--no-deps", "--format-version", "1"],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    return Path(json.loads(result.stdout)["target_directory"])


def jar_classes(path: Path) -> tuple[int, int]:
    with zipfile.ZipFile(path) as archive:
        classes = [x for x in archive.infolist() if x.filename.endswith(".class")]
        return sum(x.compress_size for x in classes), len(classes)


def main() -> None:
    rustc, optimizer, converter = (shutil.which(x) for x in ("rustc", "wasm-opt", "wasm2jar"))
    if not all((rustc, optimizer, converter)):
        raise RuntimeError("rustc, wasm-opt and wasm2jar are required")
    rows = []
    target_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wasi-no-std-floor-", dir=target_dir()) as directory:
        tmp = Path(directory)
        for name, source_text in {**STD, **NO_STD, "no_std_cptx": ""}.items():
            source = ROOT / "experiments/no_std_cptx.rs" if name == "no_std_cptx" else tmp / f"{name}.rs"
            if name != "no_std_cptx":
                source.write_text(source_text, encoding="utf-8")
            wasm = tmp / f"{name}.wasm"
            command = [rustc, "--edition=2024", "--target", TARGET,
                       str(source), "-o", str(wasm),
                       "-C", "opt-level=z", "-C", "lto=fat",
                       "-C", "codegen-units=1", "-C", "panic=abort",
                       "-C", "strip=symbols"]
            if name.startswith("no_std"):
                command.extend(["--crate-type=cdylib", "-C", "link-arg=--export=_start"])
            run(command)
            optimized = tmp / f"{name}.opt.wasm"
            run([optimizer, "-Oz", "--enable-bulk-memory", "--strip-debug",
                 "--strip-producers", str(wasm), "-o", str(optimized)])
            chosen = optimized if optimized.stat().st_size < wasm.stat().st_size else wasm
            jar = tmp / f"{name}.jar"
            run([converter, "--output-class", "console/tools/Cptx",
                 "--jar", str(jar), str(chosen)], cwd=tmp)
            classes, count = jar_classes(jar)
            rows.append((name, chosen.stat().st_size, wasm_code_size(chosen),
                         jar.stat().st_size, classes, count))
    print("\nRust std vs no_std WASI/JVM size floor")
    print(f"  {'Variant':<20} {'WASM':>10} {'Code':>10} {'JAR':>10} {'Classes ZIP':>13} {'Count':>7}")
    for name, wasm, code, jar, classes, count in rows:
        print(f"  {name:<20} {wasm:>10,} {code:>10,} {jar:>10,} {classes:>13,} {count:>7}")
    print("\nNo_std fixtures omit Rust std initialization, heap allocation, CLI parsing,")
    print("UTF-8 validation, and normal error propagation; they are not equivalent.")
    print("The minimal fd_write fixture uses a direct WASI Preview 1 import.")
    print("JAR conversion alone does not demonstrate JVM/WASI execution.")
    print("No production files or build artifacts were modified.")


if __name__ == "__main__":
    main()
