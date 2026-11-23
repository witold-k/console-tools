#!/usr/bin/env python3
"""Build the aggressive ProGuard cptx JVM JAR twice; report reproducibility.

Uses independent temporary output paths. Never replaces the standard JAR.
"""
from __future__ import annotations
import hashlib
import difflib
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile

from cptx_size_floor import target_dir
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entries(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as jar:
        return {name: jar.read(name) for name in jar.namelist()}


def main() -> None:
    target_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cptx-jvm-repro-", dir=target_dir()) as directory:
        jars = [Path(directory) / f"build-{i}.jar" for i in (1, 2)]
        for jar in jars:
            subprocess.run([sys.executable, "scripts/wasi_no_std_jvm_test.py",
                            "no_std_cptx", "--output-jar", str(jar)],
                           cwd=ROOT, check=True)
        outputs = []
        for i, baseline in enumerate(jars, 1):
            outdir = Path(directory) / f"proguard-{i}"
            subprocess.run([sys.executable, "scripts/cptx_proguard_experiment.py",
                            "--baseline", str(baseline), "--output-dir", str(outdir),
                            "--aggressive-only"], cwd=ROOT, check=True)
            candidate = outdir / "cptx-proguard-aggressive.jar"
            if not candidate.is_file():
                raise SystemExit(f"FAIL missing aggressive candidate for build {i}")
            outputs.append(candidate)
        for baseline in jars:
            print(f"Intermediate {baseline.name}: {baseline.stat().st_size:,} bytes "
                  f"SHA256 {digest(baseline)}", flush=True)
        for i, candidate in enumerate(outputs, 1):
            print(f"Aggressive build-{i}: {candidate.stat().st_size:,} bytes "
                  f"SHA256 {digest(candidate)}", flush=True)
        if digest(outputs[0]) == digest(outputs[1]):
            print("PASS byte-for-byte reproducible aggressive ProGuard JAR")
            if digest(jars[0]) != digest(jars[1]):
                print("NOTE wasm2jar intermediates differ, final JARs match")
            return
        first, second = entries(outputs[0]), entries(outputs[1])
        changed = sorted(name for name in first.keys() | second.keys()
                         if first.get(name) != second.get(name))
        if changed:
            print("JAR entry content differs:", *changed, sep="\n  ")
            javap = shutil.which("javap")
            if javap:
                for entry in changed:
                    if not entry.endswith(".class"):
                        continue
                    cls = entry[:-6].replace("/", ".")
                    disassembly = []
                    for jar in outputs:
                        result = subprocess.run(
                            [javap, "-c", "-p", "-v", "-classpath", str(jar), cls],
                            cwd=ROOT, capture_output=True, text=True, check=True)
                        disassembly.append(result.stdout.splitlines(keepends=True))
                    diff = list(difflib.unified_diff(
                        disassembly[0], disassembly[1],
                        fromfile=f"build-1/{cls}", tofile=f"build-2/{cls}"))
                    print(f"\\nBytecode difference for {cls}:")
                    print("".join(diff[:180]) if diff else
                          "Class bytes differ, but javap output matches.")
                    if len(diff) > 180:
                        print(f"... {len(diff) - 180} additional diff lines")
        else:
            print("JAR entries match; archive metadata/order/compression differs.")
        raise SystemExit("FAIL aggressive ProGuard JAR is not byte-for-byte reproducible")


if __name__ == "__main__":
    main()
