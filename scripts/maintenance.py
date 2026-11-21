#!/usr/bin/env python3
"""Miscellaneous build/maintenance actions invoked by Justfile."""
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def run(*args, check=True):
    return subprocess.run(args, cwd=ROOT, check=check).returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("clear", "cover-setup", "cover", "cover-lcov", "cover-text", "install", "clean", "clean-all", "targetlist"))
    action = parser.parse_args().action
    if action == "clear":
        run("tmux", "clear-history", check=False)
        run("clear")
    elif action == "cover-setup":
        run("cargo", "install", "cargo-llvm-cov")
        run("rustup", "component", "add", "llvm-tools-preview")
    elif action.startswith("cover"):
        command = ["cargo", "llvm-cov", "--all-features", "--workspace"]
        if action == "cover":
            command.append("--html")
        elif action == "cover-lcov":
            command += ["--lcov", "--output-path", str(ROOT / "target/coverage/lcov.info")]
        run(*command)
    elif action == "install":
        # Install the already verified pinned-Nightly binaries; cargo install would
        # silently rebuild them with the default (stable) toolchain.
        metadata = subprocess.check_output(["cargo", "metadata", "--no-deps", "--format-version", "1"], cwd=ROOT, text=True)
        target = Path(json.loads(metadata)["target_directory"])
        bindir = Path(os.environ.get("CARGO_INSTALL_ROOT", os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")))) / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        sources = {name: target / "release" / name for name in ("xcat", "cptx", "wasm-host")}
        missing = [str(source) for source in sources.values() if not source.is_file()]
        if missing:
            raise RuntimeError(f"Missing release binaries: {missing}; run just build-release first")
        for name, source in sources.items():
            shutil.copy2(source, bindir / name)
            (bindir / name).chmod(0o755)
            print(f"Installed {bindir / name} ({source.stat().st_size:,} bytes)")
    elif action == "clean":
        (ROOT / "Cargo.lock").unlink(missing_ok=True)
        run("cargo", "clean", "-p", ROOT.name)
    elif action == "clean-all":
        run("cargo", "clean")
    elif action == "targetlist":
        run("rustup", "target", "list")


if __name__ == "__main__":
    main()
