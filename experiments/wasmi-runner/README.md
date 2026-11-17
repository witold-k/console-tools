# Experimental embedded WASM interpreter

This is an independent Rust package so the existing std-only native and WASI
programs retain **zero Cargo dependencies**. It embeds Wasmi + WASI Preview 1
and needs **no external Wasmtime executable** at runtime.

Build (first time requires crates.io access):

```sh
cargo build --manifest-path experiments/wasmi-runner/Cargo.toml --release
python3 scripts/wasm.py build
CONSOLE_TOOLS_WASM_RUNNER="$PWD/experiments/wasmi-runner/target/release/console-tools-wasmi-runner" \
  python3 scripts/wasm.py test
```

The standalone runner accepts `run --dir HOST::GUEST module.wasm [args]`
(the subset of Wasmtime CLI used by console-tools). For the native bridge:

```sh
CONSOLE_TOOLS_WASM_RUNNER="$PWD/experiments/wasmi-runner/target/release/console-tools-wasmi-runner" \
  "$(cargo metadata --no-deps --format-version 1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')/release/wasm-host" cptx --help
```

Measure the total distribution size: runner + native wasm-host + both .wasm
modules. Compare with the two native binaries. The interpreter's speed,
filesystem behavior and security must be tested before adopting it. The
wasmi_wasi dependency currently brings a general-purpose WASI implementation;
the 18-import subset is a future size optimization, not implemented here.
