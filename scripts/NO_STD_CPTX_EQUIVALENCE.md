# no_std cptx JVM experiment: equivalence boundary

This is an isolated size and ABI experiment, **not** a drop-in implementation of `cptx`.

## Actual production behavior

`src/bin/cptx.rs` parses zero arguments or `-h`/`--help`. On a normal
invocation it calls `tmux::capture()` and then `clipboard::copy(&text)`.
It does not implement a stdin-to-stdout copier. Capture, clipboard selection,
platform error handling, and full CLI/error wording must be evaluated before
claiming equivalence. The JVM launcher additionally has its own `--desktop`
mode and platform integration.

## What the small fixture demonstrates

`no_std_cptx` in `scripts/wasi_no_std_floor.py` exercises WASI Preview 1
argument imports, stdin reads, stdout writes, and an incremental UTF-8
validator through the existing Java launcher. Its size is a **lower bound
for a component**, not the expected size of a complete replacement.

The fixture writes validated chunks as it reads them. If a later chunk
contains invalid UTF-8, earlier chunks have already been written. The
production flow captures text before copying to the clipboard; this
partial-output behavior cannot be assumed equivalent. The test now asserts
this gap explicitly.

## Requirements before a production proposal

1. Characterize `tmux::capture()` and `clipboard::copy()` behavior and
   compare observable results, not just bytes passing through stdin/stdout.
2. Decide whether the Java host or WASI module owns capture, UTF-8 validation,
   clipboard output, and error reporting. Do not silently move responsibilities.
3. For atomic output, validate the entire captured text before committing it
   to the clipboard. A fixed-size streaming buffer cannot guarantee this for
   arbitrarily long input. Options include host-owned buffering or a
   temporary-file/two-pass design; both need error and resource-limit tests.
4. Inject short writes, read errors, write errors, and failures in clipboard
   and tmux integrations. The current host writes full chunks and does not
   simulate these conditions.
5. Compare CLI help text and exit status against the production binary,
   including the existing Unicode em dash in the help text.
6. Only after parity tests pass, compare final **standalone** JAR sizes.

## Commands

- `just wasi-no-std-cptx-test`: isolated JVM fixture and documented gap
- `just wasi-no-std-cptx-compare`: same raw WASM on native WASI and JVM
- `just wasi-no-std-floor`: isolated component size measurements

No production files are modified by these commands.

## Experiment inventory and cleanup (18 November 2026)

The repository retains the following **measurement tools**, even when their
underlying alternatives did not win, so future size work can be reproduced:

| Just recipe | Purpose |
| --- | --- |
| `wasm-size-report` / `wasm-size-experiments` | WASM sections and isolated Binaryen optimization comparisons |
| `wasm-bytecode-report` / `wasm-memory-patterns` | Inspect translated JVM instruction counts and memory-access patterns |
| `cptx-size-floor` | Rust std-library feature size contributions (non-additive) |
| `wasm2jar-size-floor` | Isolated Rust/WASI-to-JVM conversion sizes |
| `wasi-runtime-floor` | Rust optimization and LTO setting comparisons |
| `wasi-no-std-floor` | Rust std vs no_std WASI and translated JAR sizes |
| `wasi-no-std-jvm-test` / `wasi-no-std-cptx-test` | Runnable JVM regression fixtures |
| `wasi-no-std-cptx-test-raw` / `wasi-no-std-cptx-compare` | Raw-WASM and native-WASI diagnostic comparison |

**Removed as unsuccessful exploratory code:** the isolated upstream
`wasm2jar` memory-store compiler patch driver
(`scripts/wasm2jar_memory_experiment.py`) and its paired
baseline/candidate bytecode comparison
(`scripts/wasm2jar_compare_bytecode.py`). These were not part of the
working production pipeline; the generic bytecode and memory-pattern
measurement scripts remain. The old experiment can still be inspected
through Git history.

### Recorded measurements (historical; remeasure after toolchain changes)

| Configuration | Size | Interpretation |
| --- | ---: | --- |
| Previous standalone cptx JAR comparison baseline | 51,281 B | Historical reference from earlier runs |
| Full std-based wasm2jar cptx standalone JAR (17 Nov 2026) | 52,492 B | Recorded in README; build-dependent |
| no_std_cptx raw-WASM JVM standalone JAR | 14,756 B | Native WASI comparison run; passed |
| no_std_cptx optimized-WASM JVM standalone JAR | 14,750 B | 18 Nov 2026 JVM regression run; passed |
| no_std_cptx optimized WASM | 1,344 B | 18 Nov 2026 JVM regression run |

The no_std standalone size is **not** an apples-to-apples production
replacement size: the fixture does not capture tmux or copy to the
clipboard. It also emits a valid prefix before reporting late invalid
UTF-8; the regression test intentionally records this semantic gap.

The earlier failure to reject invalid UTF-8 was a **test fixture bug**:
Python literals accidentally contained literal backslash escape text.
Both Wasmtime and the JVM rejected actual invalid bytes after correction.
The working validator must not be classified as a failed experiment.

The Cargo warning about a package-local profile in a parent workspace
does not by itself invalidate these measurements, but builds should
record tool versions, flags and the workspace target path.

### Next optimization decision

Preserve the current working JVM implementation. First measure the
host/translated-module class contributions and verify tmux/clipboard
parity for any alternative. Do not replace the production path solely
because a smaller stdin/stdout fixture passes its isolated tests.
