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

## Integration checkpoint (new experiment branch)

The `wasi-no-std-cptx-test` recipe now also runs the **existing production
JVM desktop integration test** against the freshly built ~15 KB no_std JAR,
using mocked `tmux` and `wl-copy`. This tests actual
`--desktop` capture-to-clipboard behavior for the same payload sizes
(28 to 336,000 bytes) as the production JAR. This is **additional
validation**, not a replacement of the production JAR.

Run `just wasi-no-std-cptx-test`; expect
`PASS no_std desktop integration (tmux -> WASM -> clipboard)`.
The test must pass on the target machine before claiming functional parity.
The experiment still has different CLI help typography and non-desktop
streaming error behavior. The Java desktop launcher buffers output and
only invokes the clipboard after successful WASM completion, so the
documented streaming prefix does not itself imply partial clipboard writes.
Further error-path tests are required before switching the build default.

## Optional packaged artifact and failure regression tests

Run `just wasi-no-std-cptx-package` to build and validate a separate
`target/wasm2jar-probe/cptx-no-std-standalone.jar` (using the workspace's
actual Cargo target directory). The existing `cptx-standalone.jar` and
default recipes are untouched. This is an **opt-in experimental artifact**,
not an installation or a default replacement.

The test now also injects these desktop failure paths through executable
mocks: nonzero tmux exit (clipboard must not be called), invalid UTF-8
late in tmux output (clipboard must not be called), and nonzero clipboard
exit (JVM must fail). The separate stdin/stdout fixture still emits a
valid prefix on late UTF-8 failure, while the desktop launcher buffers it.
The Java host's read/write I/O error injection and full native cptx
error-message parity remain open work. A successful local test run is
required; commits alone do not establish test success.

## CLI parity and missing executable regression

The no_std help text now uses the same UTF-8 em dash as the Rust CLI.
The JVM regression compares the **complete stdout bytes** for both help
options and the complete stderr bytes and exit code for invalid options.
It also checks that a missing `wl-copy` executable fails in desktop
mode without reporting a successful copy.

These tests must be run again after the fixture change. The host's
`fd_read`/`fd_write` injected error and partial-write paths are **not
yet covered**; the small variant is still opt-in and must not be treated
as fully equivalent merely because its help and desktop tests pass.

## Injected WASI host I/O errors

The optional JVM packaging test now compiles a temporary Java harness
against the translated classes, injects a throwing stdin stream and a
throwing stdout stream, and verifies nonzero WASI exit for both `fd_read`
and `fd_write`. The host now checks `PrintStream.checkError()` after
flush so Java's swallowed write exceptions become a WASI I/O error.
The harness is compiled **after** JAR packaging, so it is not bundled
in the distributed artifact.

This does not simulate a WASI `fd_write` call returning a positive
short count. That case remains untested; the Rust fixture's write loop
is designed to retry partial writes. Rerun
`just wasi-no-std-cptx-package` locally to validate these changes.

## Short successful WASI writes

The optional JVM suite now recompiles a **temporary test-only** launcher
whose `fd_write` reports at most seven bytes per call. It runs ASCII,
multibyte UTF-8, and large inputs through the original translated Rust
WASM module and verifies exact stdout byte equality. This exercises the
Rust retry loop when the host reports successful but partial writes.
The modified launcher is never packaged into the optional JAR.

The late-invalid-UTF-8 stdout difference is still present and documented;
the small variant remains optional until its semantics are resolved.

## Provisional JVM default (16 KiB buffer)

By explicit user decision, the no_std cptx module now uses a **16,384-byte**
input buffer and is the default for `just wasm2jar-test-cptx`, producing
`target/wasm2jar-probe/cptx-standalone.jar` in the Cargo workspace target
directory. The old std-based JVM path remains available as
`just wasm2jar-test-cptx-std`. The optional comparison recipe
`just wasi-no-std-cptx-package` remains available and writes its
separate `cptx-no-std-standalone.jar`.

This changes the **JVM cptx packaging recipe**, not the native `cptx`
binary, `xcat`, or the default `just build` recipe. The choice is
provisional pending a successful local regression run. Standalone
stdin/stdout mode still may emit a validated prefix on late invalid
UTF-8; the desktop clipboard path buffers before committing.
