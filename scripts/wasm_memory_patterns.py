#!/usr/bin/env python3
"""Read-only analysis of repeated wasm2jar memory-access bytecode sequences."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess

OPCODE = re.compile(r"^\s+(\d+):\s+([a-z][a-z0-9_]*)\b(.*)$")
METHOD = re.compile(r"^  (?!static \{|Code:).+\);\s*$")


def target_dir() -> Path:
    result = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        check=True, capture_output=True, text=True,
    )
    return Path(json.loads(result.stdout)["target_directory"])


def analyze(jar: Path, klass: str) -> None:
    result = subprocess.run(
        ["javap", "-c", "-p", "-classpath", str(jar), klass],
        check=True, capture_output=True, text=True,
    )
    methods = []
    current_name = None
    current = []

    def finish() -> None:
        if current_name is not None and current:
            methods.append((current_name, list(current)))

    for line in result.stdout.splitlines():
        if METHOD.match(line):
            finish()
            current_name = line.strip()
            current = []
            continue
        match = OPCODE.match(line)
        if match and current_name is not None:
            current.append((match.group(2), match.group(3).strip()))
    finish()

    patterns = {
        "field + swap + ByteBuffer.get": lambda ops, i: (
            i + 2 < len(ops) and ops[i][0] == "getfield"
            and ops[i + 1][0] == "swap"
            and ops[i + 2][0] in ("invokevirtual", "invokeinterface")
            and "ByteBuffer.get" in ops[i + 2][1]
        ),
        "ByteBuffer.put + pop": lambda ops, i: (
            i + 1 < len(ops)
            and ops[i][0] in ("invokevirtual", "invokeinterface")
            and "ByteBuffer.put" in ops[i][1]
            and ops[i + 1][0] == "pop"
        ),
        "constant + iadd": lambda ops, i: (
            i + 1 < len(ops)
            and (ops[i][0].startswith("iconst_")
                 or ops[i][0] in ("bipush", "sipush", "ldc", "ldc_w"))
            and ops[i + 1][0] == "iadd"
        ),
    }
    totals = Counter()
    by_method = []
    for name, ops in methods:
        counts = Counter({
            label: sum(bool(test(ops, i)) for i in range(len(ops)))
            for label, test in patterns.items()
        })
        totals.update(counts)
        by_method.append((sum(counts.values()), name, counts))
    print(f"\n{klass} ({jar.name}): {len(methods)} methods")
    for label, count in totals.items():
        print(f"  {label}: {count}")
    print("  Methods with most recognized memory-access patterns:")
    for count, name, detail in sorted(by_method, reverse=True)[:12]:
        if count:
            print(f"    {count:>5}  {name[:100]}")
            print("           " + ", ".join(f"{k}={v}" for k, v in detail.items() if v))
    print("  Counts identify translation patterns, not proven redundant instructions.")


def main() -> None:
    root = target_dir() / "wasm2jar-probe"
    for tool in ("xcat", "cptx"):
        jar = root / f"{tool}-standalone.jar"
        if not jar.is_file():
            raise FileNotFoundError(f"{jar}; run just wasm2jar-test-all")
        analyze(jar, f"console.tools.{tool.capitalize()}$Part0")


if __name__ == "__main__":
    main()
