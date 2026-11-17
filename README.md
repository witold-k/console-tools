# console-tools

Rust command-line utilities. **cptx** copies the entire current tmux pane
(including scrollback) to the desktop clipboard. **xcat** collects selected project files into a
single clipboard text, optionally runs a task, and copies the combined source
and task output back to the clipboard. It is based on
[buildscripts/lua/bin/xcat.lua](https://github.com/witold-k/buildscripts/blob/master/lua/bin/xcat.lua).

## Build

```sh
cargo build --release --bins
./target/release/xcat --help
./target/release/cptx --help
```

For clipboard access on Linux, install **wl-clipboard** (`wl-copy`) for
Wayland or **xclip** / **xsel** for X11. Windows uses PowerShell
`Set-Clipboard`. A working desktop clipboard is required for scans.

## Commands

### cptx

Run `cptx` from inside a tmux pane to copy its entire available scrollback
and visible contents to the desktop clipboard. This is a Rust replacement
for [buildscripts/bash/cptx](https://github.com/witold-k/buildscripts/blob/master/bash/cptx).
It runs `tmux capture-pane -p -S -`, checks its exit status, and uses the
same clipboard implementation as `xcat` (X11 CLIPBOARD or Wayland).
`cptx --help` displays usage. Running outside tmux reports an error.
The command does not print the captured pane or modify tmux history.

### xcat


| Command | Behavior |
| --- | --- |
| `xcat` | Scan the current working directory and copy selected files |
| `xcat -d /path/to/project` | Scan a specific directory |
| `xcat -r script.py -- --verbose` | Run only the task, auto-select launcher, copy its output |
| `xcat -e ./test.sh -- --verbose` | Scan, copy, execute a shell script, then copy scan + output |
| `xcat -d project -e Justfile -- build` | Scan `project`, run its Justfile's `build` recipe |
| `xcat -e Makefile -- test` | Scan and execute `make -f Makefile test` |
| `xcat -e script.ps1 -- -Verbose` | Execute a PowerShell script |
| `xcat -c custom.json -d src` | Use an explicit JSON configuration |
| `xcat -h` | Display detailed help |

`-d` / `--dir` selects the scan directory (default: current directory).
`-e` / `--execute` selects a task file, resolved relative to the scan
directory unless absolute. `-c` / `--config` overrides the config location.
Everything after `--` is passed unchanged to the task, without shell
interpolation. Arguments after `--` require `-e`.

## Standalone execution (`-r`)

`xcat -r <file> [-- args...]` runs a file without scanning the project.
The clipboard receives labeled stdout, stderr, and exit status. Unlike `-e`,
it does not copy source files first. An executable file is launched directly;
non-executable scripts use an interpreter selected from their extension
(`.sh`, `.bash`, `.py`, `.lua`, `.rb`, `.pl`, `.js`, `.mjs`, `.ps1`).
Justfile and Makefile are launched through `just` and `make`. Unknown
non-executable formats fail with an explicit error. Required interpreters
must be installed. This executes local code, so only run trusted files.

## Dependency-free WebAssembly (WASI Preview 1)

**Both CLI commands now build to WASI from the same Rust sources.** The
Cargo dependency list is empty. Filesystem scanning, JSON config handling,
UTF-8 validation and task-output formatting are implemented in Rust using
only the standard library. No Maven, Chicory, Wasmtime library crate,
ProGuard, JVM or pip package is bundled.

A WASI Preview 1 module **cannot launch child processes or access the host
clipboard directly**. A small native `wasm-host` executable uses the **same Rust modules** as the
native tools to capture tmux, launch tasks and write to wl-copy/xclip/xsel.
There is no second implementation of argument parsing, task dispatch or
clipboard handling. All configuration and scanning happen in WASM;
task-output formatting is shared by native Rust and WASM.

```text
One Rust codebase (no Cargo dependencies)
       |                       |
   native Rust             wasm32-wasip1
                               |
                    wasmtime CLI (runtime)
                               |
                 Rust std-only wasm-host bridge
                               |
                     tmux, tasks, clipboard
```

**Requirements:** stable Rust with the `wasm32-wasip1` target, a separately
installed `wasmtime` executable; Python 3.8+ is needed only for the existing
build helper scripts, not for running the host. Install tmux and a supported
clipboard program for actual clipboard use. Neither WASM modules nor the
native Rust host embeds a WASM runtime library or any third-party crate.

```sh
just wasm-setup                     # rustup target add wasm32-wasip1
just build-wasm                     # offline native tests + WASM build
just test-wasm                      # real WASI smoke tests
just wasm-xcat                      # scan current directory
just wasm-cptx                      # capture tmux pane
target/release/wasm-host xcat -d src
target/release/wasm-host xcat -e script.py -- --verbose
target/release/wasm-host xcat -r script.py -- --verbose
target/release/wasm-host cptx --help
cargo test --offline                # native Rust library and CLI tests
```

Artifacts are `target/wasm32-wasip1/release/xcat.wasm` and
`target/wasm32-wasip1/release/cptx.wasm`. Actual sizes are printed by the
build script; no size is claimed without running the build.

Direct `cptx.wasm` reads UTF-8 tmux capture from stdin and emits it on
stdout. Direct `xcat.wasm` reads preopened directories and emits the
formatted scan on stdout. For `-e` and `-r`, the host launches the task
and supplies temporary stdout/stderr files to WASM, where the existing
shared Rust formatter builds the report. Without the host, process-execution
flags are intentionally rejected on WASI.

**Security:** preopened directories grant the module filesystem access to
those paths; run trusted modules. `xcat -e/-r` executes local programs.
Native builds remain available without WASM. Windows host-bridge parity
has not been verified.

## WASM-to-JVM translation (wasm2jar, experimental)

This is a **separate JVM path** from the older `rustc_codegen_jvm`
experiment below. The original std-only Rust sources compile to
`wasm32-wasip1`, then `wasm2jar` 0.1.0 translates the WASM modules into
Java bytecode. A small Java WASI Preview 1 host supplies the imported
functions. **No second implementation of the application logic is needed.**

```text
              Rust xcat / cptx
                      |
                 wasm32-wasip1
                      |
                    wasm2jar
                      |
           generated JVM bytecode
                      |
           Java WASI Preview 1 host
                      |
                   JVM / OS
```

Requirements: the `wasm32-wasip1` Rust target, `wasm2jar` 0.1.0 on
`PATH` (or at `/opt/rust/bin/wasm2jar`), Python 3, and a JDK with
`java`, `javac`, `jar` and `javap`. The build uses `wasm-opt`
when available. The resulting standalone JARs require Java, not Wasmtime.
For clipboard integration, install the corresponding OS utility.

```sh
just wasm2jar-test-cptx   # translate, package and test cptx end-to-end
just wasm2jar-test-xcat   # translate, package and test filesystem scan and clipboard
just wasm2jar-test-all    # both paths, including native/WASI build checks
java -jar target/wasm2jar-probe/cptx-standalone.jar --help
java -jar target/wasm2jar-probe/xcat-standalone.jar --help
java -jar target/wasm2jar-probe/xcat-standalone.jar  # scan current directory
```

Generated standalone artifacts are
`target/wasm2jar-probe/cptx-standalone.jar` and
`target/wasm2jar-probe/xcat-standalone.jar`. In the November 2026 test
run they were approximately **52.5 KB** and **104.3 KB**, respectively;
actual sizes depend on the build. These are substantially smaller than
the older `rustc_codegen_jvm` JARs.

**Verified:** `cptx --help`, stdin/UTF-8 roundtrip, and a mocked
tmux → Rust WASM → `wl-copy` desktop path with scrollback through
336,000 bytes. `xcat --help` and a real JVM filesystem scan are also
verified, including UTF-8 file content, automatic configuration creation,
and clipboard output using a mocked `wl-copy`. A manual JVM scan of the
repository also succeeded. The Java host provides the WASI filesystem
bridge while Rust/WASM retains the scanning and filtering logic.

**Limitations:** JVM `xcat -e` and `-r` task execution are not supported;
WASI Preview 1 cannot launch processes. Absolute `-d` paths and arbitrary
custom config paths have not been verified through the Java preopens.
The JVM host currently supports Linux clipboard utilities; Windows parity
and a broader filesystem/security audit remain outstanding.

`scripts/wasm2jar_run.py` applies a narrow compatibility patch to
`wasm2jar` 0.1.0 generated helper bytecode: the inaccessible
`AssertionError(String)` constructor descriptor is replaced with the
public `AssertionError(Object)` descriptor after validating the class
constant pool. This is a **workaround for the converter**, not an
application-level change; revisit it when updating `wasm2jar`.
The Java host must read `Memory.bytes` afresh after WASM memory growth.

The `wasm-host` Rust binary is **not required** for this JVM path.
It remains an independent Wasmtime-based runner and a reference for
the filesystem, task, tmux and clipboard behavior.

## Experimental embedded Wasmi runner

The isolated package in `experiments/wasmi-runner/` embeds Wasmi and WASI
Preview 1 in a native executable. It is an optional experiment and does not
add dependencies to the existing std-only package. Run `just test-wasmi` to
build and test it; initial dependency downloads require network access.
The runner is selected via `CONSOLE_TOOLS_WASM_RUNNER` instead of `wasmtime`.
Measure its size together with `wasm-host` and both WASM modules. This is
experimental and not yet verified on the target machine.

## Experimental JVM backend

The upstream `rustc_codegen_jvm` backend currently lists `std::process`
(child process creation and management) as **planned**, not supported.
Both `xcat` and `cptx` require it. Therefore the JVM recipes below are
experimental diagnostics, **not a fully verified JVM release**.

Requirements: Rust/rustup, JDK 8+ (`java`, `javac`, `jar`), Python 3.8+ and Git.
`cargo-jvm` installs the pinned nightly and builds the backend during setup.

```sh
just jvm-setup       # cargo install cargo-jvm; cargo jvm setup; doctor
just jvm-smoke       # attempt to run xcat --help on JVM
just build-jvm       # package, optimize and smoke-test both JARs
just jvm-package     # attempt to package runnable JARs
just jvm-artifacts   # list resulting artifacts
```

JVM compilation and the application help screens have been observed to work
with the backend runtime on the classpath. Full application functionality,
especially process execution, remains unverified and may fail. Native `just rbuild` remains the supported release path.
See https://github.com/IntegralPilot/rustc_codegen_jvm for backend status.

## Build helper scripts

The root `Justfile` is declarative: recipes invoke Python helpers in
`scripts/` rather than embedding shell scripts. Run recipes from the
repository root with `just <recipe>`:

| Script | Responsibility |
| --- | --- |
| `scripts/build.py` | Git pull/rebase, native builds, tests and Clippy |
| `scripts/jvm.py` | JVM setup, compilation, JAR distributions, ProGuard and smoke tests |
| `scripts/wasm.py` | Offline WASI builds and smoke tests |
| `scripts/wasm2jar_probe.py` | Translate WASI modules to JVM bytecode and inspect imports |
| `scripts/wasm2jar_run.py` | Package standalone JVM JARs, apply compatibility patch and run smoke tests |
| `src/bin/wasm_host.rs` | Native std-only WASI process and clipboard bridge |
| `scripts/maintenance.py` | Installation, coverage, cleanup and target utilities |

The former root-level `build.py` has moved to `scripts/build.py`.
For direct invocation, use `python3 scripts/build.py build-debug`
or `python3 scripts/jvm.py proguard` (after generating standalone JARs).

## Just recipes

Run `just --list` to inspect the available recipes. The default `just`
command runs `build`. Recipes that invoke `pull` can update the local
checkout; `install` changes the locally installed binaries. JVM builds use
`CARGO_TARGET_DIR=target` to keep their artifacts in this repository.

| Recipe | Description |
| --- | --- |
| `just`, `just build` | Native debug build via `scripts/build.py` |
| `just build-release` | Native release build via `scripts/build.py` |
| `just pull` | Pull project changes via `scripts/build.py github_pull` |
| `just gbuild` | Pull and run a native debug build |
| `just rbuild` | Pull, build native release binaries, and install |
| `just install` | Build release, run Clippy, and `cargo install --path .` |
| `just clear` | Clear tmux history (if available) and terminal screen |
| `just clean` | Delete `Cargo.lock` and clean this Cargo package |
| `just clean-all` | Run `cargo clean` for the workspace |
| `just targetlist` | List available rustup targets |
| `just rpi` | Cross-compile for `aarch64-unknown-linux-gnu` |
| `just cover-setup` | Install `cargo-llvm-cov` and LLVM tools |
| `just cover` | Produce HTML coverage |
| `just cover-lcov` | Produce LCOV coverage |
| `just cover-text` | Print terminal coverage |
| `just wasm2jar-test-cptx` | Test translated cptx including desktop clipboard roundtrip |
| `just wasm2jar-test-xcat` | Test translated xcat JVM help (filesystem bridge pending) |
| `just wasm2jar-test-all` | Run both wasm2jar test paths |
| `just jvm-target-dir` | Prepare backend-local target directory |
| `just jvm-setup` | Install/setup `cargo-jvm` and run doctor |
| `just build-jvm` | Package, optimize with ProGuard, smoke-test and print both final JAR sizes |
| `just jvm-package` | Package original JVM release JARs |
| `just jvm-distributions` | Build both thin and standalone JAR layouts |
| `just jvm-test-distributions` | Build both layouts and run four `--help` smoke tests |
| `just jvm-smoke` | Run `xcat --help` via `cargo jvm run` |
| `just jvm-proguard` | Conservatively shrink standalone JARs (no optimization or obfuscation) |
| `just jvm-test-proguard` | Build optimized JARs and compare help/error behavior against standalone JARs |
| `just jvm-artifacts` | List original JVM JAR and class artifacts |

### JVM distribution layouts

`just jvm-distributions` depends on `jvm-package`, so it rebuilds both
original release JARs before preparing the distributions:

```text
target/jvm-package/release/
  xcat.jar
  cptx.jar
target/jvm-dist/
  thin/
    xcat.jar
    cptx.jar
    runtime-0.1.0.jar
  standalone/
    xcat.jar
    cptx.jar
```

The **thin** JARs refer to the adjacent `runtime-0.1.0.jar` through
their manifest `Class-Path`; distribute that runtime JAR alongside
either application JAR. The **standalone** JARs merge the backend runtime
classes into each application JAR and do not require a separate runtime
JAR. Both approaches still require Java and any external tools used by
the applications (for example, tmux and clipboard utilities).

```sh
just jvm-distributions
java -jar target/jvm-dist/thin/xcat.jar --help
java -jar target/jvm-dist/thin/cptx.jar --help
java -jar target/jvm-dist/standalone/xcat.jar --help
java -jar target/jvm-dist/standalone/cptx.jar --help

# Or build and smoke-test all four in one command:
just jvm-test-distributions
```

### Optional ProGuard size optimization

`just build-jvm` is the experimental JVM pipeline: it packages both programs, creates thin and standalone distributions, shrinks standalone JARs with ProGuard, compares basic CLI behavior with the original JARs, and prints final paths and sizes. `just rbuild` remains native-only. ProGuard is provisioned automatically when necessary. For compilation only, use `python3 scripts/jvm.py build`.


`just build-jvm` automatically downloads and caches pinned **ProGuard 7.10.0** under `target/tools/` when the system ProGuard is missing or older than 7.8 (required for Java 25). No system-wide installation is needed. Set `PROGUARD=/path/to/proguard` to override the executable. A full JDK with `jmods` and network access on first download are required. ProGuard reads the standalone JARs and uses the JDK modules as library inputs:

```sh
just jvm-proguard
du -h target/jvm-dist/standalone/*.jar target/jvm-dist/proguard/*.jar
just jvm-test-proguard
```

The additional outputs are `target/jvm-dist/proguard/xcat.jar` and
`target/jvm-dist/proguard/cptx.jar`. The original, thin, and standalone
artifacts remain unchanged. ProGuard uses five optimization passes,
shrinking, access modification, aggressive interface merging, and
obfuscation. It retains the Java entry points and backend runtime classes
to reduce reflection-related breakage. This is an **experimental**
optimization: generated Rust-JVM code may depend on indirect references
that static analysis cannot detect. If ProGuard reports missing
dependencies, investigate them rather than suppressing warnings blindly.
A successful `--help` smoke test does not prove full functionality.

The `--help` tests check JVM startup and argument handling only.
They do **not** verify file scanning, clipboard integration, tmux,
or child-process execution. The backend remains experimental. The
original `target/jvm-package/release/*.jar` artifacts are preserved
and may require the runtime on the Java classpath to run.

## File selection and output

xcat uses [fsscanner](https://github.com/witold-k/fsscanner) to traverse
the directory tree. Its JSON configuration controls which filenames and
suffixes are included and which directories are excluded. Matching is
case-insensitive. Selected files are ordered with Markdown first, text/log
files next, and other accepted files afterward. The copied text includes file
boundaries and file contents.

Targets outside the canonical scan root are rejected, and duplicate canonical
paths are included once. Non-UTF-8, binary, and oversized files are skipped.
Directory exclusions apply at any nesting level.

## Configuration

On first scan, xcat creates a default configuration if none exists:

- Linux / Unix: `$XDG_CONFIG_HOME/xcat/config.json`, or
  `~/.config/xcat/config.json` when `XDG_CONFIG_HOME` is unset.
- Windows: `%APPDATA%\\xcat\\config.json` when `APPDATA` is set.
- Any platform: `-c path/to/config.json` selects another file.

An existing invalid configuration is reported as an error, not overwritten.
The `scanendfilter` and `scanfullfilter` keys follow the naming used by
`aiagents`. Example:

```json
{
  "scanendfilter": [".rs", ".md", ".toml", ".sh"],
  "scanfullfilter": ["Cargo.toml", "Makefile", "Justfile"],
  "excludedirs": [".git", "target", "build"],
  "max_file_bytes": 2000000
}
```

- `scanendfilter`: allowed filename suffixes, each beginning with `.`.
- `scanfullfilter`: allowed complete filenames.
- `excludedirs`: directory names excluded throughout the tree.
- `max_file_bytes`: positive maximum size for an individual included file.

## Task execution (`-e`)

The first clipboard copy contains the scanned files. The selected task then
runs with its working directory set to the scan root. Once it finishes, xcat
replaces the clipboard text with the scan plus clearly labeled **stdout**,
**stderr**, and **exit status**.

| Task file | Execution |
| --- | --- |
| `Justfile` | `just --justfile <file> [args]` |
| `Makefile`, `makefile`, `GNUmakefile` | `make -f <file> [args]` |
| `*.sh` | `bash <file> [args]` |
| `*.ps1` | PowerShell `-NoProfile -File <file> [args]` |
| Other executable file | Direct execution with supplied arguments |

A task returning a nonzero status makes xcat exit unsuccessfully, but its
captured output is still copied. If launching the task fails, the execution
error is appended to the clipboard text.

## Tests

Tests live under `tests/` as integration tests:

- `tests/config.rs`: filename filters, excluded directories, config creation,
  persistence, and invalid JSON.
- `tests/cptx.rs`: help and CLI argument validation without tmux or clipboard.
- `tests/cli.rs`: CLI help, unknown options, missing values, and forwarded
  argument validation. These tests do not require a clipboard session.

```sh
cargo test --all-targets
cargo build --release --bin xcat
```

Manual end-to-end verification of scanning and clipboard behavior requires a
working clipboard backend and, for `-e`, the relevant task runner.
