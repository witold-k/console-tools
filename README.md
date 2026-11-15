# console-tools

Rust command-line utilities. **cptx** copies the entire current tmux pane\n(including scrollback) to the desktop clipboard. **xcat** collects selected project files into a
single clipboard text, optionally runs a task, and copies the combined source
and task output back to the clipboard. It is based on
[buildscripts/lua/bin/xcat.lua](https://github.com/witold-k/buildscripts/blob/master/lua/bin/xcat.lua).

## Build

```sh
cargo build --release --bins
./target/release/xcat --help\n./target/release/cptx --help
```

For clipboard access on Linux, install **wl-clipboard** (`wl-copy`) for
Wayland or **xclip** / **xsel** for X11. Windows uses PowerShell
`Set-Clipboard`. A working desktop clipboard is required for scans.

## Commands\n\n### cptx\n\nRun `cptx` from inside a tmux pane to copy its entire available scrollback\nand visible contents to the desktop clipboard. This is a Rust replacement\nfor [buildscripts/bash/cptx](https://github.com/witold-k/buildscripts/blob/master/bash/cptx).\nIt runs `tmux capture-pane -p -S -`, checks its exit status, and uses the\nsame clipboard implementation as `xcat` (X11 CLIPBOARD or Wayland).\n`cptx --help` displays usage. Running outside tmux reports an error.\nThe command does not print the captured pane or modify tmux history.\n\n### xcat\n

| Command | Behavior |
| --- | --- |
| `xcat` | Scan the current working directory and copy selected files |
| `xcat -d /path/to/project` | Scan a specific directory |
| `xcat -r script.py -- --verbose` | Run only the task, auto-select launcher, copy its output |\n| `xcat -e ./test.sh -- --verbose` | Scan, copy, execute a shell script, then copy scan + output |
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
just build-jvm       # attempt to compile xcat and cptx
just jvm-package     # attempt to package runnable JARs
just jvm-artifacts   # list resulting artifacts
```

JVM compilation and the application help screens have been observed to work
with the backend runtime on the classpath. Full application functionality,
especially process execution, remains unverified and may fail. Native `just rbuild` remains the supported release path.
See https://github.com/IntegralPilot/rustc_codegen_jvm for backend status.

## Just recipes

Run `just --list` to inspect the available recipes. The default `just`
command runs `build`. Recipes that invoke `pull` can update the local
checkout; `install` changes the locally installed binaries. JVM builds use
`CARGO_TARGET_DIR=target` to keep their artifacts in this repository.

| Recipe | Description |
| --- | --- |
| `just`, `just build` | Native debug build via `build.py` |
| `just build-release` | Native release build via `build.py` |
| `just pull` | Pull project changes via `build.py github_pull` |
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
| `just jvm-target-dir` | Prepare backend-local target directory |
| `just jvm-setup` | Install/setup `cargo-jvm` and run doctor |
| `just build-jvm` | Compile both programs for the JVM |
| `just jvm-package` | Package original JVM release JARs |
| `just jvm-distributions` | Build both thin and standalone JAR layouts |
| `just jvm-test-distributions` | Build both layouts and run four `--help` smoke tests |
| `just jvm-smoke` | Run `xcat --help` via `cargo jvm run` |
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
- `tests/cptx.rs`: help and CLI argument validation without tmux or clipboard.\n- `tests/cli.rs`: CLI help, unknown options, missing values, and forwarded
  argument validation. These tests do not require a clipboard session.

```sh
cargo test --all-targets
cargo build --release --bin xcat
```

Manual end-to-end verification of scanning and clipboard behavior requires a
working clipboard backend and, for `-e`, the relevant task runner.
