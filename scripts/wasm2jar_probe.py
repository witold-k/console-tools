#!/usr/bin/env python3
"""Probe the installed wasm2jar compiler without assuming its CLI or WASI support.

This is intentionally diagnostic: conversion is not equivalent to runnable WASI.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(argv, timeout=45):
    print("+", " ".join(map(str, argv)), flush=True)
    try:
        result = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}")
        return None
    print(result.stdout[:16000])
    print(f"exit status: {result.returncode}")
    return result


def locate(name):
    value = shutil.which(name)
    if value is None:
        print(f"ERROR: {name} not found in PATH")
    else:
        print(f"{name}: {value}")
    return value


def cargo_target_dir():
    metadata = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return Path(json.loads(metadata.stdout)["target_directory"])


def wasm_file(name):
    override = os.environ.get("CONSOLE_TOOLS_WASM_DIR")
    if override:
        return Path(override).expanduser().resolve() / f"{name}.wasm"
    return cargo_target_dir() / "wasm32-wasip1" / "release" / f"{name}.wasm"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["probe", "try-convert"])
    parser.add_argument("--tool", choices=["cptx", "xcat"], default="cptx")
    parser.add_argument("--output-dir", type=Path, default=None)
    args, extra = parser.parse_known_args()
    if extra and extra[0] == "--":
        extra = extra[1:]

    compiler = os.environ.get("WASM2JAR") or locate("wasm2jar")
    if os.environ.get("WASM2JAR"):
        print(f"wasm2jar override: {compiler}")
    locate("wast2jar")
    locate("java")
    locate("javap")
    if not compiler:
        return 1
    for option in ("--help", "-h", "--version"):
        run([compiler, option])
    module = wasm_file(args.tool)
    print(f"WASM module: {module}")
    if not module.is_file():
        print("ERROR: missing WASM module; run just build-wasm")
        return 1
    print(f"WASM size: {module.stat().st_size} bytes")
    print("WASI Preview 1 imports must be provided by the JVM host.")
    if args.command == "probe":
        print("Probe only; no assumption about wasm2jar argument syntax or output format.")
        return 0
    if not extra:
        print("ERROR: supply the compiler's verified arguments after --;")
        print("use {wasm} for input and {out} for output.")
        return 2
    output_dir = args.output_dir or (cargo_target_dir() / "wasm2jar-probe")
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{args.tool}.jar"
    argv = [compiler] + [v.replace("{wasm}", str(module)).replace("{out}", str(out))
                         for v in extra]
    result = run(argv, timeout=120)
    if result is None or result.returncode:
        return 1
    if out.is_file():
        print(f"Generated artifact: {out} ({out.stat().st_size} bytes)")
        print("NOTE: JAR existence does not establish WASI linkage or successful execution.")
        jar_tool = shutil.which("jar")
        if jar_tool:
            run([jar_tool, "tf", str(out)])
        if shutil.which("javap"):
            class_name = "console.tools.Cptx" if args.tool == "cptx" else "console.tools.Xcat"
            run(["javap", "-classpath", str(out), "-public", class_name])
            for helper in ("org.wasm2jar.Function", "org.wasm2jar.Memory",
                           "org.wasm2jar.Global", "org.wasm2jar.FunctionTable"):
                run(["javap", "-classpath", str(out), "-public", helper])
            # Avoid printing huge embedded Rust data strings from get_data*.
            command = ["javap", "-classpath", str(out), "-c", "-p", class_name]
            print("+", " ".join(command), "(constructor excerpt)", flush=True)
            detail = subprocess.run(command, capture_output=True, text=True, check=False)
            if detail.returncode:
                print(detail.stderr[:4000])
                return detail.returncode
            lines = detail.stdout.splitlines()
            signature = f"public {class_name}("
            start = next((i for i, line in enumerate(lines)
                          if line.strip().startswith(signature)), None)
            if start is None:
                print("ERROR: generated constructor not found in javap output")
                return 2
            end = next((i for i in range(start + 1, len(lines))
                        if lines[i].startswith("  public ") or lines[i] == "}"),
                       len(lines))
            constructor = lines[start:end]
            import re
            found = []
            pattern = r"Invalid import type for function import (\S+) \(expected FunctionType \{ inputs: \[([^]]*)\], outputs: \[([^]]*)\] \}\)"
            for line in constructor:
                match = re.search(pattern, line)
                if match:
                    found.append(match.groups())
            print("Required function imports and WASM types:")
            for name, inputs, outputs in found:
                print(f"  {name}: ({inputs}) -> ({outputs})")
            print(f"Found {len(found)} import signatures")
            print("Constructor excerpt:")
            print("\n".join(constructor[:100]))
            if len(constructor) > 100:
                print(f"... {len(constructor) - 100} constructor lines omitted")
            print("Import binding: inspect get/MethodHandle references above.")
        print("Execution not attempted: inspect imports and entrypoint first.")
        return 0
    print("Compiler succeeded, but no JAR found at the expected output path.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
