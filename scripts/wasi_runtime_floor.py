#!/usr/bin/env python3
"""Isolated rustc/WASI runtime-size experiments; no production changes.

Compile two fixed fixtures under alternative codegen settings, run wasm-opt,
and optionally translate each result with wasm2jar. Report sizes, not speed or
semantic equivalence. All outputs are temporary.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from cptx_size_floor import FIXTURES, ROOT, TARGET, wasm_code_size

SETTINGS = {
    "baseline_z_fat": ("z", "fat", "1"),
    "size_s_fat": ("s", "fat", "1"),
    "z_thin": ("z", "thin", "1"),
    "z_no_lto": ("z", "off", "1"),
    "z_no_lto_16cgus": ("z", "off", "16"),
}
SOURCES = ("empty", "cptx_args_os")


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def translated_size(jar: Path) -> tuple[int, int]:
    with zipfile.ZipFile(jar) as archive:
        parts = [entry for entry in archive.infolist()
                 if entry.filename.startswith("console/tools/") and
                 entry.filename.endswith(".class")]
        return jar.stat().st_size, sum(entry.compress_size for entry in parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-jvm", action="store_true",
                        help="measure only WASM, without invoking wasm2jar")
    args = parser.parse_args()
    rustc = shutil.which("rustc")
    optimizer = shutil.which("wasm-opt")
    converter = shutil.which("wasm2jar") if not args.no_jvm else None
    if not rustc or not optimizer or (not args.no_jvm and not converter):
        parser.error("requires rustc and wasm-opt, plus wasm2jar unless --no-jvm")
    results = []
    with tempfile.TemporaryDirectory(prefix="wasi-runtime-floor-") as directory:
        temp = Path(directory)
        for source_name in SOURCES:
            source = temp / f"{source_name}.rs"
            source.write_text(FIXTURES[source_name], encoding="utf-8")
            for name, (opt, lto, units) in SETTINGS.items():
                wasm = temp / f"{source_name}-{name}.wasm"
                command = [rustc, "--edition=2024", "--target", TARGET,
                           str(source), "-o", str(wasm),
                           "-C", f"opt-level={opt}", "-C", f"lto={lto}",
                           "-C", f"codegen-units={units}", "-C", "panic=abort",
                           "-C", "strip=symbols"]
                run(command)
                optimized = wasm.with_suffix(".opt.wasm")
                run([optimizer, "-Oz", "--enable-bulk-memory", "--strip-debug",
                     "--strip-producers", str(wasm), "-o", str(optimized)])
                chosen = optimized if optimized.stat().st_size < wasm.stat().st_size else wasm
                jar_size = class_size = None
                if converter:
                    jar = temp / f"{source_name}-{name}.jar"
                    run([converter, "--output-class", "console/tools/Cptx",
                         "--jar", str(jar), str(chosen)])
                    jar_size, class_size = translated_size(jar)
                results.append((source_name, name, chosen.stat().st_size,
                                wasm_code_size(chosen), jar_size, class_size))
    print("\nWASI runtime / compiler settings size experiment")
    print(f"  {'Fixture':<16} {'Settings':<19} {'WASM':>9} {'Code':>9} {'JAR':>9} {'Classes':>9}")
    for source, setting, wasm, code, jar, classes in results:
        def fmt(value: int | None) -> str:
            return f"{value:,}" if value is not None else "-"
        print(f"  {source:<16} {setting:<19} {fmt(wasm):>9} {fmt(code):>9} "
              f"{fmt(jar):>9} {fmt(classes):>9}")
    print("\nEach fixture is compiled independently; differences are not additive.")
    print("No production files, release binaries, or JARs were modified.")
    print("Size alone does not establish runtime correctness or performance.")


if __name__ == "__main__":
    main()
