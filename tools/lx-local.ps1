# Requires PowerShell 5.1 or newer.
# Runs preprocessing/lx_local.py (LX-1..LX-3). Paths may contain spaces.
# Prefer backend\.venv\Scripts\python.exe; otherwise python on PATH.
# This script does not install dependencies, does not accept a password,
# and must be given --local-only-ack. Only summary.json is shareable.

$ErrorActionPreference = 'Stop'
$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ToolsDir
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
    Write-Error 'Python is required to run python -m preprocessing.lx_local. Install the project interpreter or add python to PATH.'
    exit 2
}

Set-Location -LiteralPath $Root
& $LauncherPython -B -m preprocessing.lx_local @args
exit $LASTEXITCODE
