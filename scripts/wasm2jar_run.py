#!/usr/bin/env python3
"""Package wasm2jar cptx with the minimal Java WASI host and smoke-test it."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def run(args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(args, check=True, cwd=ROOT, **kwargs)

def diagnose_illegal_access(jar):
    """Show bytecode context for illegal AssertionError constructor references."""
    listing = subprocess.run(
        ["jar", "tf", str(jar)], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    classes = [entry[:-6].replace("/", ".") for entry in listing
               if entry.endswith(".class") and entry.startswith("console/tools/")]
    for class_name in classes:
        result = subprocess.run(
            ["javap", "-classpath", str(jar), "-c", "-p", class_name],
            check=True, capture_output=True, text=True
        )
        lines = result.stdout.splitlines()
        matches = [i for i, line in enumerate(lines)
                   if "java/lang/AssertionError.\"<init>\"" in line]
        for i in matches:
            print(f"Bytecode reference: {class_name}", flush=True)
            print("\\n".join(lines[max(0, i - 12):min(len(lines), i + 8)]),
                  flush=True)
    print("Note: an inaccessible AssertionError(String) constructor is a "
          "wasm2jar bytecode-generation issue, not a WASI import mismatch.",
          flush=True)

def fix_wasm2jar_assertion_error(stage, tool):
    """Fix wasm2jar 0.1.0's inaccessible AssertionError(String) constructor.

    Change only the UTF8 constant for the constructor descriptor in the
    generated helper class, after verifying its exact occurrence. The
    replacement keeps the same JVM stack behavior (String is an Object).
    """
    path = stage / f"console/tools/{tool.capitalize()}$Utils.class"
    data = path.read_bytes()
    old = b"(Ljava/lang/String;)V"
    new = b"(Ljava/lang/Object;)V"
    if len(old) != len(new):
        raise RuntimeError("Constructor descriptor patch must preserve length")
    if data[:4] != b"\xca\xfe\xba\xbe":
        raise RuntimeError("Generated helper is not a JVM class")
    # Parse the constant pool to avoid replacing unrelated strings or data.
    import struct
    count = struct.unpack_from(">H", data, 8)[0]
    offset = 10
    matches = []
    index = 1
    while index < count:
        tag = data[offset]
        offset += 1
        if tag == 1:
            length = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            if data[offset:offset + length] == old:
                matches.append(offset)
            offset += length
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            offset += 4 if tag in (3, 4) else 4
        elif tag in (5, 6):
            offset += 8
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            offset += 2
        elif tag == 15:
            offset += 3
        else:
            raise RuntimeError(f"Unknown JVM constant pool tag {tag}")
        index += 1
    if len(matches) != 1:
        raise RuntimeError(f"Expected one AssertionError(String) descriptor, found {len(matches)}")
    start = matches[0]
    patched = bytearray(data)
    patched[start:start + len(old)] = new
    path.write_bytes(patched)
    print("Patched wasm2jar AssertionError(String) -> AssertionError(Object)", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", choices=("cptx", "xcat"), default="cptx")
    tool = parser.parse_args().tool
    metadata = subprocess.run(["cargo", "metadata", "--no-deps", "--format-version", "1"],
                              cwd=ROOT, check=True, capture_output=True, text=True)
    target = Path(json.loads(metadata.stdout)["target_directory"])
    original = target / "wasm2jar-probe" / f"{tool}.jar"
    if not original.is_file():
        raise SystemExit("Missing translated JAR: run just wasm2jar-cptx first")
    out = target / "wasm2jar-probe" / f"{tool}-standalone.jar"
    with tempfile.TemporaryDirectory(prefix="cptx-jvm-") as d:
        stage = Path(d)
        with zipfile.ZipFile(original) as archive:
            for item in archive.infolist():
                if item.filename.startswith("META-INF/"):
                    continue
                if ".." in Path(item.filename).parts or item.filename.startswith("/"):
                    raise ValueError("Unsafe JAR entry: " + item.filename)
                if item.is_dir():
                    continue
                dest = stage / item.filename
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(item))
        fix_wasm2jar_assertion_error(stage, tool)
        run(["javac", "-cp", str(original), "-d", str(stage),
             str(ROOT / f"java/console/tools/{tool.capitalize()}Launcher.java")])
        run(["jar", "--create", "--file", str(out), "--main-class",
             f"console.tools.{tool.capitalize()}Launcher", "-C", str(stage), "."])
    print(f"Standalone JAR: {out} ({out.stat().st_size} bytes)")
    result = subprocess.run(["java", "-jar", str(out), "--help"],
                            cwd=ROOT, capture_output=True, text=True)
    print(result.stdout, flush=True)
    if result.returncode:
        print(result.stderr, file=sys.stderr, flush=True)
        raise RuntimeError(f"{tool} JVM --help exited {result.returncode}")
    if tool not in result.stdout:
        raise RuntimeError(f"{tool} JVM --help smoke test failed")
    if tool == "xcat":
        with tempfile.TemporaryDirectory(prefix="xcat-jvm-e2e-") as d:
            folder = Path(d)
            (folder / "hello.md").write_text("JVM_SCAN_UNIQUE_äöü\n", encoding="utf-8")
            (folder / "ignore.bin").write_bytes(b"\x00\xff")
            bindir = folder / "bin"
            bindir.mkdir()
            clipboard = folder / "clipboard"
            mock = bindir / "wl-copy"
            mock.write_text('#!/bin/sh\nexec /bin/cat > "$MOCK_CLIPBOARD"\n')
            mock.chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
            env["WAYLAND_DISPLAY"] = "mock"
            env["MOCK_CLIPBOARD"] = str(clipboard)
            env["XDG_CONFIG_HOME"] = str(folder / "config-home")
            result = subprocess.run(["java", "-jar", str(out), "-d", "."],
                                    cwd=folder, env=env, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"xcat JVM scan exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
            if not clipboard.exists():
                raise RuntimeError("xcat JVM did not invoke clipboard")
            actual = clipboard.read_text(encoding="utf-8")
            if "JVM_SCAN_UNIQUE_äöü" not in actual or "ignore.bin" in actual:
                raise RuntimeError(f"xcat JVM scan output mismatch: {actual[:1000]!r}")
            if not (folder / "config-home" / "xcat" / "config.json").is_file():
                raise RuntimeError("xcat JVM did not create default configuration")
            print("PASS: xcat JVM filesystem scan, UTF-8, config and clipboard")
        return 0
    sample = "WASI stdin äöü\n".encode("utf-8")
    result = run(["java", "-jar", str(out)], input=sample, capture_output=True)
    if result.stdout != sample:
        raise RuntimeError(f"stdin roundtrip failed: {result.stdout!r}")
    with tempfile.TemporaryDirectory(prefix="cptx-jvm-e2e-") as d:
        folder = Path(d)
        bin_dir = folder / "bin"
        bin_dir.mkdir()
        captured = folder / "clipboard"
        tmux = bin_dir / "tmux"
        tmux.write_text('#!/bin/sh\nexec /bin/cat "$MOCK_TMUX_PANE"\n')
        tmux.chmod(0o755)
        clipboard = bin_dir / "wl-copy"
        clipboard.write_text('#!/bin/sh\nexec /bin/cat > "$MOCK_CLIPBOARD"\n')
        clipboard.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["WAYLAND_DISPLAY"] = "mock"
        env["MOCK_TMUX_PANE"] = str(folder / "pane")
        env["MOCK_CLIPBOARD"] = str(captured)
        for repetitions in (1, 16, 256, 1024, 4096, 12000):
            pane = ("JVM_TMUX_SCROLLBACK_äöü\\n" * repetitions).encode("utf-8")
            (folder / "pane").write_bytes(pane)
            captured.unlink(missing_ok=True)
            desktop = subprocess.run(["java", "-jar", str(out), "--desktop"],
                                     cwd=ROOT, env=env, capture_output=True, text=True)
            if desktop.returncode:
                print(f"FAIL: JVM desktop at {len(pane)} bytes ({repetitions} lines)", flush=True)
                if "IllegalAccessError" in desktop.stderr:
                    diagnose_illegal_access(out)
                raise RuntimeError(
                    f"JVM desktop failed (exit {desktop.returncode})\\n"
                    f"stdout:\\n{desktop.stdout}\\nstderr:\\n{desktop.stderr}"
                )
            actual = captured.read_bytes()
            if actual != pane:
                raise RuntimeError(f"tmux/clipboard mismatch at {len(pane)} bytes: got {len(actual)}")
            print(f"PASS: JVM desktop tmux -> Rust WASM -> wl-copy ({len(pane)} bytes)", flush=True)
    print("PASS: JVM --help and UTF-8 stdin roundtrip")
    return 0

if __name__ == "__main__":
    sys.exit(main())
