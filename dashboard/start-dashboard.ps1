param([string]$PythonPath = (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'), [switch]$NoOpen,
      # quadpi click-to-fly: the bridge's UDP listen address, e.g. 127.0.0.1:14551 for SITL.
      # Omit to keep the dashboard read-only.
      [string]$QuadControl,
      # quadpi arm/disarm only, through the installed bridge's bench port: a host
      # reached by SSH tunnel (e.g. 100.100.0.10), or 127.0.0.1:15760 for SITL.
      [string]$QuadBench,
      # TFW drone click-to-fly: its filter's UDP listen address, e.g. 100.100.0.6:14551
      # once its owner has installed the filter (docs/tfw-drone-dashboard-control.md).
      [string]$TfwControl)
$ErrorActionPreference = 'Stop'
if ($QuadControl -and $QuadBench) { throw 'Use -QuadControl or -QuadBench, not both.' }
if ($QuadControl) { $env:DASHBOARD_QUAD_CONTROL = $QuadControl } else { Remove-Item Env:DASHBOARD_QUAD_CONTROL -ErrorAction SilentlyContinue }
if ($QuadBench) { $env:DASHBOARD_QUAD_BENCH = $QuadBench } else { Remove-Item Env:DASHBOARD_QUAD_BENCH -ErrorAction SilentlyContinue }
if ($TfwControl) { $env:DASHBOARD_TFW_CONTROL = $TfwControl } else { Remove-Item Env:DASHBOARD_TFW_CONTROL -ErrorAction SilentlyContinue }
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
