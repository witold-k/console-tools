# user_name        := env("USER")
# current_location := justfile()
current_dir      := justfile_directory()
module_name      := file_name(current_dir)
target_dir       := `cargo metadata --no-deps --format-version=1 | jq -r '.target_directory'`

# Default target: native debug build.
default: build

# Clear tmux scrollback (when available) and the terminal display.
clear:
    tmux clear-history || true
    clear

# Pull project updates using build.py (github_pull).
pull:
    python3 build.py github_pull

# Build native debug binaries through build.py.
build:
    python3 build.py build-debug

# Build native release binaries through build.py.
build-release:
    python3 build.py build-release

# Pull updates, then build native debug binaries.
gbuild: pull build

# Pull, build native release binaries, then install (modifies local installation).
rbuild: pull build-release install

# Prepare the backend-local target/release directory needed by upstream tooling.
jvm-target-dir:
    # Upstream build.py writes metadata to its local target/release even with a global Cargo target-dir.
    mkdir -p "${XDG_DATA_HOME:-$HOME/.local/share}/cargo-jvm/rustc_codegen_jvm/target/release"

# Install cargo-jvm, set up the experimental JVM backend, and show diagnostics.
jvm-setup: jvm-target-dir
    cargo install cargo-jvm
    CARGO_TARGET_DIR=target cargo jvm setup
    CARGO_TARGET_DIR=target cargo jvm doctor

# Compile xcat and cptx for the JVM in debug mode.
build-jvm: jvm-target-dir
    CARGO_TARGET_DIR=target RUSTFLAGS="-C panic=abort" cargo jvm build --bin xcat
    CARGO_TARGET_DIR=target RUSTFLAGS="-C panic=abort" cargo jvm build --bin cptx

# Produce original release JARs under target/jvm-package/release/.
jvm-package: jvm-target-dir
    CARGO_TARGET_DIR=target RUSTFLAGS="-C panic=abort" cargo jvm package --release --bin xcat
    CARGO_TARGET_DIR=target RUSTFLAGS="-C panic=abort" cargo jvm package --release --bin cptx

# Build both distributable layouts from the original cargo-jvm package artifacts.
# Thin: application JAR + adjacent runtime JAR (Manifest Class-Path).
# Standalone: application and runtime classes merged into one executable JAR.
# Produce thin (JAR + runtime) and standalone (merged runtime) distributions for both binaries.
jvm-distributions: jvm-package
    #!/usr/bin/env bash
    set -euo pipefail
    runtime="${XDG_DATA_HOME:-$HOME/.local/share}/cargo-jvm/rustc_codegen_jvm/runtime/build/libs/runtime-0.1.0.jar"
    test -f "$runtime" || { echo "Missing JVM runtime: $runtime" >&2; exit 1; }
    mkdir -p target/jvm-dist/thin target/jvm-dist/standalone
    cp "$runtime" target/jvm-dist/thin/runtime-0.1.0.jar
    for bin in xcat cptx; do
        source_jar="target/jvm-package/release/$bin.jar"
        test -f "$source_jar" || { echo "Missing JVM package: $source_jar" >&2; exit 1; }
        cp "$source_jar" "target/jvm-dist/thin/$bin.jar"
        manifest_tmp="$(mktemp)"
        printf 'Class-Path: runtime-0.1.0.jar\n' > "$manifest_tmp"
        jar ufm "target/jvm-dist/thin/$bin.jar" "$manifest_tmp"
        rm -f "$manifest_tmp"
        work="$(mktemp -d)"
        (cd "$work" && jar xf "$runtime" && jar xf "$OLDPWD/$source_jar")
        # Reuse the application manifest (including Main-Class); discard signatures
        # invalidated by merging archives.
        find "$work/META-INF" -maxdepth 1 -type f \( -name '*.SF' -o -name '*.RSA' -o -name '*.DSA' -o -name '*.EC' \) -delete
        test -f "$work/META-INF/MANIFEST.MF" || { echo "Missing manifest in $source_jar" >&2; rm -rf "$work"; exit 1; }
        jar cfm "target/jvm-dist/standalone/$bin.jar" "$work/META-INF/MANIFEST.MF" -C "$work" .
        rm -rf "$work"
    done
    echo 'Thin JARs: target/jvm-dist/thin/ (keep runtime-0.1.0.jar beside them)'
    echo 'Standalone JARs: target/jvm-dist/standalone/'

# Rebuild both distribution layouts and smoke-test all four JARs using --help.
jvm-test-distributions: jvm-distributions
    java -jar target/jvm-dist/thin/xcat.jar --help
    java -jar target/jvm-dist/thin/cptx.jar --help
    java -jar target/jvm-dist/standalone/xcat.jar --help
    java -jar target/jvm-dist/standalone/cptx.jar --help

# Run xcat --help through cargo-jvm (experimental smoke test).
jvm-smoke: jvm-target-dir
    CARGO_TARGET_DIR=target RUSTFLAGS="-C panic=abort" cargo jvm run --bin xcat -- --help

# Install cargo-llvm-cov and the llvm-tools-preview component.
cover-setup:
    cargo install cargo-llvm-cov
    rustup component add llvm-tools-preview

# Generate HTML coverage for all workspace targets/features.
cover:
	cargo llvm-cov --all-features --workspace --html

# Generate LCOV coverage at the Cargo target directory.
cover-lcov:
	cargo llvm-cov --all-features --workspace --lcov --output-path {{target_dir}}/coverage/lcov.info

# Print coverage summary in the terminal.
cover-text:
	cargo llvm-cov --all-features --workspace

# Build, lint and install the native release binaries via cargo install.
install:
	cargo build --release
	cargo clippy --release
	cargo install --path .

# JVM backend is experimental: inspect the emitted classes and runtime before launch.
# cargo-jvm must be installed and configured separately.
# List original JVM package JARs and emitted .class files, if present.
jvm-artifacts:
    if [ -d target/jvm-package ]; then find target/jvm-package -type f -name '*.jar' -print; else echo 'No packaged JVM JARs yet (run just jvm-package)'; fi
    if [ -d target/jvm-unknown-jvm ]; then find target/jvm-unknown-jvm -type f -name '*.class' -print; else echo 'No JVM class directory yet'; fi

# Remove Cargo.lock and clean this package's Cargo artifacts.
clean:
	rm Cargo.lock
	@cargo clean -p {{module_name}}

# Clean all Cargo build artifacts for this workspace.
clean-all:
	@cargo clean

# List Rust compilation targets available through rustup.
targetlist:
    rustup target list

# Cross-compile for aarch64-unknown-linux-gnu (requires target/toolchain support).
rpi:
    cargo build --target aarch64-unknown-linux-gnu


