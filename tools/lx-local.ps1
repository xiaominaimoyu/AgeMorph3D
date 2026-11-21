#Requires -Version 5.1
# Runs preprocessing/lx_local.py (LX-1..LX-3) on the user's own Windows machine.
# Paths may contain spaces. Prefers backend\.venv\Scripts\python.exe, then the
# "py -3.11" launcher, then the first real python on PATH (Microsoft Store
# WindowsApps aliases are skipped, not fatal). Every candidate goes through the
# same Test-Python311 probe and is skipped unless it really is 3.11.
# This script does not install dependencies, does not accept or store a password,
# and the Python CLI refuses to run without --local-only-ack. Only summary.json is
# shareable; everything under <output-dir>\local\ stays on this machine.
# Exit codes: 0 passed, 1 needs_review, 2 rejected (including every launcher
# failure, reported as LAUNCHER_PYTHON_311_REQUIRED or LAUNCHER_START_FAILED).
# NOTE: never run on Windows by the developer; only statically tested.

$ErrorActionPreference = 'Stop'

function Write-Rejected([string]$Code, [string]$Message) {
    # stderr + a fixed JSON line on stdout; no terminating error, so the exit code stays 2.
    [Console]::Error.WriteLine($Message)
    [Console]::Out.WriteLine('{"status": "rejected", "error_code": "' + $Code + '"}')
}

$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ToolsDir
$VenvPython = Join-Path $Root 'backend\.venv\Scripts\python.exe'

function Test-Python311([string]$Exe, [string[]]$PrefixArgs) {
    # One shared probe for every candidate (venv, "py -3.11", PATH python): the
    # interpreter must start and report 3.11, else it is skipped. In Windows
    # PowerShell 5.1 a redirected native stderr line becomes an error record, which
    # 'Stop' would turn into a terminating error, so relax it for the probe only.
    $Probe = 3
    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Exe @PrefixArgs -B -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 3)" 2>$null | Out-Null
        $Probe = $LASTEXITCODE
    } catch {
        $Probe = 3
    } finally {
        $ErrorActionPreference = $PreviousPreference
    }
    return ($Probe -eq 0)
}

$Launcher = $null
$LauncherArgs = @()
if ((Test-Path -LiteralPath $VenvPython -PathType Leaf) -and (Test-Python311 $VenvPython @())) {
    $Launcher = $VenvPython
}
if (-not $Launcher) {
    # Probe first so a missing 3.11 does not leak py's own exit code.
    $Py = @(Get-Command py -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1
    if ($Py -and (Test-Python311 $Py.Source @('-3.11'))) {
        $Launcher = $Py.Source
        $LauncherArgs = @('-3.11')
    }
}
if (-not $Launcher) {
    # Get-Command may return several matches; take the first real 3.11 application.
    $Candidates = @(Get-Command python -CommandType Application -All -ErrorAction SilentlyContinue)
    foreach ($Candidate in $Candidates) {
        if ($Candidate.Source -notlike '*\WindowsApps\*' -and (Test-Python311 $Candidate.Source @())) {
            $Launcher = $Candidate.Source
            break
        }
    }
}
if (-not $Launcher) {
    Write-Rejected 'LAUNCHER_PYTHON_311_REQUIRED' 'Python 3.11 is required (backend\.venv, "py -3.11", or python on PATH).'
    exit 2
}

# Keep the caller's working directory and environment unchanged afterwards.
$Code = 2
$PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location -LiteralPath $Root
try {
    try {
        & $Launcher @LauncherArgs -B -m preprocessing.lx_local @args
        $Code = $LASTEXITCODE
        if ($Code -notin 0, 1, 2) {
            # e.g. the interpreter failed to start or crashed outside the CLI.
            Write-Rejected 'LAUNCHER_START_FAILED' "Python exited with code $Code before the CLI finished."
            $Code = 2
        }
    } catch {
        Write-Rejected 'LAUNCHER_START_FAILED' 'Python could not be started.'
        $Code = 2
    }
} finally {
    Pop-Location
    $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode
}
exit $Code
