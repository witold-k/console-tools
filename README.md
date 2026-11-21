# console-tools

Rust command-line utilities. **cptx** copies the entire current tmux pane
(including scrollback) to the desktop clipboard. **xcat** collects selected project files into a
single clipboard text, optionally runs a task, and copies the combined source
and task output back to the clipboard. It is based on
[buildscripts/lua/bin/xcat.lua](https://github.com/witold-k/buildscripts/blob/master/lua/bin/xcat.lua).

## Verified no_std JVM ProGuard release (21 November 2026)

On this experimental branch, `just rbuild` now publishes both no_std
WASI-to-JVM JARs using the **minimal ProGuard keep** policy. The JVM
integration tests run before publication, and the optimized cptx candidate
also passes desktop failure, injected WASI I/O error and short-write checks.
The published artifacts are under the Cargo workspace target directory in
`wasm2jar-probe/{xcat,cptx}-standalone.jar`.

| Policy | xcat JAR | cptx JAR | Total |
| --- | ---: | ---: | ---: |
| Conservative (previous default) | 25,540 B | 14,275 B | 39,815 B |
| Relaxed | 24,371 B | 13,173 B | 37,544 B |
| **Minimal (new default)** | **23,941 B** | **12,816 B** | **36,757 B** |

These are local measurements, not guaranteed byte-identical builds.
`just jvm-no-std-proguard-compare` rebuilds and tests all three policies
without publishing; `just rbuild` builds and publishes the minimal policy.
The known late-invalid-UTF-8 stdout streaming difference in no_std cptx
remains; the tested desktop clipboard path rejects invalid input.

## Build

The default `just` commands use the **pinned Rust Nightly
`nightly-2026-11-21`**. Release builds of `xcat` and `cptx` rebuild
the Rust standard library with `panic=immediate-abort` to minimize size.
This changes panic behavior: no unwinding or panic hooks.

Install the toolchain and WASI target once:

```sh
just wasm-nightly-setup
```

The JVM pipeline additionally needs `wasm2jar` 0.1.0, Binaryen's
`wasm-opt`, and a JDK (`java`, `javac`, `jar`).
See the pinned Nightly section below for details.

```sh
just build          # pinned Nightly native debug build, tests, Clippy
just gbuild         # pull current branch, then build
just build-release  # pinned Nightly immediate-abort native release, tests, Clippy
just rbuild         # pull, build/install native tools, build/test JVM, publish JARs
just build-wasm     # pinned Nightly WASI + JVM integration tests and publication
just wasm2jar-test-all # same pinned Nightly JVM pipeline
```

The normal output paths remain the Cargo workspace's
`target/release/{xcat,cptx}`, `target/wasm32-wasip1/release/*.wasm`,
and `target/wasm2jar-probe/*-standalone.jar`. The Nightly WASI/JVM
build first runs in isolated directories, tests both JVM tools, and only
then publishes the verified artifacts. Native `install` copies the
already-built binaries instead of silently recompiling with Stable.
`wasm-host` remains a separate native bridge.

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
interpolation. Arguments after `--` require `-e` or `-r`.

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
The native WASI host reuses Rust argument parsing and task dispatch.
The Java WASI host has its own OS process-launch and clipboard bridge.
Configuration, scanning and task-report formatting remain in shared Rust/WASM code.

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

## Pinned Nightly WASI/JVM size experiment

The regular `just rbuild` pipeline now uses this pinned Nightly build. This pipeline
rebuilds Rust's standard library with `panic=immediate-abort` and translates
the resulting WASI modules into standalone Java JARs. The script validates
the compiler commit before building and leaves production artifacts untouched.

### Installation and commands

Install `rustup` and `just` first. On a machine with a working rustup
installation, run the **explicit one-time setup**:

```sh
just wasm-nightly-setup
```

This installs the official `nightly-2026-11-21` toolchain, `rust-src`,
and its separate `wasm32-wasip1` target. If rustup is managed under a
nonstandard prefix (such as `/opt/rust`), configure `RUSTUP_HOME` and
`CARGO_HOME` consistently before running setup; don't mix installations.

Other prerequisites are Python 3, `wasm2jar` 0.1.0, Binaryen's `wasm-opt`,
and a JDK with `java`, `javac`, and `jar`. On Debian/Ubuntu, for example,
`sudo apt install binaryen openjdk-25-jdk` provides Binaryen and a JDK
where those packages are available. Install `wasm2jar` separately using
the project's existing instructions. The build recipes deliberately **do not**
install packages or toolchains themselves.

```sh
just wasm-nightly-immediate-abort  # smaller experimental WASI + JAR artifacts; full JVM tests
just wasm-nightly-abort            # matched control with conventional panic=abort
```

The outputs live under `<Cargo target directory>/wasm-nightly-immediate-abort/`
and `.../wasm-nightly-abort/`. The scripts print sizes and compare them with
available baselines. Rust panic handling is different: immediate-abort
terminates without unwinding or running panic hooks.

### Verified toolchain and results (21 November 2026)

- Rust `nightly-2026-11-21`, rustc `1.102.0-nightly`, commit
  `c7d5ba59d8e11ee2e2204b173458eec4cb41c973`, LLVM 23.1.6.
- Binaryen `wasm-opt` 120; OpenJDK `25.0.5.0.3`; `wasm2jar`
  executable at `~/.cargo/bin/wasm2jar` (converter version documented as 0.1.0).
- Immediate-abort: xcat WASM **89,499 B**, JAR **91,902 B**;
  cptx WASM **41,371 B**, JAR **46,619 B**.
- The Java integration suites passed, including tmux/clipboard transfers up to
  336,000 bytes, UTF-8, filesystem scanning, configuration, and task execution.

Only Rust Nightly is pinned and its compiler commit checked automatically;
the other versions are recorded, not enforced. This supports repeating the
build later, but does not guarantee that upstream downloads will remain
available or that JAR files will be byte-identical. No container or private
toolchain archive is part of this setup.

## WASM-to-JVM translation (wasm2jar, experimental)

This is a **separate JVM path** from the older `rustc_codegen_jvm`
experiment below. The original std-only Rust sources compile to
`wasm32-wasip1`, then `wasm2jar` 0.1.0 translates the WASM modules into
Java bytecode. A small Java WASI Preview 1 host supplies the imported
functions. The scanning, configuration and task-report logic is reused from Rust/WASM;
OS integration (process launching, filesystem preopens and clipboard) is
provided by Java.

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
just wasm2jar-test-cptx   # default: 16 KiB no_std cptx JVM, full regression suite
just wasm2jar-test-cptx-std  # legacy std-based JVM comparison
just wasm2jar-test-xcat   # scan, config, clipboard, -e/-r tasks and reports
just wasm2jar-test-all    # both paths, including native/WASI build checks
# Locate the Cargo workspace target directory (may be ../target).
TARGET_DIR=$(cargo metadata --no-deps --format-version 1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')
java -jar "$TARGET_DIR/wasm2jar-probe/cptx-standalone.jar" --help
java -jar "$TARGET_DIR/wasm2jar-probe/xcat-standalone.jar" --help
java -jar "$TARGET_DIR/wasm2jar-probe/xcat-standalone.jar"  # scan current directory
```

Generated standalone artifacts are
`<Cargo target directory>/wasm2jar-probe/cptx-standalone.jar` and
`<Cargo target directory>/wasm2jar-probe/xcat-standalone.jar`.
Use `cargo metadata --no-deps --format-version 1` to locate the target directory;
in a parent Cargo workspace it is typically `../target`, not `./target`. The default no_std cptx JVM build now uses **aggressive ProGuard with relaxed keep rules**. In the 18 November 2026 local regression runs, the verified optimized JAR was approximately **11.6 KB** (11,631–11,632 bytes), compared with approximately **12.7 KB** for the previous conservative-keep build and **14.1 KB** unoptimized. The earlier std-based cptx JAR was **52,492 bytes**.
The recorded xcat JAR size was **107,725 bytes**. Actual sizes depend on the build. These are substantially smaller than
the older `rustc_codegen_jvm` JARs.

**Verified:** `cptx --help`, stdin/UTF-8 roundtrip, and a mocked
tmux → Rust WASM → `wl-copy` desktop path with scrollback through
336,000 bytes. `xcat --help` and a real JVM filesystem scan are also
verified, including UTF-8 file content, automatic configuration creation,
and clipboard output using a mocked `wl-copy`. A manual JVM scan of the
repository also succeeded (33 files copied), including the Linux clipboard
fallback when `wl-copy` is unavailable. The Java host provides the WASI filesystem
bridge while Rust/WASM retains the scanning and filtering logic.
The 17 November 2026 `just wasm2jar-test-all` run also passed the
`xcat` `-e`/`-r` end-to-end checks, custom directory/config paths,
argument forwarding, stdout/stderr capture and WASM-generated task reports.

**Task execution (verified on Linux):** The JVM host supports
`xcatj -e <file> -- <args>` and `xcatj -r <file> -- <args>`. Java launches
trusted local tasks, captures stdout/stderr and exit status, and invokes the
Rust/WASM task-report formatter through a temporary WASI preopen. For `-e`,
the first clipboard copy contains the scan, followed by the combined scan and
report; `-r` copies only the report. Absolute `-d` paths and custom `-c`
config paths are supported through host preopens. The automated JVM end-to-end test passed on Linux with custom paths,
forwarded arguments, stdout/stderr and exit-status report formatting.

**Limitations:** WASI Preview 1 cannot launch processes itself, so the Java
host duplicates the native Rust task-launcher selection logic. The JVM host
currently supports Linux `wl-copy`, `xclip` and `xsel` clipboard utilities; Windows parity
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


### cptx JVM ProGuard optimization

`just wasm2jar-test-cptx` builds and tests the unoptimized no_std WASM-to-JVM
JAR, then applies aggressive ProGuard optimization with **relaxed keep**
rules. The optimized JAR is promoted to
`<Cargo target directory>/wasm2jar-probe/cptx-standalone.jar` **only after**
CLI, UTF-8, desktop clipboard, WASI error, and partial-write regression
checks pass. The unoptimized
`cptx-standalone-unoptimized.jar` is preserved for comparison.

The keep rules preserve the JVM entry point, dynamically resolved WASI host
methods, and the generated WASM `_start` entry point. Other generated
WASM/runtime classes are eligible for shrinking and optimization.
`wasm2jar` uses dynamic `MethodHandle` resolution, so removing all
keep rules is not a supported build configuration. The experimental
minimal-keep candidate ran ordinary CLI and desktop tests but failed the
partial-write harness because ProGuard removed or renamed classes required
to compile the test-only host; it was **not** adopted.

For diagnostics, `just cptx-proguard-relaxed-keep` compares the shrink,
optimize and aggressive modes without replacing the default JAR.
`just cptx-proguard-experiment` retains the conservative keep-rule
comparison. JAR byte counts may vary by a few bytes between builds.

### Size experiments and reproducibility

The isolated size/bytecode probes are kept for future optimization. Their
purpose, retained `just` commands, historical measurements, and known
semantic gaps are documented in
[`scripts/NO_STD_CPTX_EQUIVALENCE.md`](scripts/NO_STD_CPTX_EQUIVALENCE.md).
The abandoned upstream wasm2jar memory-store patch experiment and its
candidate-only comparison driver were removed; general measurement tools
remain available. The 16 KiB-buffer no_std cptx module with aggressive relaxed-keep ProGuard is now the default **JVM** packaging
path. Its Java desktop host provides tmux capture and clipboard integration,
and the 18 November 2026 local regression suite passed, including short
WASI writes and injected I/O failures. The native Rust cptx remains unchanged.
Standalone stdin/stdout streaming still emits a validated prefix before a
later UTF-8 error; the desktop host buffers before writing to the clipboard.

## Convenient JVM commands (Bash / PowerShell)

The repository includes sourceable shell functions in `shell/` for the
standalone wasm2jar JARs. They resolve the Cargo workspace target directory
using `cargo metadata`, so they work from any current directory.

**Bash (Linux):** add the following to `~/.bashrc` (adjust checkout path):

```sh
source /path/to/console-tools/shell/console-tools.bash
```

**PowerShell:** add the following to `$PROFILE` (adjust checkout path):

```powershell
. 'C:\path\to\console-tools\shell\console-tools.ps1'
```

Both shells define `xcatj [args...]` and `cptxj [args...]`.
For example: `xcatj -d .`, `xcatj -e ./test.sh -- --verbose`,
`xcatj -r script.py -- --verbose`, and `cptxj`.
The JVM `xcatj` command now forwards `-d`, `-c`, `-e`, `-r` and `--` task
arguments to the Java host (verified in the Linux end-to-end tests).
For normal scans, `xcatj` now reports the number of files actually emitted by
its no_std WASI scanner, matching the native `xcat` success-message format:
`Copied N scanned files to clipboard.` The WASM module sends this count as
separate host metadata; it is not appended to the clipboard contents. The JVM
end-to-end test checks the count alongside the scan output. On the tested
Linux project checkout, both commands reported 51 files. Matching counts do
not by themselves establish byte-for-byte identical clipboard contents.
`cptxj` automatically uses the JVM desktop mode; `cptxj --help`
shows help without desktop capture. `xcatj` forwards all arguments.
Set `CONSOLE_TOOLS_JAR_DIR` to the directory containing the two
standalone JARs to bypass Cargo metadata (environment variable in Bash
or `$env:CONSOLE_TOOLS_JAR_DIR` in PowerShell).

The wrappers need Java and existing built JARs; they do not build them.
On Linux the JVM hosts need the supported clipboard utilities and
`cptxj` needs tmux. The PowerShell wrapper is provided for convenience,
but the JVM desktop hosts are **not yet Windows-compatible**.

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
especially process execution, remains unverified and may fail. `just rbuild` builds and installs native release binaries and also runs both WASI-to-JVM translation test paths.
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
| `scripts/wasm2jar_run.py` | Package standalone JVM JARs, apply compatibility patch and run JVM end-to-end tests |
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
| `just install-wasm-tools` | Install missing Binaryen, JDK, wasm32-wasip1 Rust target and wasm2jar 0.1.0 (Debian/Ubuntu) |
| `just rbuild` | Pull, build/install native release binaries, build xcat/cptx WASI modules, and build/test both wasm2jar JVM targets |
| `just install` | Build release, run Clippy, and `cargo install --path .` |
| `just clear` | Clear tmux history (if available) and terminal screen |
| `just clean` | Delete `Cargo.lock` and clean this Cargo package |
| `just clean-all` | Run `cargo clean` for the workspace |
| `just targetlist` | List available rustup targets |
| `just cover-setup` | Install `cargo-llvm-cov` and LLVM tools |
| `just cover` | Produce HTML coverage |
| `just cover-lcov` | Produce LCOV coverage |
| `just cover-text` | Print terminal coverage |
| `just wasm2jar-test-cptx` | Test translated cptx including desktop clipboard roundtrip |
| `just wasm2jar-test-xcat` | Test translated xcat JVM help, scan, config, clipboard and `-e`/`-r` task execution |
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

`just build-jvm` is the experimental JVM pipeline: it packages both programs, creates thin and standalone distributions, shrinks standalone JARs with ProGuard, compares basic CLI behavior with the original JARs, and prints final paths and sizes. `just rbuild` also invokes `wasm2jar-test-all` (including the WASI builds and JVM translation tests); the separate `build-jvm` command uses the older `rustc_codegen_jvm` backend. ProGuard is provisioned automatically when necessary. For compilation only, use `python3 scripts/jvm.py build`.


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

These `--help`-only limitations apply to the **older** `rustc_codegen_jvm`
backend. The separate `wasm2jar` backend above has passed end-to-end tests
for filesystem scanning, clipboard integration, tmux capture and task execution
on Linux. Windows host integration remains unverified. The
original `target/jvm-package/release/*.jar` artifacts are preserved
and may require the runtime on the Java classpath to run.

## File selection and output

xcat uses its own standard-library Rust scanner to traverse
the directory tree. Its JSON configuration controls which filenames and
suffixes are included and which directories are excluded. Matching is
case-insensitive. Selected files are ordered with Markdown first, text/log
files next, and other accepted files afterward. The copied text includes file
boundaries and file contents.

File symlinks are followed even when their targets lie outside the scan root,
using the symlink's relative path for filtering and output. Directory symlinks
are traversed only when their targets stay within the canonical scan root.
Duplicate canonical file targets are included once. Broken symlinks, non-UTF-8,
binary, and oversized files are skipped. Directory exclusions apply at any
nesting level.

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


### wasm2jar bytecode size investigation

The upstream compiler is [harpocrates/wasm2jar](https://github.com/harpocrates/wasm2jar),
whose `lib/Cargo.toml` declares version 0.1.0. Its
`lib/src/translate/memory.rs` translates WASM loads/stores through
`java.nio.ByteBuffer`, explicitly emitting `Swap` around memory access and
`Pop` after `ByteBuffer.put` (which returns the buffer). The latter is
necessary for JVM stack balance and must not simply be deleted.

The large `Part0` classes are dominated by translated WASM methods, not
the Java launcher. Investigate memory-access translation before changing
the Rust program. `just wasm-memory-patterns` counts selected sequences
in the generated standalone JARs, and `just wasm-bytecode-report` reports
instruction frequencies and large methods. Both are read-only. They do
not establish whether a given instruction is redundant.

Next compiler-side experiment, **not yet implemented**: compare a
verified alternative memory-access emission strategy against upstream
`wasm2jar` 0.1.0. Preserve ByteBuffer little-endian behavior, bounds
checking, stack types and WASM traps. Run the full JVM end-to-end suite
for both tools before accepting any candidate; record JAR size and
bytecode counts against the baseline. No compiler fork or translator
patch is included in this repository yet.

### Default aggressive ProGuard optimization for the no_std cptx JVM JAR

The default `just wasm2jar-test-cptx` recipe builds and regression-tests the
16 KiB-buffer no_std WASI module and packages the unoptimized JVM JAR as
`wasm2jar-probe/cptx-standalone-unoptimized.jar`. It then runs the aggressive
ProGuard configuration, verifies CLI, UTF-8/binary boundaries, mocked desktop
tmux/clipboard integration, WASI I/O errors and test-host partial writes, and
atomically publishes the passing candidate as
`wasm2jar-probe/cptx-standalone.jar`. If optimization or verification fails,
the default JAR is not replaced. The native binaries and xcat are unaffected.

To compare the shrink, optimize and aggressive modes against the preserved
unoptimized reference, run:

```sh
just cptx-proguard-experiment
```

Each candidate is kept separately in the Cargo workspace target directory.
Generated wasm2jar ABI classes remain conservatively kept because dynamic
MethodHandle bindings are not fully visible to static analysis. The partial
WASI write harness recompiles a test-only host against the optimized runtime;
it does **not** exercise the ProGuard-optimized host bytecode with injected
short writes.

### Verified minimal ProGuard JAR sizes (Linux)

The no_std wasm2jar pipeline uses the verified `minimal` keep policy by
default for both `xcat` and `cptx`. Run `just rbuild` to build, run the
regression gates and publish both verified JARs. The file-count reporting
change is included in the xcat JVM regression test.

Latest verified local build (21 November 2026):

| Artifact | Size |
| --- | ---: |
| Native xcat | 128,088 bytes |
| Native cptx | 74,976 bytes |
| JVM xcat | 24,793 bytes |
| JVM cptx | 12,817 bytes |

The JVM JARs are published to `wasm2jar-probe/xcat-standalone.jar` and
`wasm2jar-probe/cptx-standalone.jar` under the Cargo target directory.
Use `just jvm-no-std-proguard-compare` to compare conservative, relaxed and
minimal keep policies without publishing the candidates. Size measurements
are build-specific and can change after code or toolchain updates.

### Reproducibility diagnostics (non-blocking)

```sh
just cptx-jvm-reproducibility
```

This builds two independent unoptimized JVM JARs, applies and tests aggressive
ProGuard to both, and compares SHA-256 hashes and classfile differences.
The wasm2jar `InnerClasses` metadata can be emitted in different orders and
ProGuard does not necessarily normalize that ordering. Hash differences are
diagnostic, **not** a release or merge gate. The default build instead requires
functional regression tests to pass.

**Known semantic gap:** stdin streaming may write a valid prefix before later
invalid UTF-8 is detected, whereas desktop clipboard capture validates the
whole input before invoking the clipboard. This behavior predates ProGuard
and remains a separate correctness consideration.
