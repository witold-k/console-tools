#!/usr/bin/env python3
"""Miscellaneous build/maintenance actions invoked by Justfile."""
import argparse
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
        run("cargo", "build", "--release")
        run("cargo", "clippy", "--release")
        run("cargo", "install", "--path", ".")
    elif action == "clean":
        (ROOT / "Cargo.lock").unlink(missing_ok=True)
        run("cargo", "clean", "-p", ROOT.name)
    elif action == "clean-all":
        run("cargo", "clean")
    elif action == "targetlist":
        run("rustup", "target", "list")


if __name__ == "__main__":
    main()
