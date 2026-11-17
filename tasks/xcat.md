- please got to repo https://github.com/witold-k/buildscripts and examine
 lua/bin/xcat.lua

 - i need simular functionality as rust application:

 - additionally i need a config file, like in agagens with same file suffixes.
 - also auto creation if not availabe

 - some base library function (xcat should use them):
   - function to copy to system clipboard, for x, wayland and windows
   - original requirement: use https://github.com/witold-k/fsscanner to scan files
     (superseded for the std-only native/WASI build: scanning now uses std::fs)
   - scanning should always use filter from config
   - xcat without arguments : scan current dir with filter and copy to clipboard
   - xcat -d <dir> scan dir <dir> and copy to clipboard
   - xcat -e <file> [-d dir] [ -- args for excuted file ] scan dir, copy to clipboard execute file and copy stdout + stderr to clipboard
        - in case file is pure executable => just execuete file
        - Justfile call just file
        - Makefile/makefile => call make file
        - *.sh call bash
        - *.ps1 call powershell
    - xcat -h also offer detailed help with some examples

    - -r standalone (searched for exe)

    - also provide excutable jvm build.


## WASI design update (2026-11)

- One shared Rust source for native and wasm32-wasip1, with zero Cargo dependencies.
- Dependency-free iterative filesystem scanner and JSON configuration parser.
- Small Rust host only for functionality absent from WASI Preview 1:
  tmux, task execution and clipboard. It reuses existing native Rust modules.
- No duplicate Java/Python utility implementation, Maven, Chicory or runtime crates.
- Run `just test-wasm` for native tests, WASI smoke tests and host integration.
