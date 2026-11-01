# Requires PowerShell 5.1 or newer.
# Runs tools/local_run.py. Paths may contain spaces.
# The service interpreter stays backend\.venv\Scripts\python.exe even when this
# wrapper has to bootstrap the launcher script with another Python.
# Node defaults to AGEMORPH_NODE, else D:\JAVA run tools\node.exe when that
# file exists, else node on PATH. This script does not install dependencies.

$ErrorActionPreference = 'Stop'
$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ToolsDir
$Script = Join-Path $ToolsDir 'local_run.py'
$VenvPython = Join-Path $Root 'backend\.venv\Scripts\python.exe'

$LauncherPython = $null
if (Test-Path -LiteralPath $VenvPython) {
    $LauncherPython = $VenvPython
} else {
    $Command = Get-Command python -ErrorAction SilentlyContinue
    if ($Command) {
        $LauncherPython = $Command.Source
    }
}
if (-not $LauncherPython) {
    Write-Error 'Python is required to run tools/local_run.py. The service still uses backend\.venv\Scripts\python.exe and will not fall back to another interpreter.'
    exit 2
}

& $LauncherPython -B $Script @args
exit $LASTEXITCODE
