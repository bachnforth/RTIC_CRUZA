param([ValidateSet('start','stop','status')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$state = Join-Path $PSScriptRoot '../output/mesh-relay'
$scriptPath = Join-Path $PSScriptRoot 'mesh-relay.py'
$pidPath = Join-Path $state 'process-id.txt'
$statusPath = Join-Path $state 'status.json'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$process = $null
if (Test-Path $pidPath) {
    $savedId = [int](Get-Content $pidPath -Raw)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$savedId"
    if ($process -and $process.CommandLine -notlike "*$scriptPath*") {
        throw 'Saved process ID belongs to another command; refusing to manage it.'
    }
}
switch ($Action) {
    'start' {
        if ($process) { throw 'Relay is already running.' }
        $pythonExe = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
        if (-not (Test-Path $pythonExe)) { throw 'Bundled Python not found.' }
        $arguments = '"{0}" --config "{1}" --status "{2}"' -f $scriptPath,(Join-Path $PSScriptRoot 'mesh-relay.json'),$statusPath
        $started = Start-Process -FilePath $pythonExe -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $state 'stdout.log') -RedirectStandardError (Join-Path $state 'stderr.log')
        $started.Id | Set-Content $pidPath
        Start-Sleep -Seconds 2
        if ($started.HasExited) { throw (Get-Content (Join-Path $state 'stderr.log') -Raw) }
        "Relay running (PID $($started.Id)). Stop: .\linktest\mesh-relay.ps1 stop"
    }
    'stop' {
        if ($process) { Stop-Process -Id $process.ProcessId -ErrorAction Stop }
        Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
        'Relay stopped. No network settings were changed.'
    }
    'status' {
        if ($process) { "Running (PID $($process.ProcessId))" } else { 'Stopped' }
        if (Test-Path $statusPath) { Get-Content $statusPath }
    }
}
