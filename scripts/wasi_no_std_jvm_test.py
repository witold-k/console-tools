#!/usr/bin/env python3
"""Run the isolated no_std streaming WASI fixture through the real Java host.

No production binaries or JARs are replaced. The no_std_cptx variant validates
UTF-8 incrementally but is not equivalent to the full cptx application.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import argparse
import sys
import zipfile

from cptx_size_floor import ROOT, TARGET
from wasi_no_std_floor import NO_STD
from wasm2jar_run import fix_wasm2jar_assertion_error, test_standalone


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(map(str, argv)), flush=True)
    return subprocess.run(argv, cwd=ROOT, check=True, **kwargs)


def test_desktop_failures(jar: Path) -> None:
    """Desktop errors must never launch the clipboard after failed capture/validation."""
    with tempfile.TemporaryDirectory(prefix="no-std-desktop-errors-") as directory:
        root = Path(directory)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        pane = root / "pane"
        marker = root / "clipboard-invoked"
        tmux = bin_dir / "tmux"
        clipboard = bin_dir / "wl-copy"
        clipboard.write_text('#!/bin/sh\ntouch "$MOCK_CLIPBOARD_MARKER"\nexit "${MOCK_CLIPBOARD_EXIT:-0}"\n')
        clipboard.chmod(0o755)
        env = dict(os.environ)
        env.update(PATH=str(bin_dir) + os.pathsep + env.get("PATH", ""),
                   WAYLAND_DISPLAY="mock", MOCK_TMUX_PANE=str(pane),
                   MOCK_CLIPBOARD_MARKER=str(marker))
        java_executable = shutil.which("java")
        if java_executable is None:
            raise RuntimeError("Java executable not found")
        java_executable = str(Path(java_executable).resolve())
        def invoke() -> subprocess.CompletedProcess:
            marker.unlink(missing_ok=True)
            return subprocess.run([java_executable, "-jar", str(jar), "--desktop"],
                                  cwd=ROOT, env=env, capture_output=True, timeout=60)
        tmux.write_text('#!/bin/sh\nexit 23\n')
        tmux.chmod(0o755)
        result = invoke()
        assert result.returncode != 0 and not marker.exists(), ("tmux failure", result.stderr)
        print("PASS desktop tmux failure: clipboard not invoked")
        tmux.write_text('#!/bin/sh\nexec /bin/cat "$MOCK_TMUX_PANE"\n')
        pane.write_bytes(b"a" * 8192 + bytes((0xff,)))
        result = invoke()
        assert result.returncode != 0 and not marker.exists(), ("invalid UTF-8", result.stderr)
        print("PASS desktop late invalid UTF-8: clipboard not invoked")
        pane.write_bytes("valid äöü\\n".encode("utf-8"))
        env["MOCK_CLIPBOARD_EXIT"] = "19"
        result = invoke()
        assert result.returncode != 0 and marker.exists(), ("clipboard failure", result.stderr)
        print("PASS desktop clipboard failure: nonzero exit")
        clipboard.unlink()
        env["PATH"] = str(bin_dir)
        result = invoke()
        assert result.returncode != 0 and not marker.exists(), ("missing clipboard", result.stderr)
        assert b"wl-copy" in result.stderr, ("missing clipboard diagnostic", result.stderr)
        print("PASS desktop missing clipboard executable: nonzero exit")


def test_wasi_io_errors(stage: Path) -> None:
    """Inject Java stream failures without changing normal launcher behavior."""
    harness = stage / "CptxIoFaultHarness.java"
    harness.write_text(r"""
import java.io.*;
import java.lang.reflect.*;

public final class CptxIoFaultHarness {
    public static void main(String[] args) throws Exception {
        Class<?> type = Class.forName("console.tools.CptxLauncher");
        Constructor<?> ctor = type.getDeclaredConstructor(String[].class);
        ctor.setAccessible(true);
        Method execute = type.getDeclaredMethod("execute");
        execute.setAccessible(true);
        InputStream oldIn = System.in;
        PrintStream oldOut = System.out;
        try {
            if (args[0].equals("read")) {
                System.setIn(new InputStream() {
                    @Override public int read() throws IOException {
                        throw new IOException("injected read failure");
                    }
                    @Override public int read(byte[] b, int off, int len) throws IOException {
                        throw new IOException("injected read failure");
                    }
                });
            } else {
                System.setIn(new ByteArrayInputStream("hello".getBytes("UTF-8")));
                System.setOut(new PrintStream(new OutputStream() {
                    @Override public void write(int b) throws IOException {
                        throw new IOException("injected write failure");
                    }
                    @Override public void write(byte[] b, int off, int len) throws IOException {
                        throw new IOException("injected write failure");
                    }
                }));
            }
            Object host = ctor.newInstance((Object) new String[0]);
            int status = (Integer) execute.invoke(host);
            if (status == 0) throw new AssertionError("Expected nonzero WASI exit");
            System.err.println("PASS injected WASI fd_" + args[0] + " error: exit=" + status);
        } finally {
            System.setIn(oldIn);
            System.setOut(oldOut);
        }
    }
}
""", encoding="utf-8")
    run(["javac", "-cp", str(stage), "-d", str(stage), str(harness)])
    for operation in ("read", "write"):
        result = subprocess.run(["java", "-cp", str(stage), "CptxIoFaultHarness", operation],
                                cwd=ROOT, capture_output=True, timeout=60)
        assert result.returncode == 0 and (
            f"PASS injected WASI fd_{operation} error".encode() in result.stderr
        ), (operation, result.returncode, result.stderr)
        print(f"PASS injected WASI fd_{operation} error")


def test_partial_wasi_writes(stage: Path) -> None:
    """Force short successful fd_write results in a test-only Java host."""
    original = (ROOT / "java/console/tools/CptxLauncher.java").read_text(encoding="utf-8")
    method_start = original.index("    public int fd_write(")
    method_end = original.index("    private static final class Exit", method_start)
    method = original[method_start:method_end]
    needle = "long length = unsigned(m.getInt((int) (base + i * 8L + 4)));"
    assert method.count(needle) == 1, "fd_write host implementation changed"
    patched = method.replace(needle, needle + "\n                length = Math.min(length, 7);")
    with tempfile.TemporaryDirectory(prefix="no-std-partial-write-") as directory:
        override = Path(directory)
        source = override / "console/tools/CptxLauncher.java"
        source.parent.mkdir(parents=True)
        source.write_text(original[:method_start] + patched + original[method_end:],
                          encoding="utf-8")
        run(["javac", "-cp", str(stage), "-d", str(override), str(source)])
        classpath = os.pathsep.join((str(override), str(stage)))
        cases = {
            "ascii": b"short writes must retry\n",
            "utf8": ("äöü 😀 — " * 300).encode("utf-8"),
            "large": ("boundary ä 😀\n" * 6000).encode("utf-8"),
        }
        for name, payload in cases.items():
            result = subprocess.run(["java", "-cp", classpath,
                                     "console.tools.CptxLauncher"],
                                    cwd=ROOT, input=payload, capture_output=True, timeout=60)
            assert result.returncode == 0 and result.stdout == payload, (
                name, result.returncode, len(result.stdout), result.stderr[:500])
            print(f"PASS partial WASI fd_write {name}: {len(payload):,} bytes")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", nargs="?", choices=("no_std_stream", "no_std_cptx"),
                        default="no_std_stream")
    parser.add_argument("--raw-wasm", action="store_true")
    parser.add_argument("--compare-native", action="store_true")
    parser.add_argument("--output-jar", type=Path,
                        help="Optional persistent standalone JAR; production build unchanged")
    args = parser.parse_args()
    if args.output_jar and args.variant != "no_std_cptx":
        parser.error("--output-jar requires no_std_cptx")
    for tool in ("rustc", "wasm-opt", "wasm2jar", "javac", "jar", "java"):
        if not shutil.which(tool):
            raise RuntimeError(f"Required executable not found: {tool}")
    variant = args.variant
    use_raw = args.raw_wasm
    compare_native = args.compare_native
    with tempfile.TemporaryDirectory(prefix="no-std-jvm-e2e-") as directory:
        tmp = Path(directory)
        source = tmp / "stream.rs"
        source.write_text(NO_STD[variant], encoding="utf-8")
        wasm = tmp / "stream.wasm"
        optimized = tmp / "stream.opt.wasm"
        translated = tmp / "stream-translated.jar"
        standalone = tmp / "stream-standalone.jar"
        run(["rustc", "--edition=2024", "--target", TARGET, str(source),
             "--crate-type=cdylib", "-o", str(wasm), "-C", "opt-level=z",
             "-C", "lto=fat", "-C", "codegen-units=1", "-C", "panic=abort",
             "-C", "strip=symbols", "-C", "link-arg=--export=_start"])
        run(["wasm-opt", "-Oz", "--enable-bulk-memory", "--strip-debug",
             "--strip-producers", str(wasm), "-o", str(optimized)])
        module = wasm if use_raw else (optimized if optimized.stat().st_size < wasm.stat().st_size else wasm)
        if compare_native:
            runtime = shutil.which("wasmtime") or shutil.which("wasmer")
            if runtime is None:
                raise RuntimeError("Install wasmtime or wasmer for native WASI comparison")
            print(f"Native WASI runtime: {runtime}", flush=True)
            native_cases = {
                "valid_utf8": "Grüße 😀\n".encode("utf-8"),
                "invalid_utf8": bytes((0xff, 0xfe)),
                "incomplete_utf8": bytes((0xf0, 0x9f)),
                "split_invalid": b"a" * 16383 + bytes((0xf0, 0xff)),
            }
            assert native_cases["invalid_utf8"] == bytes((0xff, 0xfe))
            assert native_cases["incomplete_utf8"] == bytes((0xf0, 0x9f))
            for label, payload in native_cases.items():
                command = [runtime, str(module)]
                native = subprocess.run(command, input=payload, capture_output=True,
                                        cwd=ROOT, timeout=60)
                print(f"NATIVE {label}: exit={native.returncode}, "
                      f"stdout={native.stdout[:100]!r}, "
                      f"stderr={native.stderr[:500]!r}", flush=True)
                if label == "valid_utf8":
                    assert native.returncode == 0 and native.stdout == payload, label
                else:
                    assert native.returncode != 0, label
        print(f"Selected WASM: {'raw' if use_raw else 'size-optimized'} "
              f"({module.stat().st_size:,} bytes)", flush=True)
        run(["wasm2jar", "--output-class", "console/tools/Cptx",
             "--jar", str(translated), str(module)])
        stage = tmp / "stage"
        stage.mkdir()
        with zipfile.ZipFile(translated) as archive:
            for entry in archive.infolist():
                if entry.is_dir() or entry.filename.startswith("META-INF/"):
                    continue
                if entry.filename.startswith("/") or ".." in Path(entry.filename).parts:
                    raise ValueError("Unsafe JAR entry")
                destination = stage / entry.filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(entry))
        # The existing patch is required only if wasm2jar emitted the known
        # inaccessible AssertionError(String) constructor descriptor.
        helper = stage / "console/tools/Cptx$Utils.class"
        if helper.is_file() and b"(Ljava/lang/String;)V" in helper.read_bytes():
            fix_wasm2jar_assertion_error(stage, "cptx")
        run(["javac", "-cp", str(translated), "-d", str(stage),
             str(ROOT / "java/console/tools/CptxLauncher.java")])
        run(["jar", "--create", "--file", str(standalone),
             "--main-class", "console.tools.CptxLauncher", "-C", str(stage), "."])
        print(f"no_std standalone JVM JAR: {standalone.stat().st_size:,} B")
        cases = {
            "empty": b"",
            "ascii": b"hello\n",
            "utf8": "Grüße 😀\n".encode("utf-8"),
            "buffer_boundary": b"a" * 16383 + b"XYZ" + b"b" * 16385,
            "large": ("JVM UTF-8 äöü 😀\n" * 32768).encode("utf-8"),
            "invalid_utf8": b"\xff\xfe\x00\x80",
        }
        if variant == "no_std_cptx":
            cases.pop("invalid_utf8")
            cases["split_utf8"] = b"a" * 16383 + "😀".encode("utf-8") + b"b" * 16400
        for name, data in cases.items():
            result = subprocess.run(["java", "-jar", str(standalone)], cwd=ROOT,
                                    input=data, capture_output=True, timeout=60)
            if result.returncode:
                raise RuntimeError(f"{name}: JVM exit {result.returncode}; "
                                   f"stderr={result.stderr[:2000]!r}; "
                                   f"stdout_len={len(result.stdout)}")
            if result.stdout != data:
                raise AssertionError(f"{name}: byte mismatch "
                                     f"({len(result.stdout)} vs {len(data)})")
            print(f"PASS {name}: {len(data):,} bytes")
        if variant == "no_std_cptx":
            for option in ("-h", "--help"):
                result = run(["java", "-jar", str(standalone), option],
                             capture_output=True, timeout=60)
                expected_help = (
                    "cptx — copy the current tmux pane and its scrollback to the clipboard\n\n"
                    "Usage: cptx [-h|--help]\n\n"
                    "Requires tmux and a supported clipboard backend "
                    "(xclip, xsel, or wl-copy).\n"
                ).encode("utf-8")
                assert result.stdout == expected_help and result.stderr == b"", (
                    option, result.stdout, result.stderr)
                print(f"PASS CLI {option}")
            for option in ("--unknown", "--help", "-h"):
                arguments = [option, "extra"] if option != "--unknown" else [option]
                result = subprocess.run(["java", "-jar", str(standalone), *arguments],
                                        cwd=ROOT, capture_output=True, timeout=60)
                assert result.returncode == 1 and result.stderr == b"cptx: Usage: cptx [-h|--help]\n", (
                    arguments, result.returncode, result.stderr)
                print(f"PASS rejected CLI {arguments}")
            invalid_cases = {"invalid_utf8": bytes((0xff, 0xfe)),
                               "large_invalid_binary": bytes(range(256)) * 2048,
                               "incomplete_utf8": bytes((0xf0, 0x9f)),
                               "split_invalid": b"a" * 4095 + bytes((0xf0, 0xff))}
            assert invalid_cases["invalid_utf8"] == bytes((0xff, 0xfe))
            assert invalid_cases["incomplete_utf8"] == bytes((0xf0, 0x9f))
            for name, data in invalid_cases.items():
                result = subprocess.run(["java", "-jar", str(standalone)],
                                        cwd=ROOT, input=data, capture_output=True, timeout=60)
                if result.returncode == 0 or b"invalid UTF-8" not in result.stderr:
                    raise AssertionError(
                        f"{name}: expected nonzero exit and invalid UTF-8 message; "
                        f"exit={result.returncode}, "
                        f"stdout={result.stdout[:200]!r}, "
                        f"stderr={result.stderr[:2000]!r}")
                print(f"PASS rejected {name}")
            immediate = subprocess.run(["java", "-jar", str(standalone)],
                                       cwd=ROOT, input=bytes((0xff, 0xfe)),
                                       capture_output=True, timeout=60)
            assert immediate.returncode != 0 and immediate.stdout == b"", (
                immediate.returncode, immediate.stdout[:100])
            late = subprocess.run(["java", "-jar", str(standalone)],
                                  cwd=ROOT, input=b"a" * 16384 + bytes((0xff,)),
                                  capture_output=True, timeout=60)
            assert late.returncode != 0 and late.stdout == b"a" * 16384, (
                late.returncode, len(late.stdout), late.stderr[:200])
            print("PASS immediate invalid input: no stdout")
            print("CONFIRMED semantic gap: late invalid input emitted 16384 bytes")
            # Exercise the actual tmux -> WASM -> clipboard desktop path with
            # the same mocks and payload sizes as the production JAR suite.
            test_standalone(standalone, "cptx")
            print("PASS no_std desktop integration (tmux -> WASM -> clipboard)")
            test_desktop_failures(standalone)
            test_wasi_io_errors(stage)
            test_partial_wasi_writes(stage)
            print("NOTE: streaming may emit a valid prefix before later invalid UTF-8;")
            print("the original cptx validates the entire input before writing.")
        else:
            print("NOTE: invalid UTF-8 is intentionally passed through, unlike full cptx.")
        if variant == "no_std_cptx":
            print("PASS short fd_write responses verified with a test-only Java host.")
        if args.output_jar:
            output = args.output_jar.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(standalone, output)
            print(f"Packaged no_std JAR: {output} ({output.stat().st_size:,} B)")
        print("Native binaries and xcat artifacts unchanged.")


if __name__ == "__main__":
    main()
