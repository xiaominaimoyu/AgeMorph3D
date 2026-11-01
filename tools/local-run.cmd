@echo off
setlocal EnableExtensions
REM Bootstrap tools\local_run.py. The service interpreter remains
REM backend\.venv\Scripts\python.exe inside the Python entry; this wrapper
REM only falls back when that file is missing so the launcher can report it.
REM Node is selected by the Python entry (AGEMORPH_NODE, the documented
REM D:\JAVA run tools\node.exe path when present, or node on PATH).
REM This wrapper does not install dependencies or change system configuration.

set "TOOLS=%~dp0"
for %%I in ("%TOOLS%..") do set "ROOT=%%~fI"
set "SCRIPT=%TOOLS%local_run.py"
set "VENV_PY=%ROOT%\backend\.venv\Scripts\python.exe"
set "RUNPY=%VENV_PY%"
if not exist "%RUNPY%" set "RUNPY=python"
"%RUNPY%" -B "%SCRIPT%" %*
exit /b %ERRORLEVEL%
