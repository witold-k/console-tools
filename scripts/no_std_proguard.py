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

ROOT = Path(__file__).resolve().parents[1]


def target_dir():
    metadata = subprocess.check_output(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=ROOT, text=True)
    return Path(json.loads(metadata)["target_directory"])


def optimize(tool, baseline, output):
    if not baseline.is_file():
        raise FileNotFoundError(baseline)
    proguard = proguard_executable()
    jmods = sorted((java_home() / "jmods").glob("*.jmod"))
    if not jmods:
        raise RuntimeError("JDK jmods not found")
    cap = tool.capitalize()
    launcher = f"console.tools.{cap}Launcher"
    wasm = f"console.tools.{cap}"
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
        f"-keep class {launcher} {{ *; }}",
        f"-keep class {wasm} {{ *; }}",
        f"-keep class {wasm}$* {{ *; }}",
        "-keep class org.wasm2jar.** { *; }",
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
    parser.add_argument("--publish", action="store_true",
                        help="Publish only after BOTH xcat and cptx regression suites pass")
    args = parser.parse_args()
    target = target_dir()
    candidates = {
        "xcat": target / "no-std-xcat" / "xcat-no-std-standalone.jar",
        "cptx": target / "wasm2jar-probe" / "cptx-no-std-standalone.jar",
    }
    optimized = {}
    for tool, baseline in candidates.items():
        output = baseline.with_name(f"{tool}-no-std-proguard.jar")
        output.unlink(missing_ok=True)
        optimize(tool, baseline, output)
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
