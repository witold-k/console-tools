#!/usr/bin/env python3
"""Measure WASM sections, JAR class sizes and safe Binaryen size experiments.

Read-only for production artifacts. Candidate WASM files are written under
Cargo's target/wasm-size-experiments and never replace release modules.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def target_dir() -> Path:
    proc = subprocess.run(["cargo", "metadata", "--no-deps", "--format-version", "1"],
                          cwd=ROOT, check=True, text=True, capture_output=True)
    return Path(json.loads(proc.stdout)["target_directory"])


def uleb(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 35, 7):
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, pos
    raise ValueError("Invalid LEB128")


def wasm_sections(path: Path) -> None:
    data = path.read_bytes()
    if data[:8] != bytes.fromhex("0061736d01000000"):
        raise ValueError(f"Not a WASM module: {path}")
    names = {1:"type",2:"import",3:"function",4:"table",5:"memory",6:"global",
             7:"export",8:"start",9:"element",10:"code",11:"data",12:"data_count"}
    sections = []
    pos = 8
    while pos < len(data):
        start = pos
        kind = data[pos]
        pos += 1
        length, pos = uleb(data, pos)
        end = pos + length
        if end > len(data):
            raise ValueError(f"Truncated section in {path}")
        label = names.get(kind, f"section-{kind}")
        if kind == 0:
            size, at = uleb(data, pos)
            label = "custom:" + data[at:at+size].decode("utf-8", errors="replace")
        sections.append((label, end-start))
        pos = end
    print(f"  WASM {path.name}: {len(data)} bytes")
    for label, size in sorted(sections, key=lambda row: -row[1]):
        print(f"    {label:<24} {size:>9} B {size / len(data):>6.1%}")


def jar_entries(path: Path) -> None:
    if not path.is_file():
        return
    with zipfile.ZipFile(path) as archive:
        entries = [(item.filename, item.file_size, item.compress_size)
                   for item in archive.infolist() if not item.is_dir()]
    print(f"  JAR {path.name}: {path.stat().st_size} bytes; "
          f"{sum(row[1] for row in entries)} bytes uncompressed")
    for name, raw, compressed in sorted(entries, key=lambda row: -row[2]):
        print(f"    {name:<48} {raw:>9} B raw  {compressed:>9} B compressed")


def experiment(path: Path, target: Path) -> None:
    optimizer = shutil.which("wasm-opt")
    if optimizer is None:
        print("  wasm-opt unavailable; skipping experiments")
        return
    destination = target / "wasm-size-experiments"
    destination.mkdir(parents=True, exist_ok=True)
    variants = {
        "Oz": ["-Oz"],
        "Os": ["-Os"],
        "O3": ["-O3"],
        "Oz-converge": ["-Oz", "--converge"],
    }
    results = []
    for name, flags in variants.items():
        output = destination / f"{path.stem}-{name}.wasm"
        command = [optimizer, *flags, "--enable-bulk-memory",
                   "--strip-debug", "--strip-producers", str(path), "-o", str(output)]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if result.returncode:
            print(f"  {name}: failed: {result.stderr.strip()[:250]}")
            continue
        size = output.stat().st_size
        results.append((name, size))
        print(f"  {name:<13} {size:>9} B ({size-path.stat().st_size:+d} vs current)")
    if results:
        best = min(results, key=lambda row: row[1])
        print(f"  Smallest candidate: {best[0]} ({best[1]} B)")
        print("  Candidates are NOT automatically promoted: JVM end-to-end tests required.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", action="store_true",
                        help="Compare Binaryen settings without modifying release WASM")
    args = parser.parse_args()
    target = target_dir()
    for tool in ("xcat", "cptx"):
        print(f"\n=== {tool} ===")
        wasm = target / "wasm32-wasip1" / "release" / f"{tool}.wasm"
        if not wasm.is_file():
            raise FileNotFoundError(f"{wasm}; run just build-wasm first")
        wasm_sections(wasm)
        for suffix in ("standalone",):
            jar_entries(target / "wasm2jar-probe" / f"{tool}-{suffix}.jar")
        if args.experiment:
            experiment(wasm, target)


if __name__ == "__main__":
    main()
