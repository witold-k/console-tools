#!/usr/bin/env python3
"""Optimize no_std xcat and cptx JARs with ProGuard and verify before publishing.

Keeps baseline artifacts intact. A failed test never promotes a candidate.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from jvm import proguard_executable, java_home
from wasm2jar_run import test_standalone
from wasi_no_std_jvm_test import test_desktop_failures, test_wasi_io_errors, test_partial_wasi_writes
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def target_dir():
    metadata = subprocess.check_output(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=ROOT, text=True)
    return Path(json.loads(metadata)["target_directory"])


def optimize(tool, baseline, output, keep_mode="minimal", deep_verify=False):
    if not baseline.is_file():
        raise FileNotFoundError(baseline)
    proguard = proguard_executable()
    jmods = sorted((java_home() / "jmods").glob("*.jmod"))
    if not jmods:
        raise RuntimeError("JDK jmods not found")
    cap = tool.capitalize()
    launcher = f"console.tools.{cap}Launcher"
    wasm = f"console.tools.{cap}"
    keep_generated = ("-keep class" if keep_mode == "conservative"
                      else "-keep,allowshrinking,allowoptimization class")
    launcher_rules = ([f"-keep class {launcher} {{ *; }}"] if keep_mode != "minimal" else [
        f"-keep class {launcher} {{",
        "    public static void main(java.lang.String[]);",
        "    public int args_sizes_get(int,int);",
        "    public int args_get(int,int);",
        "    public int environ_sizes_get(int,int);",
        "    public int environ_get(int,int);",
        "    public int fd_read(int,int,int,int);",
        "    public int fd_write(int,int,int,int);",
        "    public void proc_exit(int);",
        "    public int random_get(int,int);",
        "    public int fd_close(int);",
        "    public int fd_fdstat_get(int,int);",
        "    public int fd_filestat_get(int,int);",
        "    public int fd_prestat_get(int,int);",
        "    public int fd_prestat_dir_name(int,int,int);",
        "    public int fd_readdir(int,int,int,long,int);",
        "    public int path_create_directory(int,int,int);",
        "    public int path_filestat_get(int,int,int,int,int);",
        "    public int path_open(int,int,int,int,int,long,long,int,int);",
        "    public int path_readlink(int,int,int,int,int,int);",
        "    <init>(java.lang.String[]);",
        "    private int execute();",
        "}",
    ])
    rules = [
        f"-injars {baseline}",
        f"-outjars {output}",
        *(f"-libraryjars {jmod}(!**.jar;!module-info.class)" for jmod in jmods),
        "-dontnote",
        "-dontwarn java.lang.invoke.MethodHandle",
        "-dontwarn java.lang.IllegalArgumentException",
        "-keepattributes *Annotation*,Signature,InnerClasses,EnclosingMethod",
        "-optimizationpasses 5",
        "-allowaccessmodification",
        "-mergeinterfacesaggressively",
        # Reflectively discovered WASI methods and generated WASM exports
        # must retain their names and descriptors.
        *launcher_rules,
        *([f"-keep class {wasm} {{ public void _start(); }}"] if keep_mode != "conservative" else []),
        f"{keep_generated} {wasm} {{ *; }}",
        f"{keep_generated} {wasm}$* {{ *; }}",
        f"{keep_generated} org.wasm2jar.** {{ *; }}",
        # ProGuard can still shrink unreachable Java library classes.
    ]
    with tempfile.TemporaryDirectory(prefix=f"{tool}-proguard-") as tmp:
        config = Path(tmp) / "rules.pro"
        config.write_text("\n".join(rules) + "\n", encoding="utf-8")
        result = subprocess.run([proguard, f"@{config}"], cwd=ROOT,
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"{tool} ProGuard failed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
    test_standalone(output, tool)
    if deep_verify and tool == "cptx":
        test_desktop_failures(output)
        with tempfile.TemporaryDirectory(prefix="cptx-proguard-verify-") as tmp:
            stage = Path(tmp)
            with zipfile.ZipFile(output) as jar:
                jar.extractall(stage)
            test_wasi_io_errors(stage)
            test_partial_wasi_writes(stage)
    print(f"PASS: {tool} ProGuard: {baseline.stat().st_size:,} -> {output.stat().st_size:,} bytes")


def promote(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".optimized-", suffix=".jar",
                                     dir=dest.parent, delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        shutil.copyfile(src, temporary)
        os.replace(temporary, dest)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-mode", choices=("conservative", "relaxed", "minimal"), default="minimal",
                        help="ProGuard keep policy (default: verified minimal)")
    parser.add_argument("--deep-verify", action="store_true",
                        help="Run cptx fault and partial-write harnesses")
    parser.add_argument("--publish", action="store_true",
                        help="Publish only after BOTH xcat and cptx regression suites pass")
    args = parser.parse_args()
    if args.publish and args.keep_mode != "minimal":
        parser.error("Only verified minimal keep mode may publish default artifacts")
    if args.publish:
        args.deep_verify = True
    target = target_dir()
    candidates = {
        "xcat": target / "no-std-xcat" / "xcat-no-std-standalone.jar",
        "cptx": target / "wasm2jar-probe" / "cptx-no-std-standalone.jar",
    }
    optimized = {}
    for tool, baseline in candidates.items():
        output = baseline.with_name(f"{tool}-no-std-proguard-{args.keep_mode}.jar")
        output.unlink(missing_ok=True)
        optimize(tool, baseline, output, keep_mode=args.keep_mode, deep_verify=args.deep_verify)
        optimized[tool] = output
    if args.publish:
        # Both candidates were successfully built and independently tested.
        for tool, candidate in optimized.items():
            dest = target / "wasm2jar-probe" / f"{tool}-standalone.jar"
            promote(candidate, dest)
            print(f"Published verified {tool} ProGuard JAR: {dest}")
    else:
        print("No default artifacts changed. Use --publish after parity gates pass.")


if __name__ == "__main__":
    main()
