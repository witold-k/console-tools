# Dot-source from $PROFILE: . 'C:\path\to\console-tools\shell\console-tools.ps1'
# Optional: $env:CONSOLE_TOOLS_JAR_DIR = 'C:\path\to\wasm2jar-probe'
$script:ConsoleToolsRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
function Get-ConsoleToolsJarDir {
    if ($env:CONSOLE_TOOLS_JAR_DIR) { return $env:CONSOLE_TOOLS_JAR_DIR }
    Push-Location $script:ConsoleToolsRoot
    try {
        $metadata = (& cargo metadata --no-deps --format-version 1 | Out-String)
        if ($LASTEXITCODE -ne 0) { throw 'cargo metadata failed; set CONSOLE_TOOLS_JAR_DIR' }
        $target = ($metadata | ConvertFrom-Json).target_directory
        return (Join-Path $target 'wasm2jar-probe')
    } finally { Pop-Location }
}
function xcatj {
    $dir = Get-ConsoleToolsJarDir
    $jar = Join-Path $dir 'xcat-standalone.jar'
    if (-not (Test-Path -LiteralPath $jar -PathType Leaf)) { throw "Missing JAR: $jar (run just wasm2jar-test-xcat)" }
    & java -jar $jar @args
}
function cptxj {
    $dir = Get-ConsoleToolsJarDir
    $jar = Join-Path $dir 'cptx-standalone.jar'
    if (-not (Test-Path -LiteralPath $jar -PathType Leaf)) { throw "Missing JAR: $jar (run just wasm2jar-test-cptx)" }
    if ($args.Count -gt 0 -and $args[0] -in @("--help", "-h")) { & java -jar $jar @args }
    else { & java -jar $jar --desktop @args }
}
