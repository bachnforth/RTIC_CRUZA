param([string]$PythonPath = (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'),
      [Parameter(ValueFromRemainingArguments = $true)][string[]]$AtrArgs)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot 'runtime\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { & (Join-Path $PSScriptRoot 'install-atr.ps1') -PythonPath $PythonPath }
# The dashboard page pulls video from the aircraft; recognition reads its local copy.
& (Join-Path $PSScriptRoot '..\dashboard\start-dashboard.ps1') -PythonPath $PythonPath
$probe = New-Object Net.Sockets.TcpClient
try { $probe.Connect('127.0.0.1', 8554) } catch {
    throw 'Dashboard has no recognition output. Run dashboard\stop-dashboard.ps1 once, then start again.'
} finally { $probe.Dispose() }
& $python -u (Join-Path $PSScriptRoot 'atr.py') @AtrArgs
