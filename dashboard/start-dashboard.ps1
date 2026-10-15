param([string]$PythonPath = (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'), [switch]$NoOpen)
$ErrorActionPreference = 'Stop'
$url = 'http://127.0.0.1:8765'
try { $status = Invoke-RestMethod "$url/status" -TimeoutSec 2 } catch { $status = $null }
if (-not $status) {
    if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Python runtime missing. Pass -PythonPath with a Python 3.11+ executable.' }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'runtime\mediamtx-v1.21.2\mediamtx.exe'))) { throw 'Run install-runtime.ps1 first.' }
    $script = Join-Path $PSScriptRoot 'server.py'
    Start-Process -FilePath $PythonPath -ArgumentList @('-u', ('"' + $script + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'runtime\dashboard.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'runtime\dashboard.stderr.log') | Out-Null
    $deadline = (Get-Date).AddSeconds(12)
    do {
        Start-Sleep -Milliseconds 400
        try { $status = Invoke-RestMethod "$url/status" -TimeoutSec 2 } catch { $status = $null }
    } until ($status -or (Get-Date) -gt $deadline)
    if (-not $status) { throw 'Dashboard did not start. Inspect runtime\dashboard.stderr.log.' }
}
if (-not $NoOpen) { Start-Process $url }
