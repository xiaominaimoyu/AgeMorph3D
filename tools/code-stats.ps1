# Requires PowerShell 5.1 or newer.
# Runs tools/code_stats.py. Paths may contain spaces.
# This wrapper does not install anything, map authors to members, or write thesis text.

$ErrorActionPreference = 'Stop'
$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ToolsDir
$Script = Join-Path $ToolsDir 'code_stats.py'
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
    Write-Error 'Python 3.11 or newer is required to run tools/code_stats.py. Nothing was installed.'
    exit 2
}

& $LauncherPython -B $Script @args
exit $LASTEXITCODE
