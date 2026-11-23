#!/usr/bin/env python3
"""JVM packaging and ProGuard helpers invoked by the Justfile."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import re
import zipfile

ROOT = Path(__file__).resolve().parent.parent

def cargo_target_dir():
    metadata = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return Path(json.loads(metadata.stdout)["target_directory"])

TARGET_DIR = cargo_target_dir()
DIST = TARGET_DIR / "jvm-dist"
PACKAGE = TARGET_DIR / "jvm-package" / "release"
PROGUARD_VERSION = "7.10.0"
PROGUARD_DIR = TARGET_DIR / "tools" / f"proguard-{PROGUARD_VERSION}"


def run(*args, env=None):
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def runtime_path():
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return base / "cargo-jvm/rustc_codegen_jvm/runtime/build/libs/runtime-0.1.0.jar"


def target_dir():
    """Report Cargo's effective target directory without creating anything."""
    print(TARGET_DIR)


def cargo_jvm(*args):
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET_DIR)
    env["RUSTFLAGS"] = "-C panic=abort"
    run("cargo", "jvm", *args, env=env)


def setup():
    run("cargo", "install", "cargo-jvm")
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET_DIR)
    run("cargo", "jvm", "setup", env=env)
    run("cargo", "jvm", "doctor", env=env)


def build():
    for name in ("xcat", "cptx"):
        cargo_jvm("build", "--bin", name)


def package():
    for name in ("xcat", "cptx"):
        cargo_jvm("package", "--release", "--bin", name)


def smoke():
    cargo_jvm("run", "--bin", "xcat", "--", "--help")


def manifest_attributes(data):
    # Preserve Main-Class and other existing attributes, replacing Class-Path.
    lines = data.decode("utf-8").replace("\r\n", "\n").split("\n")
    out = []
    skip = False
    for line in lines:
        if line.lower().startswith("class-path:"):
            skip = True
            continue
        if skip and line.startswith(" "):
            continue
        skip = False
        if line:
            out.append(line)
    return out


def write_jar(source, output, runtime=None, thin=False):
    with zipfile.ZipFile(source) as app:
        manifest = app.read("META-INF/MANIFEST.MF")
        attributes = manifest_attributes(manifest)
        if thin:
            attributes.append("Class-Path: runtime-0.1.0.jar")
        new_manifest = ("\r\n".join(attributes) + "\r\n\r\n").encode("utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as dst:
            seen = set()
            for archive in ([app] if thin else [app, runtime]):
                for info in archive.infolist():
                    name = info.filename
                    if name in seen or name == "META-INF/MANIFEST.MF":
                        continue
                    if name.upper().startswith("META-INF/") and name.upper().endswith((".SF", ".RSA", ".DSA", ".EC")):
                        continue
                    seen.add(name)
                    dst.writestr(name, archive.read(name))
            dst.writestr("META-INF/MANIFEST.MF", new_manifest)


def distributions():
    runtime = runtime_path()
    if not runtime.is_file():
        raise FileNotFoundError(f"Missing JVM runtime: {runtime}")
    thin_dir = DIST / "thin"
    standalone_dir = DIST / "standalone"
    for name in ("xcat", "cptx"):
        if not (PACKAGE / f"{name}.jar").is_file():
            raise FileNotFoundError(f"Missing JVM package: {PACKAGE / f'{name}.jar'}")
    thin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(runtime, thin_dir / "runtime-0.1.0.jar")
    with zipfile.ZipFile(runtime) as runtime_jar:
        for name in ("xcat", "cptx"):
            source = PACKAGE / f"{name}.jar"
            if not source.is_file():
                raise FileNotFoundError(f"Missing JVM package: {source}")
            write_jar(source, thin_dir / f"{name}.jar", thin=True)
            write_jar(source, standalone_dir / f"{name}.jar", runtime=runtime_jar)
    print(f"Thin JARs: {thin_dir} (keep runtime-0.1.0.jar beside them)")
    print(f"Standalone JARs: {standalone_dir}")


def test_distributions():
    for layout in ("thin", "standalone"):
        for name in ("xcat", "cptx"):
            run("java", "-jar", str(DIST / layout / f"{name}.jar"), "--help")


def java_home():
    if os.environ.get("JAVA_HOME"):
        return Path(os.environ["JAVA_HOME"])
    javac = shutil.which("javac")
    if not javac:
        raise RuntimeError("javac not found; a full JDK is required")
    return Path(javac).resolve().parent.parent



def proguard_executable():
    """Use a compatible local ProGuard, installing a pinned release if necessary."""
    override = os.environ.get("PROGUARD")
    if override:
        path = shutil.which(override)
        if not path:
            raise RuntimeError(f"PROGUARD executable not found: {override}")
        return path
    local = PROGUARD_DIR / "bin" / "proguard.sh"
    if local.is_file():
        return str(local)
    installed = shutil.which("proguard")
    if installed:
        result = subprocess.run([installed, "-version"], capture_output=True, text=True)
        match = re.search(r"version\\s+(\\d+)\\.(\\d+)(?:\\.(\\d+))?", result.stdout + result.stderr)
        if match and tuple(int(x or 0) for x in match.groups()) >= (7, 8, 0):
            return installed
        print("System ProGuard is too old for Java 25; provisioning ProGuard " + PROGUARD_VERSION, flush=True)
    url = (f"https://github.com/Guardsquare/proguard/releases/download/"
           f"v{PROGUARD_VERSION}/proguard-{PROGUARD_VERSION}.zip")
    destination = PROGUARD_DIR.parent
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as temp:
        archive_path = Path(temp) / "proguard.zip"
        print(f"Downloading ProGuard {PROGUARD_VERSION} from {url}", flush=True)
        urllib.request.urlretrieve(url, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                extracted = (destination / member.filename).resolve()
                if not extracted.is_relative_to(destination.resolve()):
                    raise RuntimeError(f"Unsafe ProGuard ZIP entry: {member.filename}")
            archive.extractall(destination)
    if not local.is_file():
        raise RuntimeError(f"ProGuard distribution missing {local}; check {url}")
    local.chmod(local.stat().st_mode | 0o111)
    return str(local)


def proguard():
    """Conservative shrinking of experimental Rust-generated JVM bytecode."""
    executable = proguard_executable()
    jmods = sorted((java_home() / "jmods").glob("*.jmod"))
    if not jmods:
        raise RuntimeError("No JDK jmods found")
    output_dir = DIST / "proguard"
    for name in ("xcat", "cptx"):
        source = DIST / "standalone" / f"{name}.jar"
        output = output_dir / f"{name}.jar"
        if not source.is_file():
            raise FileNotFoundError(source)
        # Generated Rust classes include references that ProGuard cannot resolve
        # statically (e.g. drop glue, f128 symbols, MethodHandle signatures).
        # Keep their entire namespace intact; shrink only other classes.
        # -ignorewarnings is deliberately explicit: the upstream backend's
        # unresolved references must not be mistaken for a clean analysis.
        rules = [
            f"-injars {source}",
            f"-outjars {output}",
            *(f"-libraryjars {jmod}(!**.jar;!module-info.class)" for jmod in jmods),
            "-dontnote",
            "-ignorewarnings",
            "-dontoptimize",
            "-dontobfuscate",
            "-keepattributes *Annotation*,Signature,InnerClasses,EnclosingMethod",
            f"-keep class {name}.{name} {{ public static void main(java.lang.String[]); }}",
            "-keep class org.rustlang.** { *; }",
        ]
        output_dir.mkdir(parents=True, exist_ok=True)
        # Never leave a stale or partially generated artifact on failure.
        output.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="proguard-", dir=TARGET_DIR) as tmp:
            config = Path(tmp) / "proguard.pro"
            config.write_text("\n".join(rules) + "\n")
            run(executable, f"@{config}")
        with zipfile.ZipFile(output) as jar:
            manifest = jar.read("META-INF/MANIFEST.MF").decode("utf-8")
            if f"Main-Class: {name}.{name}" not in manifest.replace("\\r\\n", "\\n"):
                raise RuntimeError(f"ProGuard output lacks Main-Class for {name}")
        print(f"{name}: {source.stat().st_size / 1048576:.2f} MiB -> {output.stat().st_size / 1048576:.2f} MiB")


def test_proguard():
    """Compare observable, clipboard-free CLI behavior against standalone JARs."""
    cases = {
        "xcat": [(["--help"], 0), (["--definitely-invalid-option"], None)],
        "cptx": [(["--help"], 0), (["--definitely-invalid-option"], None)],
    }
    for name, scenarios in cases.items():
        baseline = DIST / "standalone" / f"{name}.jar"
        optimized = DIST / "proguard" / f"{name}.jar"
        for arguments, expected_status in scenarios:
            def invoke(path):
                return subprocess.run(
                    ["java", "-jar", str(path), *arguments],
                    cwd=ROOT, capture_output=True, timeout=45,
                )
            original = invoke(baseline)
            result = invoke(optimized)
            if expected_status is not None and original.returncode != expected_status:
                raise RuntimeError(
                    f"Baseline {name} {arguments} failed (exit {original.returncode}): "
                    + original.stderr.decode(errors="replace")
                )
            if (original.returncode, original.stdout, original.stderr) != (
                result.returncode, result.stdout, result.stderr
            ):
                raise RuntimeError(
                    f"ProGuard changed {name} {arguments} behavior: "
                    f"baseline exit={original.returncode}, optimized exit={result.returncode}; "
                    f"baseline stdout={original.stdout[:300]!r}, optimized stdout={result.stdout[:300]!r}; "
                    f"baseline stderr={original.stderr[:300]!r}, optimized stderr={result.stderr[:300]!r}"
                )
            print(f"PASS {name} {' '.join(arguments)}: matches standalone (exit {result.returncode})")



def report_optimized():
    """Print final optimized artifacts and their sizes."""
    print("Optimized JVM JARs:")
    for name in ("xcat", "cptx"):
        path = DIST / "proguard" / f"{name}.jar"
        if not path.is_file():
            raise FileNotFoundError(f"Missing optimized JAR: {path}")
        print(f"  {path.relative_to(TARGET_DIR)}: {path.stat().st_size / 1048576:.2f} MiB")


def artifacts():
    for folder, suffix in ((TARGET_DIR / "jvm-package", ".jar"), (TARGET_DIR / "jvm-unknown-jvm", ".class")):
        if folder.is_dir():
            for path in sorted(folder.rglob(f"*{suffix}")):
                print(path)
        else:
            print(f"No {suffix} artifacts in {folder}")


def main():
    actions = {
        "target-dir": target_dir, "setup": setup, "build": build,
        "package": package, "smoke": smoke, "distributions": distributions,
        "test-distributions": test_distributions, "proguard": proguard,
        "test-proguard": test_proguard, "report-optimized": report_optimized, "artifacts": artifacts,
    }
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=actions)
    args = parser.parse_args()
    actions[args.action]()


if __name__ == "__main__":
    main()
