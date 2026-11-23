#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and smoke-test native + WASI console-tools without external crates."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TARGET = "wasm32-wasip1"
def target_dir() -> Path:
    metadata = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return Path(json.loads(metadata.stdout)["target_directory"])


OUT = target_dir() / TARGET / "release"


def temporary_dir(prefix):
    target = target_dir()
    target.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=target)


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def verify_dependencies() -> None:
    lines = (ROOT / "Cargo.toml").read_text(encoding="utf-8").splitlines()
    active = False
    for line in lines:
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("["):
            active = stripped == "[dependencies]"
        elif active and stripped:
            raise RuntimeError("Cargo.toml contains an external dependency: " + stripped)


def setup() -> None:
    run(["rustup", "target", "add", TARGET])
    if not shutil.which("wasmtime"):
        print("wasmtime is not installed; install its CLI to run the WASI artifacts.",
              file=sys.stderr)


def build() -> None:
    verify_dependencies()
    run(["cargo", "test", "--offline"])
    run(["cargo", "build", "--offline", "--release", "--bin", "wasm-host"])
    # Override the workspace release profile for this WASI build only.
    optimized_env = dict(os.environ)
    optimized_env.update({
        "CARGO_PROFILE_RELEASE_OPT_LEVEL": "z",
        "CARGO_PROFILE_RELEASE_LTO": "true",
        "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "1",
        "CARGO_PROFILE_RELEASE_PANIC": "abort",
        "CARGO_PROFILE_RELEASE_STRIP": "symbols",
    })
    before = {name: (OUT / (name + ".wasm")).stat().st_size
              for name in ("xcat", "cptx") if (OUT / (name + ".wasm")).is_file()}
    run(["cargo", "build", "--offline", "--release", "--target", TARGET,
         "--bin", "xcat", "--bin", "cptx"], env=optimized_env)
    optimize_wasm()
    print(f"Native host: {target_dir() / 'release/wasm-host'}", flush=True)
    for name in ("xcat", "cptx"):
        path = OUT / f"{name}.wasm"
        if not path.is_file():
            raise RuntimeError(f"Missing WASM output: {path}")
        size = path.stat().st_size
        previous = before.get(name)
        print(f"{path}: {size} bytes" +
              (f" (previous: {previous}, change: {size - previous:+d} bytes)"
               if previous is not None else " (no previous build)"), flush=True)



def optimize_wasm() -> None:
    """Optionally shrink WASI modules with Binaryen; keep originals if not smaller."""
    optimizer = shutil.which("wasm-opt")
    if not optimizer:
        print("wasm-opt not found; skipping optional Binaryen size optimization",
              flush=True)
        return
    for name in ("xcat", "cptx"):
        source = OUT / f"{name}.wasm"
        if not source.is_file():
            raise RuntimeError(f"Missing WASM output: {source}")
        original_size = source.stat().st_size
        # Write to a sibling file so a failed optimizer never damages the module.
        with tempfile.TemporaryDirectory(prefix=f"{name}-binaryen-", dir=OUT) as d:
            optimized = Path(d) / f"{name}.wasm"
            command = [optimizer, "-Oz", "--enable-bulk-memory",
                       "--strip-debug", "--strip-producers",
                       str(source), "-o", str(optimized)]
            print("+", " ".join(command), flush=True)
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Binaryen optimization failed for {name}; retaining original: "
                      f"{result.stderr.strip()}", file=sys.stderr)
                continue
            optimized_size = optimized.stat().st_size
            if optimized_size < original_size:
                os.replace(optimized, source)
                print(f"{name}.wasm: {original_size} -> {optimized_size} bytes "
                      f"({original_size - optimized_size} bytes saved)", flush=True)
            else:
                print(f"{name}.wasm: Binaryen did not reduce size "
                      f"({original_size} -> {optimized_size} bytes); retaining original",
                      flush=True)



def read_uleb(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(5):
        if pos >= len(data):
            raise ValueError("Truncated WASM LEB128 integer")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7f) << shift
        if byte < 0x80:
            return value, pos
        shift += 7
    raise ValueError("Invalid WASM LEB128 integer")


def read_wasm_string(data: bytes, pos: int) -> tuple[str, int]:
    size, pos = read_uleb(data, pos)
    end = pos + size
    if end > len(data):
        raise ValueError("Truncated WASM string")
    return data[pos:end].decode("utf-8"), end


def inspect_wasm(path: Path) -> None:
    """Report actual WASI imports and binary sections without extra dependencies."""
    data = path.read_bytes()
    if data[:8] != bytes.fromhex("0061736d01000000"):
        raise ValueError(f"Invalid WASM v1 header: {path}")
    sections = []
    imports = []
    section_names = {
        0: "custom", 1: "type", 2: "import", 3: "function",
        4: "table", 5: "memory", 6: "global", 7: "export",
        8: "start", 9: "element", 10: "code", 11: "data",
        12: "data_count",
    }
    pos = 8
    while pos < len(data):
        start = pos
        section_id = data[pos]
        pos += 1
        length, pos = read_uleb(data, pos)
        end = pos + length
        if end > len(data):
            raise ValueError(f"Truncated WASM section {section_id}: {path}")
        payload = data[pos:end]
        label = section_names.get(section_id, f"section_{section_id}")
        if section_id == 0:
            label, _ = read_wasm_string(payload, 0)
            label = "custom:" + label
        elif section_id == 2:
            cursor = 0
            count, cursor = read_uleb(payload, cursor)
            for _ in range(count):
                module, cursor = read_wasm_string(payload, cursor)
                field, cursor = read_wasm_string(payload, cursor)
                if cursor >= len(payload):
                    raise ValueError("Truncated WASM import")
                kind = payload[cursor]
                cursor += 1
                # We only need the names. Parse each descriptor to reach the next import.
                if kind == 0:  # function type index
                    _, cursor = read_uleb(payload, cursor)
                elif kind == 1:  # table: ref type + limits
                    cursor += 1
                    flags, cursor = read_uleb(payload, cursor)
                    _, cursor = read_uleb(payload, cursor)
                    if flags & 1:
                        _, cursor = read_uleb(payload, cursor)
                elif kind == 2:  # memory limits
                    flags, cursor = read_uleb(payload, cursor)
                    _, cursor = read_uleb(payload, cursor)
                    if flags & 1:
                        _, cursor = read_uleb(payload, cursor)
                elif kind == 3:  # global: value type + mutability
                    cursor += 2
                else:
                    raise ValueError(f"Unsupported WASM import kind {kind}")
                imports.append((module, field, ("func", "table", "memory", "global")[kind]))
        sections.append((label, end - start))
        pos = end
    print(f"\\n{path.name}: {len(data)} bytes", flush=True)
    print("  Sections (including headers):", flush=True)
    for label, size in sections:
        print(f"    {label}: {size} bytes", flush=True)
    print(f"  Imports: {len(imports)}", flush=True)
    for module, field, kind in imports:
        print(f"    {module}.{field} [{kind}]", flush=True)
    wasi = sorted({field for module, field, _ in imports if module.startswith("wasi_")})
    print(f"  Distinct WASI imports: {len(wasi)}", flush=True)
    print("  Note: import count describes the required host API, not runtime size.",
          flush=True)


def analyze() -> None:
    for name in ("xcat", "cptx"):
        path = OUT / f"{name}.wasm"
        if not path.is_file():
            raise RuntimeError(f"Missing WASM output: {path}; run build first")
        inspect_wasm(path)



def wasmtime(name: str, args: list[str], mounts: list[tuple[Path, str]] | None = None,
             input_data: bytes | None = None) -> subprocess.CompletedProcess:
    command = [os.environ.get("CONSOLE_TOOLS_WASM_RUNNER", "wasmtime"), "run"]
    for host, guest in mounts or []:
        command.extend(["--dir", f"{host}::{guest}"])
    command.extend([str(OUT / f"{name}.wasm"), *args])
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, input=input_data, capture_output=True, check=True)


def test() -> None:
    verify_dependencies()
    runner = os.environ.get("CONSOLE_TOOLS_WASM_RUNNER", "wasmtime")
    if not shutil.which(runner):
        raise RuntimeError(f"WASI runner is not available: {runner}")
    help_cptx = wasmtime("cptx", ["--help"])
    assert b"tmux" in help_cptx.stdout, help_cptx.stdout
    help_xcat = wasmtime("xcat", ["--help"])
    assert b"scan" in help_xcat.stdout, help_xcat.stdout
    text = b"Unicode: \xc3\xa4\xc3\xb6\xc3\xbc\n"
    capture = wasmtime("cptx", [], input_data=text)
    assert capture.stdout == text, (capture.stdout, text)
    with temporary_dir("console-tools-wasm-") as d:
        temp = Path(d)
        root = temp / "project"
        root.mkdir()
        (root / "src").mkdir()
        (root / "target").mkdir()
        (root / "src" / "keep.rs").write_text("fn example() {}\n", encoding="utf-8")
        (root / "target" / "skip.rs").write_text("must not appear\n", encoding="utf-8")
        (root / "image.bin").write_bytes(b"\x00\xff\x00")
        (root / "Cargo.toml").write_text("[package]\nname=\"sample\"\n", encoding="utf-8")
        config = temp / "config.json"
        config.write_text(json.dumps({
            "scanendfilter": [".rs"],
            "scanfullfilter": ["Cargo.toml"],
            "excludedirs": ["target"],
            "max_file_bytes": 1000,
        }), encoding="utf-8")
        result = wasmtime("xcat", ["-d", "/work", "-c", "/cfg/config.json"],
                          [(root, "/work"), (temp, "/cfg")])
        actual = result.stdout.decode("utf-8")
        assert "src/keep.rs" in actual, actual
        assert "Cargo.toml" in actual, actual
        assert "skip.rs" not in actual, actual
        assert "image.bin" not in actual, actual
        stdout = temp / "stdout"
        stderr = temp / "stderr"
        stdout.write_bytes(b"task success\n")
        stderr.write_bytes(b"")
        report = wasmtime("xcat", ["--wasm-task-report", "script.sh",
                                  "/cfg/stdout", "/cfg/stderr", "0"],
                          [(temp, "/cfg")]).stdout.decode("utf-8")
        assert "EXECUTABLE OUTPUT: script.sh" in report, report
        assert "task success" in report, report
        assert "EXIT STATUS: 0" in report, report
    # Real WASI modules + real Rust host, with mocked external OS commands.
    if os.name == "posix":
        with temporary_dir("console-tools-wasm-e2e-") as d:
            temp = Path(d)
            bin_dir = temp / "bin"
            root = temp / "work"
            bin_dir.mkdir()
            root.mkdir()
            (root / "test.rs").write_text("pub fn main() {}\n", encoding="utf-8")
            config = temp / "config.json"
            config.write_text(json.dumps({
                "scanendfilter": [".rs", ".sh"],
                "scanfullfilter": [],
                "excludedirs": ["target"],
                "max_file_bytes": 2048,
            }), encoding="utf-8")
            clipboard = temp / "clipboard"
            def script(path: Path, source: str) -> None:
                path.write_text("#!/bin/sh\n" + source, encoding="utf-8")
                path.chmod(0o755)
            script(bin_dir / "wl-copy", 'exec /bin/cat > "$CAPTURED_CLIPBOARD"\n')
            script(bin_dir / "tmux", "printf 'WASM_TMUX_SENTINEL\\n'\n")
            task = root / "task.sh"
            script(task, "printf 'TASK_STDOUT\\n'\nprintf 'TASK_STDERR\\n' >&2\n")
            env = dict(os.environ)
            env["WAYLAND_DISPLAY"] = "mock"
            env.pop("DISPLAY", None)
            env["CAPTURED_CLIPBOARD"] = str(clipboard)
            env["CONSOLE_TOOLS_WASM_DIR"] = str(OUT)
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            host = str(target_dir() / "release" / "wasm-host")
            run([host, "xcat", "-d", str(root), "-c", str(config)],
                env=env, capture_output=True)
            assert "test.rs" in clipboard.read_text(encoding="utf-8")
            run([host, "cptx"], env=env, capture_output=True)
            assert clipboard.read_text(encoding="utf-8") == "WASM_TMUX_SENTINEL\n"
            run([host, "xcat", "-r", "task.sh", "-d", str(root)],
                env=env, capture_output=True)
            report = clipboard.read_text(encoding="utf-8")
            assert "TASK_STDOUT" in report and "TASK_STDERR" in report, report
            assert "EXIT STATUS: 0" in report, report
        print("PASS: actual Rust host + actual WASI + mocked tmux, task and clipboard")

    print("PASS: WASI CLI help, stdin, filtered filesystem scanning, and report formatting")


def main(argv: list[str]) -> int:
    try:
        if argv == ["setup"]:
            setup()
        elif argv == ["build"]:
            build()
        elif argv == ["test"]:
            test()
        elif argv == ["analyze"]:
            analyze()
        else:
            print("Usage: python3 scripts/wasm.py {setup|build|test|analyze}", file=sys.stderr)
            return 2
        return 0
    except (RuntimeError, AssertionError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"WASM error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
