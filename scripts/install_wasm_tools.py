#!/usr/bin/env python3
"""Install tools required by the WASI-to-JVM release pipeline (Debian/Ubuntu)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def run(*command: str) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    if not shutil.which("apt-get"):
        print("Automatic setup currently supports Debian/Ubuntu (apt-get) only.", file=sys.stderr)
        return 1

    packages = []
    if not shutil.which("wasm-opt"):
        packages.append("binaryen")
    if not all(shutil.which(tool) for tool in ("java", "javac", "jar", "javap")):
        packages.append("default-jdk")
    if packages:
        prefix = [] if os.geteuid() == 0 else ["sudo"]
        run(*prefix, "apt-get", "update")
        run(*prefix, "apt-get", "install", "-y", *packages)
    else:
        print("Binaryen and JDK already available.", flush=True)

    if not shutil.which("rustup"):
        raise RuntimeError("rustup is required; install Rust via https://rustup.rs/")
    run("rustup", "target", "add", "wasm32-wasip1")

    if not shutil.which("wasm2jar"):
        if not shutil.which("cargo"):
            raise RuntimeError("cargo is required to install wasm2jar")
        run("cargo", "install", "--git", "https://github.com/harpocrates/wasm2jar",
            "--bin", "wasm2jar", "--locked", "wasm2jar-bin")

    missing = [tool for tool in ("wasm-opt", "java", "javac", "jar", "javap", "wasm2jar")
               if not shutil.which(tool)]
    if missing:
        raise RuntimeError("Tools not on PATH: " + ", ".join(missing))
    print("WASI/JVM build prerequisites are available.", flush=True)
    print("ProGuard is provisioned by scripts/jvm.py on first use.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        sys.exit(1)
