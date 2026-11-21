#!/usr/bin/env python3
"""Isolated nightly WASI immediate-abort -> wasm2jar comparison.

Never writes to the normal Cargo target directory or production JAR paths.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGET = "wasm32-wasip1"
TOOLCHAIN = "nightly-2026-11-21"
EXPECTED_RUSTC_COMMIT = "c7d5ba59d8e11ee2e2204b173458eec4cb41c973"

def run(args, env=None):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panic", choices=("abort", "immediate-abort"),
                        default="immediate-abort")
    args = parser.parse_args()
    panic = args.panic
    metadata = subprocess.run(["cargo", "metadata", "--no-deps", "--format-version", "1"],
                              cwd=ROOT, capture_output=True, text=True, check=True)
    normal = Path(json.loads(metadata.stdout)["target_directory"])
    isolated = normal / f"wasm-nightly-{panic}"
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = str(isolated)
    # Profile overrides apply to WASI only, not to the host build scripts.
    env.update(CARGO_PROFILE_RELEASE_OPT_LEVEL="z",
               CARGO_PROFILE_RELEASE_LTO="true",
               CARGO_PROFILE_RELEASE_CODEGEN_UNITS="1",
               CARGO_PROFILE_RELEASE_STRIP="symbols")
    # build-std rebuilds Rust libraries, but still needs the target's WASI CRT/libc.
    # The stable target installation does not satisfy the separate nightly sysroot.
    version = subprocess.run(["rustc", f"+{TOOLCHAIN}", "-vV"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
    if f"commit-hash: {EXPECTED_RUSTC_COMMIT}" not in version.splitlines():
        raise RuntimeError(f"Unexpected rustc for {TOOLCHAIN}:\\n{version}")
    sysroot = subprocess.run(["rustc", f"+{TOOLCHAIN}", "--print", "sysroot"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    self_contained = Path(sysroot) / "lib" / "rustlib" / TARGET / "lib" / "self-contained"
    rust_src = Path(sysroot) / "lib" / "rustlib" / "src" / "rust" / "library" / "Cargo.toml"
    if not rust_src.is_file():
        raise RuntimeError(f"Missing rust-src for {TOOLCHAIN}. Install it separately with "
                           f"rustup component add rust-src --toolchain {TOOLCHAIN}")
    required = ("crt1-command.o", "libc.a")
    missing = [name for name in required if not (self_contained / name).is_file()]
    if missing:
        raise RuntimeError(f"Nightly WASI sysroot missing {missing} in {self_contained}. "
                           f"Install separately: rustup target add {TARGET} --toolchain {TOOLCHAIN}")
    flags = ["-Z", "panic-immediate-abort"] if panic == "immediate-abort" else []
    run(["cargo", f"+{TOOLCHAIN}", *flags, "-Z", "build-std=std,panic_abort",
         "--config", f'profile.release.panic="{panic}"',
         "build", "--release", "--target", TARGET,
         "-p", "console-tools", "--bin", "xcat", "--bin", "cptx"], env)
    wasm_dir = isolated / TARGET / "release"
    optimizer = shutil.which("wasm-opt")
    for name in ("xcat", "cptx"):
        wasm = wasm_dir / f"{name}.wasm"
        if optimizer:
            optimized = wasm.with_suffix(".optimized.wasm")
            try:
                run([optimizer, "-Oz", "--enable-bulk-memory",
                     "--strip-debug", "--strip-producers",
                     str(wasm), "-o", str(optimized)])
                if optimized.stat().st_size < wasm.stat().st_size:
                    optimized.replace(wasm)
            finally:
                optimized.unlink(missing_ok=True)
        print(f"{name} WASM {panic}: {wasm.stat().st_size:,} bytes")
    jar_dir = isolated / "wasm2jar-probe"
    jar_dir.mkdir(parents=True, exist_ok=True)
    converter = shutil.which("wasm2jar")
    if not converter:
        raise RuntimeError("wasm2jar not found in PATH")
    for name in ("cptx", "xcat"):
        translated = jar_dir / f"{name}.jar"
        run([converter, "--output-class", f"console/tools/{name.capitalize()}",
             "--jar", str(translated), str(wasm_dir / f"{name}.wasm")])
        run([sys.executable, "scripts/wasm2jar_run.py", "--tool", name,
             "--input-jar", str(translated),
             "--output-jar", str(jar_dir / f"{name}-standalone.jar")])
    print(f"\nIsolated nightly {panic} results:")
    control = normal / ("wasm-nightly-abort" if panic == "immediate-abort" else "wasm-nightly-immediate-abort")
    for name in ("xcat", "cptx"):
        for kind, path, baseline in (
            ("WASM", wasm_dir / f"{name}.wasm", normal / TARGET / "release" / f"{name}.wasm"),
            ("JAR", jar_dir / f"{name}-standalone.jar", normal / "wasm2jar-probe" / f"{name}-standalone.jar"),
        ):
            size = path.stat().st_size
            counterpart = (control / TARGET / "release" / path.name if kind == "WASM"
                           else control / "wasm2jar-probe" / path.name)
            if counterpart.is_file():
                other = counterpart.stat().st_size
                print(f"{name} {kind}: {size:,} B vs other nightly mode {other:,} B "
                      f"({size - other:+,} B, {(size / other - 1) * 100:+.1f}%)")
            if baseline.is_file():
                previous = baseline.stat().st_size
                print(f"  previously published artifact: {previous:,} B "
                      f"({size - previous:+,} B, {(size / previous - 1) * 100:+.1f}%)")
    print("\nTool versions:")
    for command in (["rustc", f"+{TOOLCHAIN}", "--version", "--verbose"],
                    ["wasm-opt", "--version"], ["java", "-version"],
                    ["javac", "-version"]):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        print(f"  {' '.join(command)}: {(result.stdout or result.stderr).strip()}")
    print(f"  wasm2jar executable: {converter}")
    print("Published WASM and JAR outputs unchanged by this isolated run.")

if __name__ == "__main__":
    main()
