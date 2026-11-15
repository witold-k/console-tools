# user_name        := env("USER")
# current_location := justfile()
current_dir      := justfile_directory()
module_name      := file_name(current_dir)
target_dir       := `cargo metadata --no-deps --format-version=1 | jq -r '.target_directory'`

default: build

clear:
    tmux clear-history || true
    clear

pull:
    python3 build.py github_pull

build:
    python3 build.py build-debug

build-release:
    python3 build.py build-release

gbuild: pull build

rbuild: pull build-release install

build-jvm:
    RUSTFLAGS="-C panic=unwind" cargo jvm build --bin aifix --no-default-features

cover-setup:
    cargo install cargo-llvm-cov
    rustup component add llvm-tools-preview

cover:
	cargo llvm-cov --all-features --workspace --html

cover-lcov:
	cargo llvm-cov --all-features --workspace --lcov --output-path {{target_dir}}/coverage/lcov.info

cover-text:
	cargo llvm-cov --all-features --workspace

install:
	cargo build --release
	cargo clippy --release
	cargo install --path .

test-jvm:
    java -cp $HOME/.local/share/cargo-jvm/rustc_codegen_jvm/runtime/build/libs/runtime-0.1.0.jar:{{target_dir}}/jvm-unknown-jvm/debug/collect_to_md.jar xcat.xcat

clean:
	rm Cargo.lock
	@cargo clean -p {{module_name}}

clean-all:
	@cargo clean

targetlist:
    rustup target list

rpi:
    cargo build --target aarch64-unknown-linux-gnu


