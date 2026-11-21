#Requires -Version 5.1
# Runs preprocessing/lx_local.py (LX-1..LX-3) on the user's own Windows machine.
# Paths may contain spaces. Prefers backend\.venv\Scripts\python.exe, then the
# "py -3.11" launcher, then python on PATH (the Microsoft Store alias is refused).
# This script does not install dependencies, does not accept or store a password,
# and the Python CLI refuses to run without --local-only-ack. Only summary.json is
# shareable; everything under <output-dir>\local\ stays on this machine.
# Exit codes are passed through: 0 passed, 1 needs_review, 2 rejected.

$ErrorActionPreference = 'Stop'
$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ToolsDir
$VenvPython = Join-Path $Root 'backend\.venv\Scripts\python.exe'

$Launcher = $null
$LauncherArgs = @()
if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    $Launcher = $VenvPython
} else {
    $Py = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
    if ($Py) {
        $Launcher = $Py.Source
        $LauncherArgs = @('-3.11')
    } else {
        $Command = Get-Command python -CommandType Application -ErrorAction SilentlyContinue
        if ($Command -and ($Command.Source -notlike '*\WindowsApps\*')) {
            $Launcher = $Command.Source
        }
    }
}
if (-not $Launcher) {
    # Write to stderr without a terminating error so the exit code stays 2.
    [Console]::Error.WriteLine('Python 3.11 is required (backend\.venv, "py -3.11", or python on PATH).')
    exit 2
}

# Keep the caller's working directory and environment unchanged afterwards.
$Code = 2
$PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location -LiteralPath $Root
try {
    & $Launcher @LauncherArgs -B -m preprocessing.lx_local @args
    $Code = $LASTEXITCODE
} finally {
    Pop-Location
    $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode
}
exit $Code
