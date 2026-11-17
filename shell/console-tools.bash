# Source from ~/.bashrc: source /path/to/console-tools/shell/console-tools.bash
# Optional: export CONSOLE_TOOLS_JAR_DIR=/absolute/path/to/wasm2jar-probe
_console_tools_jar_dir() {
    if [[ -n ${CONSOLE_TOOLS_JAR_DIR:-} ]]; then
        printf '%s\n' "$CONSOLE_TOOLS_JAR_DIR"
        return
    fi
    local metadata target
    metadata=$(cd "$_CONSOLE_TOOLS_ROOT" && cargo metadata --no-deps --format-version 1 2>/dev/null) || {
        printf 'console-tools: cargo metadata failed; set CONSOLE_TOOLS_JAR_DIR\n' >&2
        return 1
    }
    target=$(printf '%s' "$metadata" | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])') || return
    printf '%s/wasm2jar-probe\n' "$target"
}
_CONSOLE_TOOLS_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
xcatj() {
    local dir
    dir=$(_console_tools_jar_dir) || return
    [[ -f "$dir/xcat-standalone.jar" ]] || { printf 'Missing JAR: %s\nRun: just wasm2jar-test-xcat\n' "$dir/xcat-standalone.jar" >&2; return 1; }
    java -jar "$dir/xcat-standalone.jar" "$@"
}
cptxj() {
    local dir
    dir=$(_console_tools_jar_dir) || return
    [[ -f "$dir/cptx-standalone.jar" ]] || { printf 'Missing JAR: %s\nRun: just wasm2jar-test-cptx\n' "$dir/cptx-standalone.jar" >&2; return 1; }
    if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
        java -jar "$dir/cptx-standalone.jar" "$@"
    else
        java -jar "$dir/cptx-standalone.jar" --desktop "$@"
    fi
}
