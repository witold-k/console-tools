# console-tools

Rust command-line utilities. **xcat** collects selected project files into a
single clipboard text, optionally runs a task, and copies the combined source
and task output back to the clipboard. It is based on
[buildscripts/lua/bin/xcat.lua](https://github.com/witold-k/buildscripts/blob/master/lua/bin/xcat.lua).

## Build

```sh
cargo build --release --bin xcat
./target/release/xcat --help
```

For clipboard access on Linux, install **wl-clipboard** (`wl-copy`) for
Wayland or **xclip** / **xsel** for X11. Windows uses PowerShell
`Set-Clipboard`. A working desktop clipboard is required for scans.

## Commands

| Command | Behavior |
| --- | --- |
| `xcat` | Scan the current working directory and copy selected files |
| `xcat -d /path/to/project` | Scan a specific directory |
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
- `tests/cli.rs`: CLI help, unknown options, missing values, and forwarded
  argument validation. These tests do not require a clipboard session.

```sh
cargo test --all-targets
cargo build --release --bin xcat
```

Manual end-to-end verification of scanning and clipboard behavior requires a
working clipboard backend and, for `-e`, the relevant task runner.
