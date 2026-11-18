#!/usr/bin/env python3
"""Read-only javap statistics for generated wasm2jar classes.

Measures bytecode instruction frequencies, methods, and repeated operations.
Requires JDK javap and previously built standalone JARs.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess


def target_dir() -> Path:
    result = subprocess.run(["cargo", "metadata", "--no-deps", "--format-version", "1"],
                            check=True, capture_output=True, text=True)
    return Path(json.loads(result.stdout)["target_directory"])


def analyze(jar: Path, class_name: str) -> None:
    result = subprocess.run(["javap", "-c", "-p", "-classpath", str(jar), class_name],
                            check=True, capture_output=True, text=True)
    instructions = Counter()
    method_sizes = []
    method = None
    first = last = None
    for line in result.stdout.splitlines():
        if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(");"):
            if method is not None and first is not None:
                method_sizes.append((last - first + 1, method))
            method = line.strip()
            first = last = None
        match = re.match(r"^\s+(\d+):\s+([a-z][a-z0-9_]*)\b", line)
        if match:
            offset = int(match.group(1))
            instructions[match.group(2)] += 1
            if first is None:
                first = offset
            last = offset
    if method is not None and first is not None:
        method_sizes.append((last - first + 1, method))
    print(f"\n{class_name} ({jar.name})")
    print(f"  Instructions: {sum(instructions.values())}; methods with code: {len(method_sizes)}")
    print("  Most frequent JVM opcodes:")
    for opcode, count in instructions.most_common(20):
        print(f"    {opcode:<22} {count:>8}")
    print("  Largest method bytecode spans (approximate):")
    for size, name in sorted(method_sizes, reverse=True)[:12]:
        print(f"    {size:>8} B  {name[:110]}")


def main() -> None:
    root = target_dir() / "wasm2jar-probe"
    for tool in ("xcat", "cptx"):
        jar = root / f"{tool}-standalone.jar"
        if not jar.is_file():
            raise FileNotFoundError(f"{jar}; run just wasm2jar-test-all")
        class_name = f"console.tools.{tool.capitalize()}"
        for suffix in ("$Part0", "", "$Utils", "Launcher"):
            analyze(jar, class_name + suffix)


if __name__ == "__main__":
    main()
