#!/usr/bin/env python3
"""Measure how isolated Rust/WASI fixtures expand into wasm2jar JVM classes.

Read-only diagnostic: all fixtures and generated JARs live in a temporary
directory. These are conversion sizes, not runnable WASI applications.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from cptx_size_floor import FIXTURES, ROOT, TARGET, wasm_code_size


def run(argv: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(map(str, argv)), flush=True)
    subprocess.run(argv, cwd=cwd, check=True)


def target_dir() -> Path:
    result = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return Path(json.loads(result.stdout)["target_directory"])


def class_sizes(jar: Path) -> tuple[int, int, int, int]:
    with zipfile.ZipFile(jar) as archive:
        classes = [i for i in archive.infolist() if i.filename.endswith(".class")]
        translated = [i for i in classes if i.filename.startswith("console/tools/")]
        support = [i for i in classes if i.filename.startswith("org/wasm2jar/")]
        return (
            sum(i.compress_size for i in translated),
            sum(i.compress_size for i in support),
            sum(i.file_size for i in translated),
            len(classes),
        )


def main() -> None:
    rustc = shutil.which("rustc")
    converter = shutil.which("wasm2jar")
    optimizer = shutil.which("wasm-opt")
    if not rustc or not converter:
        raise RuntimeError("rustc and wasm2jar are required")
    baseline = target_dir() / TARGET / "release" / "cptx.wasm"
    if not baseline.is_file():
        raise FileNotFoundError(f"{baseline}; run just build-wasm")
    rows = []
    target_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wasm2jar-size-floor-", dir=target_dir()) as directory:
        tmp = Path(directory)
        for name, code in [*FIXTURES.items(), ("ACTUAL_cptx", None)]:
            wasm = tmp / f"{name}.wasm"
            if code is None:
                shutil.copyfile(baseline, wasm)
            else:
                source = tmp / f"{name}.rs"
                source.write_text(code, encoding="utf-8")
                run([rustc, "--edition=2024", "--target", TARGET, str(source),
                     "-o", str(wasm), "-C", "opt-level=z", "-C", "lto=fat",
                     "-C", "codegen-units=1", "-C", "panic=abort",
                     "-C", "strip=symbols"])
                if optimizer:
                    optimized = tmp / f"{name}.opt.wasm"
                    run([optimizer, "-Oz", "--enable-bulk-memory",
                         "--strip-debug", "--strip-producers",
                         str(wasm), "-o", str(optimized)])
                    if optimized.stat().st_size < wasm.stat().st_size:
                        wasm = optimized
            jar = tmp / f"{name}.jar"
            run([converter, "--output-class", "console/tools/Cptx",
                 "--jar", str(jar), str(wasm)], cwd=tmp)
            translated, support, raw, count = class_sizes(jar)
            rows.append((name, wasm.stat().st_size, wasm_code_size(wasm),
                         jar.stat().st_size, translated, support, raw, count))
    print("\nWASM -> JVM size floor (independent builds; compressed class sizes):")
    print(f"  {'Variant':<26} {'WASM':>8} {'Code':>8} {'JAR':>8} {'Translated':>11} {'Runtime':>9} {'Raw class':>11} {'Classes':>7}")
    for name, wasm, code, jar, translated, support, raw, count in rows:
        print(f"  {name:<26} {wasm:>8,} {code:>8,} {jar:>8,} "
              f"{translated:>11,} {support:>9,} {raw:>11,} {count:>7}")
    by_name = {row[0]: row for row in rows}
    print("\nFull cptx compared to empty Rust program:")
    for index, label in [(1, "WASM"), (3, "JAR"), (4, "translated classes"),
                         (5, "wasm2jar support classes")]:
        print(f"  {label}: {by_name['ACTUAL_cptx'][index] - by_name['empty'][index]:+,} bytes")
    print("  JAR sizes exclude the separate Java launcher/host.")
    print("  Fixture JARs are not executed; WASI imports require a host.")
    print("  No production artifacts were modified.")


if __name__ == "__main__":
    main()
