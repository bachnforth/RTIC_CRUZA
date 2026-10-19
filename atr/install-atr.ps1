param([string]$PythonPath = (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
$ErrorActionPreference = 'Stop'
# A private virtual environment keeps these packages out of the shared runtime.
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Python runtime missing. Pass -PythonPath with a Python 3.11+ executable.' }
$venv = Join-Path $PSScriptRoot 'runtime\venv'
& $PythonPath -m venv $venv
if ($LASTEXITCODE) { throw 'Could not create the virtual environment.' }
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE) { throw 'Package installation failed; see the messages above.' }
Write-Output 'Recognition packages installed in atr\runtime\venv.'
