# Requires PowerShell 5.1 or newer.
# Runs tools/repro_check.py. Paths may contain spaces.
# This wrapper does not install dependencies, edit manifests, or sign off L02.
# The service interpreter checked by the script remains
# backend\.venv\Scripts\python.exe. This file only bootstraps the checker.

$ErrorActionPreference = 'Stop'
$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ToolsDir
$Script = Join-Path $ToolsDir 'repro_check.py'
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
    Write-Error 'Python 3.11 or newer is required to run tools/repro_check.py. Nothing was installed.'
    exit 2
}

& $LauncherPython -B $Script @args
exit $LASTEXITCODE
