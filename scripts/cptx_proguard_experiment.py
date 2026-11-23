#!/usr/bin/env python3
"""Experiment: ProGuard shrinking of the default no_std cptx wasm2jar JAR.

Never overwrite the baseline. Compare each candidate with the baseline,
including desktop clipboard integration and invalid UTF-8 behavior.
"""
from __future__ import annotations

import json
import argparse
import shutil
from pathlib import Path
import subprocess
import tempfile
import zipfile

from jvm import proguard_executable, java_home
from wasm2jar_run import test_standalone
from wasi_no_std_jvm_test import test_desktop_failures, test_wasi_io_errors, test_partial_wasi_writes

ROOT = Path(__file__).resolve().parents[1]


def target_dir() -> Path:
    result = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=ROOT, capture_output=True, text=True, check=True)
    return Path(json.loads(result.stdout)["target_directory"])


def temporary_dir(prefix):
    target = target_dir()
    target.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=target)


def verify(baseline: Path, candidate: Path) -> None:
    with zipfile.ZipFile(candidate) as archive:
        manifest = archive.read("META-INF/MANIFEST.MF")
        if b"Main-Class: console.tools.CptxLauncher" not in manifest:
            raise AssertionError("Missing JVM entry point")
    cases = [
        ([], b""), ([], b"ascii\n"), ([], "äöü 😀\n".encode() * 3000),
        ([], b"a" * 16383 + "😀".encode() + b"z" * 16385),
        ([], b"a" * 16384 + b"\xff"), ([], b"\xf0\x9f"),
        (["-h"], b""), (["--help"], b""),
        (["--unknown"], b""), (["-h", "extra"], b""),
    ]
    for arguments, payload in cases:
        def invoke(path: Path) -> subprocess.CompletedProcess:
            return subprocess.run(["java", "-jar", str(path), *arguments],
                                  cwd=ROOT, input=payload, capture_output=True, timeout=60)
        original, optimized = invoke(baseline), invoke(candidate)
        assert (optimized.returncode, optimized.stdout, optimized.stderr) == (
            original.returncode, original.stdout, original.stderr), (
            arguments, len(payload), optimized.returncode,
            optimized.stdout[:100], optimized.stderr[:300])
    print("PASS CLI, binary/UTF-8, 16 KiB boundaries and error parity", flush=True)
    test_standalone(candidate, "cptx")
    test_desktop_failures(candidate)
    # Run WASI fault and partial-write checks against optimized classes.
    with temporary_dir("cptx-proguard-fault-") as directory:
        stage = Path(directory)
        with zipfile.ZipFile(candidate) as archive:
            archive.extractall(stage)
        test_wasi_io_errors(stage)
        # The partial-write harness recompiles a test-only modified host
        # against optimized WASM/runtime classes. It cannot test the
        # ProGuard-optimized host bytecode with an injected short write.
        test_partial_wasi_writes(stage)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, help="Override input JAR (for reproducibility)")
    parser.add_argument("--output-dir", type=Path, help="Override output directory")
    parser.add_argument("--aggressive-only", action="store_true")
    parser.add_argument("--relaxed-keep", action="store_true",
                        help="Allow shrinking and optimization of generated WASM classes")
    parser.add_argument("--promote-to", type=Path,
                        help="Copy verified aggressive candidate to this default JAR")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Only for reproducibility: caller already tests baseline")
    args = parser.parse_args()
    if args.promote_to and (not args.aggressive_only or args.skip_verify):
        parser.error("--promote-to requires --aggressive-only with verification")
    target = args.output_dir or (target_dir() / "wasm2jar-probe")
    target.mkdir(parents=True, exist_ok=True)
    baseline = args.baseline or (target / "cptx-standalone.jar")
    if not baseline.is_file():
        raise SystemExit("Missing baseline: run just wasm2jar-test-cptx first")
    proguard = proguard_executable()
    jmods = sorted((java_home() / "jmods").glob("*.jmod"))
    if not jmods:
        raise RuntimeError("JDK jmods not found")
    print(f"Baseline: {baseline} ({baseline.stat().st_size:,} bytes)", flush=True)
    candidates = [
        ("shrink", ["-dontoptimize", "-dontobfuscate"]),
        ("optimize", ["-dontobfuscate", "-optimizationpasses 5"]),
        ("aggressive", ["-optimizationpasses 5", "-allowaccessmodification",
                        "-mergeinterfacesaggressively"]),
    ]
    if args.aggressive_only:
        candidates = [item for item in candidates if item[0] == "aggressive"]
    results = []
    for name, flags in candidates:
        suffix = "-relaxed-keep" if args.relaxed_keep else ""
        output = target / f"cptx-proguard-{name}{suffix}.jar"
        output.unlink(missing_ok=True)
        rules = [
            f"-injars {baseline}",
            f"-outjars {output}",
            *(f"-libraryjars {jmod}(!**.jar;!module-info.class)" for jmod in jmods),
            "-dontnote",
            # wasm2jar emits signature-polymorphic MethodHandle.invokeExact
            # calls and an inaccessible JDK constructor reference. ProGuard
            # cannot resolve these statically even though the unmodified JAR
            # runs. Suppress only these four known warnings; do not suppress
            # unrelated missing references.
            "-dontwarn java.lang.invoke.MethodHandle",
            "-dontwarn java.lang.IllegalArgumentException",
            "-keepattributes *Annotation*,Signature,InnerClasses,EnclosingMethod",
            "-keep class console.tools.CptxLauncher {",
            "    public static void main(java.lang.String[]);",
            "    public int args_sizes_get(int,int);",
            "    public int args_get(int,int);",
            "    public int environ_sizes_get(int,int);",
            "    public int environ_get(int,int);",
            "    public int fd_read(int,int,int,int);",
            "    public int fd_write(int,int,int,int);",
            "    public void proc_exit(int);",
            "    <init>(java.lang.String[]);",
            "    private int execute();",
            "}",
            # wasm2jar resolves generated functions through MethodHandles and names.
            # Keep generated WASM ABI classes intact, while allowing ProGuard
            # to analyze the Java host and auxiliary runtime classes.
            # Preserve the exported WASM entrypoint used by the partial-write
            # regression harness; the relaxed wildcard may otherwise remove it.
            *(["-keep class console.tools.Cptx { public void _start(); }"]
              if args.relaxed_keep else []),
            f"-keep{',allowshrinking,allowoptimization' if args.relaxed_keep else ''} class console.tools.Cptx {{ *; }}",
            f"-keep{',allowshrinking,allowoptimization' if args.relaxed_keep else ''} class console.tools.Cptx$* {{ *; }}",
            f"-keep{',allowshrinking,allowoptimization' if args.relaxed_keep else ''} class org.wasm2jar.** {{ *; }}",
            *flags,
        ]
        with temporary_dir("cptx-proguard-") as directory:
            config = Path(directory) / "config.pro"
            config.write_text("\n".join(rules) + "\n", encoding="utf-8")
            result = subprocess.run([proguard, f"@{config}"], cwd=ROOT,
                                    capture_output=True, text=True)
        if result.returncode:
            print(f"{name}: ProGuard failed (exit {result.returncode})\n"
                  f"{result.stdout[-2500:]}\n{result.stderr[-3500:]}", flush=True)
            results.append((name, "proguard failed", None))
            continue
        try:
            if not args.skip_verify:
                verify(baseline, output)
        except Exception as exc:
            print(f"{name}: regression FAILED: {exc}", flush=True)
            results.append((name, "regression failed", output.stat().st_size))
            continue
        size = output.stat().st_size
        print(f"PASS {name}: {size:,} bytes ({size - baseline.stat().st_size:+,})",
              flush=True)
        results.append((name, "PASS", size))
    print("\nProGuard experiment summary:")
    for name, status, size in results:
        print(f"  {name:<12} {status:<20} {size if size is not None else '-'}")
    winners = [(size, name) for name, status, size in results
               if status == "PASS" and size < baseline.stat().st_size]
    if winners:
        size, name = min(winners)
        print(f"Smallest verified candidate: {name}, {size:,} bytes")
    else:
        print("No smaller verified candidate; keep baseline unchanged.")
    if any(status != "PASS" for _, status, _ in results):
        raise SystemExit("FAIL one or more ProGuard candidates")
    if args.promote_to:
        suffix = "-relaxed-keep" if args.relaxed_keep else ""
        candidate = target / f"cptx-proguard-aggressive{suffix}.jar"
        destination = args.promote_to
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == baseline.resolve():
            raise SystemExit("Refusing to overwrite the unoptimized baseline")
        with tempfile.NamedTemporaryFile(
                prefix=".cptx-optimized-", suffix=".jar",
                dir=destination.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            shutil.copyfile(candidate, temporary_path)
            temporary_path.replace(destination)
        finally:
            temporary_path.unlink(missing_ok=True)
        print(f"PROMOTED verified aggressive JAR: {destination} "
              f"({destination.stat().st_size:,} bytes)")
    else:
        print("Baseline, default build and native binaries were not modified.")


if __name__ == "__main__":
    main()
