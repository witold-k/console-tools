#!/usr/bin/env python3
"""Publish tested pinned-Nightly WASI and JVM artifacts to standard output paths."""
import json
import os
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
metadata = subprocess.check_output(
    ["cargo", "metadata", "--no-deps", "--format-version", "1"],
    cwd=root, text=True)
target = Path(json.loads(metadata)["target_directory"])
nightly = target / "wasm-nightly-immediate-abort"
if not nightly.is_dir():
    raise SystemExit("Missing Nightly outputs; run just wasm-nightly-immediate-abort")

for name in ("xcat", "cptx"):
    for source, destination in (
        (nightly / "wasm32-wasip1" / "release" / f"{name}.wasm",
         target / "wasm32-wasip1" / "release" / f"{name}.wasm"),
        (nightly / "wasm2jar-probe" / f"{name}.jar",
         target / "wasm2jar-probe" / f"{name}.jar"),
        (nightly / "wasm2jar-probe" / f"{name}-standalone.jar",
         target / "wasm2jar-probe" / f"{name}-standalone.jar"),
    ):
        if not source.is_file():
            raise SystemExit(f"Missing Nightly artifact: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".nightly-new")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        print(f"Published {destination}: {destination.stat().st_size:,} bytes")
