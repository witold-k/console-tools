cargo_target_dir := `cargo metadata --no-deps --format-version 1 | python3 -c 'import json, sys; print(json.load(sys.stdin)["target_directory"])'`

# Default native debug build.
default: build

# Clear tmux and terminal.
clear:
    python3 scripts/maintenance.py clear

# Pull current branch using build helper.
pull:
    python3 scripts/build.py github_pull

# Native debug build and tests.
build:
    python3 scripts/build.py build-debug

# Native release build and tests.
build-release:
    python3 scripts/build.py build-release

# Pull and native debug build.
gbuild: pull build

# Pull, native release build and install (JVM is an independent experimental target).
rbuild: pull build-release install

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

# Build native tests and xcat/cptx WASI modules offline.
build-wasm:
    python3 scripts/wasm.py build

# Build a separate small Wasmi + WASI runner (requires crates.io on first build).
build-wasmi:
    cargo build --manifest-path experiments/wasmi-runner/Cargo.toml --release

# Test with the embedded Wasmi runner instead of an installed Wasmtime CLI.
test-wasmi: build-wasmi build-wasm
    CONSOLE_TOOLS_WASM_RUNNER="{{justfile_directory()}}/experiments/wasmi-runner/target/release/console-tools-wasmi-runner" python3 scripts/wasm.py test

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
    python3 scripts/wasm2jar_probe.py try-convert --tool cptx -- --output-class console/tools/Cptx --jar {out} {wasm}

# Package wasm2jar cptx with a minimal Java WASI host and smoke-test it.
# The translated Rust logic remains unchanged; no external Java dependencies.
wasm2jar-test-cptx: wasm2jar-cptx
    python3 scripts/wasm2jar_run.py

# Convert xcat WASI to JVM bytecode with a small Java WASI filesystem host.
wasm2jar-xcat: build-wasm
    python3 scripts/wasm2jar_probe.py try-convert --tool xcat -- --output-class console/tools/Xcat --jar {out} {wasm}

# Package xcat and test --help, filesystem scanning, config and clipboard.
wasm2jar-test-xcat: wasm2jar-xcat
    python3 scripts/wasm2jar_run.py --tool xcat

# Run the available JVM translation smoke tests for both tools.
wasm2jar-test-all: wasm2jar-test-cptx wasm2jar-test-xcat

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
