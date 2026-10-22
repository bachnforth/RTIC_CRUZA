@echo off
rem One-time download of offline aerial imagery around the flying field.
set "PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0download-imagery.py" %*
pause
