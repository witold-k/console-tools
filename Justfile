cargo_target_dir := `cargo metadata --no-deps --format-version 1 | python3 -c 'import json, sys; print(json.load(sys.stdin)["target_directory"])'`

# Default pinned-Nightly native debug build.
default: build

# Clear tmux and terminal.
clear:
    python3 scripts/maintenance.py clear

# Pull current branch using build helper.
pull:
    python3 scripts/build.py github_pull

# Pinned-Nightly native debug build and tests.
build:
    python3 scripts/build.py build-debug

# Pinned-Nightly native immediate-abort release build and tests.
build-release:
    python3 scripts/build.py build-release

# Pull and pinned-Nightly debug build.
gbuild: pull build

# Pull, build/test/install native release binaries, then build, ProGuard-optimize,
# regression-test and publish both no_std JVM distributions.
# Do not run promote_nightly_artifacts.py here: it overwrites the small JARs.
# Print the four deliverable sizes only after every build and test succeeds.
rbuild: pull build-release install jvm-no-std-proguard-publish
    python3 -c 'from pathlib import Path; t=Path("{{cargo_target_dir}}"); products=[("xcat (native)",t/"release/xcat"),("cptx (native)",t/"release/cptx"),("xcat (JVM)",t/"wasm2jar-probe/xcat-standalone.jar"),("cptx (JVM)",t/"wasm2jar-probe/cptx-standalone.jar")]; print(); print("Final product sizes:"); [(print(f"  {name:<16} {p.stat().st_size:>12,} bytes  ({p.stat().st_size/1024:>8.1f} KiB)  {p}")) for name,p in products]'

# Show the 30 largest functions in both native release binaries.
# Requires cargo-bloat (cargo install cargo-bloat).
bloat:
    cargo bloat --release --bin xcat -n 30
    cargo bloat --release --bin cptx -n 30

# Experimental native release build with a locally rebuilt Rust standard library.
# Requires nightly and rust-src. Does not install or replace rbuild artifacts.
native-nightly:
    cargo +nightly -Z build-std=std,panic_abort build --release -p console-tools --bin xcat --bin cptx
    python3 -c 'from pathlib import Path; t=Path("{{cargo_target_dir}}")/"release"; [(print(f"{name}: {(t/name).stat().st_size:,} bytes")) for name in ("xcat","cptx")]'

# Experimental immediate-abort panic strategy, scoped to Cargo's release profile.
# Unlike global RUSTFLAGS, this avoids forcing the strategy onto host build scripts.
native-nightly-immediate-abort:
    cargo +nightly -Z panic-immediate-abort -Z build-std=std,panic_abort --config 'profile.release.panic="immediate-abort"' build --release -p console-tools --bin xcat --bin cptx
    python3 -c 'from pathlib import Path; t=Path("{{cargo_target_dir}}")/"release"; [(print(f"{name}: {(t/name).stat().st_size:,} bytes")) for name in ("xcat","cptx")]'

# Run stable tests, rebuild the tiny native binaries, then exercise their real CLI entrypoints.
# xcat's scan copies files to the system clipboard; cptx's tmux capture remains manual.
native-nightly-test: native-nightly-immediate-abort
    cargo test -p console-tools
    python3 -c 'import subprocess; from pathlib import Path; t=Path("{{cargo_target_dir}}")/"release"; cases=[("xcat",["--help"],0,"Usage:"),("cptx",["--help"],0,"Usage:"),("xcat",["--definitely-invalid"],1,None),("cptx",["--definitely-invalid"],1,None)]; [(lambda p,name,args,code,needle: (print(f"{name} {args}: exit {p.returncode}"), (_ for _ in ()).throw(RuntimeError(f"{name} {args}: unexpected result: {p.stdout!r} {p.stderr!r}")) if (p.returncode==0)!=(code==0) or (needle and needle not in p.stdout) else None))(subprocess.run([str(t/name),*args],capture_output=True,text=True),name,args,code,needle) for name,args,code,needle in cases]; print("Native Nightly CLI smoke tests passed")'

# Install missing WASI/JVM build tools (Debian/Ubuntu; prompts for sudo if needed).
install-wasm-tools:
    python3 scripts/install_wasm_tools.py

# Prepare JVM backend directory.
jvm-target-dir:
    python3 scripts/jvm.py target-dir

# Install and initialize cargo-jvm.
jvm-setup:
    python3 scripts/jvm.py setup

# Build release JVM JARs, optimize with ProGuard, smoke-test, and print final JAR sizes.
build-jvm: jvm-test-proguard
    python3 scripts/jvm.py report-optimized

# Package original JVM JARs.
jvm-package:
    python3 scripts/jvm.py package

# Build thin and standalone JARs.
jvm-distributions: jvm-package
    python3 scripts/jvm.py distributions

# Smoke-test both JVM distribution layouts.
jvm-test-distributions: jvm-distributions
    python3 scripts/jvm.py test-distributions

# Optimize standalone JARs with ProGuard.
jvm-proguard: jvm-distributions
    python3 scripts/jvm.py proguard

# Compare ProGuard JAR behavior against standalone JARs.
jvm-test-proguard: jvm-proguard
    python3 scripts/jvm.py test-proguard

# Run xcat help through cargo-jvm.
jvm-smoke:
    python3 scripts/jvm.py smoke

# List JVM build artifacts.
jvm-artifacts:
    python3 scripts/jvm.py artifacts


# WASI: a single std-only Rust codebase, no Cargo dependencies or JVM libraries.
wasm-setup:
    python3 scripts/wasm.py setup

# Build and test pinned-Nightly WASI modules and JVM artifacts.
build-wasm: wasm-nightly-immediate-abort
    python3 scripts/promote_nightly_artifacts.py

# Build a separate small Wasmi + WASI runner (requires crates.io on first build).
build-wasmi:
    cargo build --manifest-path experiments/wasmi-runner/Cargo.toml --release

# Test with the embedded Wasmi runner instead of an installed Wasmtime CLI.
test-wasmi: build-wasmi build-wasm
    CONSOLE_TOOLS_WASM_RUNNER="{{cargo_target_dir}}/release/console-tools-wasmi-runner" python3 scripts/wasm.py test

# Run real WASI smoke tests for scanning, tmux stdin, and task reporting.
test-wasm: build-wasm
    python3 scripts/wasm.py test

# Run WASM xcat/cptx through a stdlib-only OS clipboard/process bridge.
wasm-xcat:
    cargo run --offline --release --bin wasm-host -- xcat

wasm-cptx:
    cargo run --offline --release --bin wasm-host -- cptx

# Install coverage tools.
cover-setup:
    python3 scripts/maintenance.py cover-setup

# Generate HTML coverage.
cover:
    python3 scripts/maintenance.py cover

# Generate LCOV coverage.
cover-lcov:
    python3 scripts/maintenance.py cover-lcov

# Print coverage report.
cover-text:
    python3 scripts/maintenance.py cover-text

# Install native binaries.
install:
    python3 scripts/maintenance.py install

# Clean package artifacts and Cargo.lock.
clean:
    python3 scripts/maintenance.py clean

# Clean all Cargo artifacts.
clean-all:
    python3 scripts/maintenance.py clean-all

# List rustup targets.
targetlist:
    python3 scripts/maintenance.py targetlist

# Inspect installed wasm2jar CLI and WASI module before attempting JVM translation.
wasm2jar-probe:
    python3 scripts/wasm2jar_probe.py probe

# Convert the existing cptx WASI module to JVM bytecode and measure the JAR.
# This does not imply WASI host functions are linked or executable.
wasm2jar-cptx: build-wasm

# Default cptx JVM: production Rust std/WASI module and Rust-owned clipboard policy.
# Package the translated module and validate desktop tmux/clipboard integration.
wasm2jar-test-cptx: build-wasm

# Compatibility alias for the previous explicit std recipe.
wasm2jar-test-cptx-std: wasm2jar-test-cptx

# Convert xcat WASI to JVM bytecode with a small Java WASI filesystem host.
wasm2jar-xcat: build-wasm

# Package xcat and test --help, filesystem scanning, config and clipboard.
wasm2jar-test-xcat: build-wasm

# Run the pinned-Nightly JVM integration tests and promote verified artifacts.
wasm2jar-test-all: build-wasm

# Install the pinned official Rust Nightly and its WASI build components.
# Explicit setup only: the build recipes never install or update toolchains.
# wasm-opt (Binaryen), wasm2jar, and a JDK are separate system dependencies.
wasm-nightly-setup:
    rustup toolchain install nightly-2026-11-21 --profile minimal --component rust-src
    rustup target add wasm32-wasip1 --toolchain nightly-2026-11-21
    rustc +nightly-2026-11-21 -vV

# Compare isolated pinned-Nightly WASI/JVM artifacts with production baselines.
# Run wasm-nightly-setup once; requires wasm-opt, wasm2jar and Java tools.
# Runs both Java end-to-end suites; does not replace production artifacts.
wasm-nightly-immediate-abort:
    python3 scripts/wasm_nightly_immediate_abort.py

# Control: same nightly build-std/WASI/JVM pipeline, but conventional panic=abort.
# Compare with wasm-nightly-immediate-abort without overwriting either output.
wasm-nightly-abort:
    python3 scripts/wasm_nightly_immediate_abort.py --panic abort

# Inspect per-section WASM and per-class compressed/uncompressed JAR sizes.
wasm-size-report:
    python3 scripts/wasm_size_analysis.py

# Compare Binaryen optimization levels without replacing production WASM.
# Candidate modules require separate JVM end-to-end validation before adoption.
wasm-size-experiments:
    python3 scripts/wasm_size_analysis.py --experiment

# Inspect JVM opcodes and largest translated methods without modifying artifacts.
wasm-bytecode-report:
    python3 scripts/wasm_bytecode_analysis.py

# Count generated ByteBuffer memory-access patterns in wasm2jar output.
wasm-memory-patterns:
    python3 scripts/wasm_memory_patterns.py

# Measure cptx's Rust/WASI size floor with isolated std-only feature fixtures.
cptx-size-floor:
    python3 scripts/cptx_size_floor.py

# Compare minimal Rust/WASI fixtures after wasm2jar translation (temporary artifacts only).
wasm2jar-size-floor:
    python3 scripts/wasm2jar_size_floor.py

# Compare rustc size/codegen options on minimal WASI fixtures and translated JVM JARs.
wasi-runtime-floor:
    python3 scripts/wasi_runtime_floor.py

# Compare isolated no_std WASI entrypoints against std, including wasm2jar sizes.
wasi-no-std-floor:
    python3 scripts/wasi_no_std_floor.py

# Execute isolated no_std WASI streaming module through the existing JVM host.
wasi-no-std-jvm-test:
    python3 scripts/wasi_no_std_jvm_test.py

# Exercise isolated no_std CLI and UTF-8 validation on the JVM.
wasi-no-std-cptx-test:
    python3 scripts/wasi_no_std_jvm_test.py no_std_cptx

# Compare JVM behavior when wasm-opt is bypassed.
wasi-no-std-cptx-test-raw:
    python3 scripts/wasi_no_std_jvm_test.py no_std_cptx --raw-wasm

# Compare native WASI behavior with JVM for the same unoptimized WASM.
wasi-no-std-cptx-compare:
    python3 scripts/wasi_no_std_jvm_test.py no_std_cptx --raw-wasm --compare-native

# Build and regression-test the no_std cptx JVM distribution at its legacy experiment path.
# The default cptx JVM recipe is now wasm2jar-test-cptx.
wasi-no-std-cptx-package:
    python3 scripts/wasi_no_std_jvm_test.py no_std_cptx --output-jar "{{cargo_target_dir}}/wasm2jar-probe/cptx-no-std-standalone.jar"

# Compare all ProGuard modes against the preserved unoptimized baseline.
cptx-proguard-experiment: wasm2jar-test-cptx
    python3 scripts/cptx_proguard_experiment.py --baseline "{{cargo_target_dir}}/wasm2jar-probe/cptx-standalone-unoptimized.jar"

# Compare shrink, optimize, and aggressive with the production relaxed keep rules.
# Uses preserved baseline; never replaces the default optimized JAR.
cptx-proguard-relaxed-keep: wasm2jar-test-cptx
    python3 scripts/cptx_proguard_experiment.py --baseline "{{cargo_target_dir}}/wasm2jar-probe/cptx-standalone-unoptimized.jar" --relaxed-keep

# Diagnostic only: compare independently built aggressive JAR hashes.
# Nondeterministic class metadata is not a release gate.
cptx-jvm-reproducibility:
    python3 scripts/cptx_jvm_reproducibility.py

# Experimental no_std JVM cptx: compile the existing no_std WASI implementation,
# package it as a standalone JAR and run CLI, UTF-8, WASI and desktop clipboard tests.
# Keeps native binaries and the regular JVM distribution untouched.
jvm-no-std-cptx:
    python3 scripts/wasi_no_std_jvm_test.py no_std_cptx --output-jar "{{cargo_target_dir}}/wasm2jar-probe/cptx-no-std-standalone.jar"

# Compare the functional no_std cptx prototype against the current JVM JAR.
jvm-no-std-size-compare: jvm-no-std-cptx
    python3 -c 'from pathlib import Path; t=Path("{{cargo_target_dir}}")/"wasm2jar-probe"; files=[t/"cptx-standalone.jar",t/"cptx-no-std-standalone.jar"]; [(print(f"{p.name}: {p.stat().st_size:,} bytes" if p.exists() else f"{p.name}: not built")) for p in files]'

# Compile the experimental no_std xcat scanner to WASI without Rust std.
# Not a replacement for the regular xcat JAR: custom config and task reports
# are still missing. Kept separate from rbuild and published artifacts.
jvm-no-std-xcat-prototype:
    mkdir -p "{{cargo_target_dir}}/no-std-xcat"
    rustc --edition=2024 --target wasm32-wasip1 --crate-type=cdylib experiments/no_std_xcat.rs -o "{{cargo_target_dir}}/no-std-xcat/xcat.wasm" -C opt-level=z -C lto=fat -C codegen-units=1 -C panic=abort -C strip=symbols -C link-arg=--export=_start
    wasm-opt -Oz --enable-bulk-memory --strip-debug --strip-producers "{{cargo_target_dir}}/no-std-xcat/xcat.wasm" -o "{{cargo_target_dir}}/no-std-xcat/xcat.opt.wasm"
    python3 -c 'from pathlib import Path; p=Path("{{cargo_target_dir}}/no-std-xcat/xcat.opt.wasm"); print(f"Experimental no_std xcat WASM: {p.stat().st_size:,} bytes")'

# Full JVM integration gate for the experimental no_std xcat implementation.
# Deliberately isolated; only publish after all existing xcat tests pass.
jvm-no-std-xcat-test: jvm-no-std-xcat-prototype
    mkdir -p "{{cargo_target_dir}}/no-std-xcat"
    cd "{{cargo_target_dir}}/no-std-xcat" && wasm2jar --output-class console/tools/Xcat --jar "{{cargo_target_dir}}/no-std-xcat/xcat-translated.jar" "{{cargo_target_dir}}/no-std-xcat/xcat.opt.wasm"
    python3 scripts/wasm2jar_run.py --tool xcat --input-jar "{{cargo_target_dir}}/no-std-xcat/xcat-translated.jar" --output-jar "{{cargo_target_dir}}/no-std-xcat/xcat-no-std-standalone.jar"
    python3 -c 'from pathlib import Path; p=Path("{{cargo_target_dir}}/no-std-xcat/xcat-no-std-standalone.jar"); print(f"Experimental no_std xcat JAR: {p.stat().st_size:,} bytes")'

# Release gate: the experimental no_std xcat must pass custom JSON filter
# regression tests before it may replace the default JVM artifact.
# ProGuard is not part of jvm-no-std-xcat-test; its size is pre-ProGuard.
jvm-no-std-xcat-release-gate: jvm-no-std-xcat-test
    @echo "no_std xcat functional regression gate passed"

# Build both no_std JVM candidates, optimize each with ProGuard and rerun
# the full existing JVM end-to-end suite on the optimized JARs.
# Does not replace the default artifacts.
jvm-no-std-proguard: jvm-no-std-xcat-release-gate jvm-no-std-cptx
    python3 scripts/no_std_proguard.py

# Publish both verified ProGuard JARs as the standard wasm2jar-probe
# distributions. No publishing occurs if either test fails.
jvm-no-std-proguard-publish: jvm-no-std-xcat-release-gate jvm-no-std-cptx
    python3 scripts/no_std_proguard.py --publish

# Compare ProGuard keep policies for BOTH no_std JVM tools without publishing.
# Every candidate runs JVM integration tests; cptx also runs WASI fault/short-write gates.
jvm-no-std-proguard-compare: jvm-no-std-xcat-release-gate jvm-no-std-cptx
    python3 scripts/no_std_proguard.py --keep-mode conservative --deep-verify
    python3 scripts/no_std_proguard.py --keep-mode relaxed --deep-verify
    python3 scripts/no_std_proguard.py --keep-mode minimal --deep-verify
    python3 -c 'import glob,os; paths=glob.glob("{{cargo_target_dir}}/no-std-xcat/*-proguard-*.jar")+glob.glob("{{cargo_target_dir}}/wasm2jar-probe/*-proguard-*.jar"); print("ProGuard keep comparison (bytes):"); [(print(os.path.basename(p),os.path.getsize(p))) for p in sorted(paths)]'
