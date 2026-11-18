#!/usr/bin/env python3
"""Run the isolated no_std streaming WASI fixture through the real Java host.

No production binaries or JARs are replaced. The generated fixture is not
UTF-8 validating and is not equivalent to the full cptx application.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import zipfile

from cptx_size_floor import ROOT, TARGET
from wasi_no_std_floor import NO_STD
from wasm2jar_run import fix_wasm2jar_assertion_error


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(map(str, argv)), flush=True)
    return subprocess.run(argv, cwd=ROOT, check=True, **kwargs)


def main() -> None:
    for tool in ("rustc", "wasm-opt", "wasm2jar", "javac", "jar", "java"):
        if not shutil.which(tool):
            raise RuntimeError(f"Required executable not found: {tool}")
    variant = sys.argv[1] if len(sys.argv) > 1 else "no_std_stream"
    if variant not in ("no_std_stream", "no_std_cptx"):
        raise SystemExit("Usage: wasi_no_std_jvm_test.py [no_std_stream|no_std_cptx]")
    use_raw = "--raw-wasm" in sys.argv[2:]
    compare_native = "--compare-native" in sys.argv[2:]
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
                "split_invalid": b"a" * 4095 + bytes((0xf0, 0xff)),
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
            "buffer_boundary": b"a" * 4095 + b"XYZ" + b"b" * 4097,
            "large": ("JVM UTF-8 äöü 😀\n" * 32768).encode("utf-8"),
            "invalid_utf8": b"\xff\xfe\x00\x80",
        }
        if variant == "no_std_cptx":
            cases.pop("invalid_utf8")
            cases["split_utf8"] = b"a" * 4095 + "😀".encode("utf-8") + b"b" * 4100
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
                assert b"Usage: cptx" in result.stdout, option
                print(f"PASS CLI {option}")
            for option in ("--unknown", "--help", "-h"):
                arguments = [option, "extra"] if option != "--unknown" else [option]
                result = subprocess.run(["java", "-jar", str(standalone), *arguments],
                                        cwd=ROOT, capture_output=True, timeout=60)
                assert result.returncode != 0 and b"Usage:" in result.stderr, arguments
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
                                  cwd=ROOT, input=b"a" * 4096 + bytes((0xff,)),
                                  capture_output=True, timeout=60)
            assert late.returncode != 0 and late.stdout == b"a" * 4096, (
                late.returncode, len(late.stdout), late.stderr[:200])
            print("PASS immediate invalid input: no stdout")
            print("CONFIRMED semantic gap: late invalid input emitted 4096 bytes")
            print("NOTE: streaming may emit a valid prefix before later invalid UTF-8;")
            print("the original cptx validates the entire input before writing.")
        else:
            print("NOTE: invalid UTF-8 is intentionally passed through, unlike full cptx.")
        print("NOTE: Java host's fd_write writes whole chunks; partial writes are")
        print("handled by the fixture but not artificially injected by this test.")
        print("NOTE: read/write error paths are not injected by this test.")
        print("No production artifacts changed.")


if __name__ == "__main__":
    main()
