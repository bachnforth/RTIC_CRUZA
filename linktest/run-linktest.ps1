<#
.SYNOPSIS
  Runs the Cruza -> quad link test from the laptop over SSH.

.DESCRIPTION
  Every step reads linktest\plan.json (addresses, SSH logins, criteria).
  Typical day:
    .\linktest\run-linktest.ps1 deploy       # copy the tool to the Pis (once, or after changes)
    .\linktest\run-linktest.ps1 start        # start quad echoes, ground check, start the Cruza sender
    .\linktest\run-linktest.ps1 watch        # live table from the Cruza (Ctrl+C closes only the view)
    .\linktest\run-linktest.ps1 watch -Quad quadpi   # live view from a quad (works over the mesh)
    ... fly ...
    .\linktest\run-linktest.ps1 stop
    .\linktest\run-linktest.ps1 collect      # copies the logs into linktest-results\<date>
    .\linktest\run-linktest.ps1 report -CruzaLog <path to the flight's .BIN>

  Nothing here sends anything to a flight controller. Quads whose ssh login in
  plan.json is still CHANGE_ME are skipped; run the echo on them by hand.
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('deploy', 'start', 'preflight', 'watch', 'status', 'stop', 'collect', 'report')]
    [string]$Action,
    [string]$Quad,
    [string]$CruzaLog,
    [string]$Results,
    [int]$Duration = 0,
    [string]$PythonExe,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$plan = Get-Content (Join-Path $here 'plan.json') -Raw | ConvertFrom-Json
$cruza = $plan.cruza.ssh
$sshOpts = @('-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=3')
$latestFile = Join-Path $repo 'linktest-results\latest.txt'

function Get-SshOptions([string]$target) {
    $opts = @($sshOpts) + @('-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes')
    $node = @($plan.cruza) + @($plan.quads) | Where-Object { $_.ssh -eq $target } | Select-Object -First 1
    if ($node.ssh_host_key_alias) { $opts += @('-o', "HostKeyAlias=$($node.ssh_host_key_alias)") }
    if ($node.ssh_key) { $opts += @('-i', (Join-Path $env:USERPROFILE ".ssh/$($node.ssh_key)")) }
    return $opts
}

function Get-Quads {
    $list = @()
    foreach ($q in $plan.quads) {
        if ($Quad -and $q.name -ne $Quad) { continue }
        if ($q.enabled -eq $false) { continue }
        if (-not $q.ssh -or $q.ssh -like 'CHANGE_ME*') {
            Write-Warning "Skipping $($q.name): no SSH login in plan.json. Start its echo by hand (see linktest\README.md)."
            continue
        }
        $list += $q
    }
    return $list
}

function Invoke-Remote([string]$target, [string]$command) {
    # Remote output goes straight to the screen; the function returns only the exit code.
    $opts = Get-SshOptions $target
    & ssh @opts $target $command | Out-Host
    return $LASTEXITCODE
}

function Watch-Remote([string]$target, [string]$command) {
    # Interactive view: give ssh the console directly so the table redraws in place.
    $argLine = (@('-t') + @(Get-SshOptions $target) + @($target, "`"$command`"")) -join ' '
    Start-Process -FilePath 'ssh' -ArgumentList $argLine -NoNewWindow -Wait
}

function Show-Step([string]$text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }

switch ($Action) {
    'deploy' {
        $hosts = @($cruza) + @(Get-Quads | ForEach-Object { $_.ssh })
        foreach ($h in $hosts) {
            Show-Step "Copying linktest to $h"
            Invoke-Remote $h 'mkdir -p ~/linktest ~/linktest-logs' | Out-Null
            $opts = Get-SshOptions $h
            & scp @opts (Join-Path $here 'linktest.py') (Join-Path $here 'plan.json') "${h}:linktest/"
            if ($LASTEXITCODE -ne 0) { Write-Warning "Copy to $h failed." ; continue }
            Invoke-Remote $h 'python3 ~/linktest/linktest.py --version' | Out-Null
        }
    }

    'start' {
        $dur = ''
        if ($Duration -gt 0) { $dur = " --duration $Duration" }
        $targetArg = ''
        if ($Quad) {
            if ($Quad -notin @($plan.quads.name)) { throw "No quad named $Quad in plan.json" }
            $targetArg = " --target $Quad"
        }
        foreach ($q in Get-Quads) {
            Show-Step "Starting echo on $($q.name) ($($q.ssh))"
            $cmd = "mkdir -p ~/linktest-logs && cd ~/linktest && " +
                   "(setsid nohup nice -n 5 python3 linktest.py echo --name $($q.name)$dur " +
                   "> ~/linktest-logs/echo-console.log 2>&1 < /dev/null &) ; sleep 2; " +
                   "python3 linktest.py watch --role echo --once | head -5"
            Invoke-Remote $q.ssh $cmd | Out-Null
        }
        Show-Step "Ground check from the Cruza"
        $code = Invoke-Remote $cruza ("python3 ~/linktest/linktest.py preflight" + $targetArg)
        if ($code -ne 0 -and -not $Force) {
            Write-Host ''
            Write-Host 'Preflight found problems. The sender was NOT started.' -ForegroundColor Yellow
            Write-Host 'Fix them, or re-run with -Force to start anyway (e.g. a quad is intentionally off).'
            exit 1
        }
        Show-Step "Starting sender on the Cruza ($cruza)"
        $cmd = "mkdir -p ~/linktest-logs && cd ~/linktest && " +
               "(setsid nohup nice -n 5 python3 linktest.py send$dur$targetArg " +
               "> ~/linktest-logs/sender-console.log 2>&1 < /dev/null &) ; sleep 3; " +
               "python3 linktest.py watch --once"
        Invoke-Remote $cruza $cmd | Out-Null
        Write-Host ''
        Write-Host "Running. Watch it with:  .\linktest\run-linktest.ps1 watch" -ForegroundColor Green
    }

    'preflight' {
        $targetArg = ''
        if ($Quad) {
            if ($Quad -notin @($plan.quads.name)) { throw "No quad named $Quad in plan.json" }
            $targetArg = " --target $Quad"
        }
        $code = Invoke-Remote $cruza ("python3 ~/linktest/linktest.py preflight" + $targetArg)
        if ($code -ne 0) { exit $code }
    }

    'watch' {
        if ($Quad) {
            $q = $plan.quads | Where-Object { $_.name -eq $Quad }
            if (-not $q) { throw "No quad named $Quad in plan.json" }
            Watch-Remote $q.ssh 'python3 ~/linktest/linktest.py watch --role echo'
        } else {
            Watch-Remote $cruza 'python3 ~/linktest/linktest.py watch'
        }
    }

    'status' {
        Show-Step "Cruza"
        Invoke-Remote $cruza 'python3 ~/linktest/linktest.py watch --once' | Out-Null
        foreach ($q in Get-Quads) {
            Show-Step $q.name
            Invoke-Remote $q.ssh 'python3 ~/linktest/linktest.py watch --role echo --once' | Out-Null
        }
    }

    'stop' {
        Show-Step "Stopping sender on the Cruza"
        Invoke-Remote $cruza 'python3 ~/linktest/linktest.py stop --role sender' | Out-Null
        foreach ($q in Get-Quads) {
            Show-Step "Stopping echo on $($q.name)"
            Invoke-Remote $q.ssh 'python3 ~/linktest/linktest.py stop --role echo' | Out-Null
        }
    }

    'collect' {
        if (-not $Results) { $Results = Join-Path $repo ('linktest-results\' + (Get-Date -Format 'yyyy-MM-dd_HHmm')) }
        New-Item -ItemType Directory -Force -Path $Results | Out-Null
        $sources = @(@{ name = 'cruza'; ssh = $cruza; role = 'sender' })
        foreach ($q in Get-Quads) { $sources += @{ name = $q.name; ssh = $q.ssh; role = 'echo' } }
        foreach ($s in $sources) {
            Show-Step "Copying $($s.role) logs from $($s.name)"
            # Every session of this role from the last 12 hours (an echo restarted
            # mid-test leaves two folders; the report stitches them together).
            $opts = Get-SshOptions $s.ssh
            $remote = @(& ssh @opts $s.ssh "find ~/linktest-logs -mindepth 1 -maxdepth 1 -type d -mmin -720 -name '*_$($s.role)_*'")
            $remote = @($remote | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() })
            if ($remote.Count -eq 0) { Write-Warning "No recent $($s.role) session on $($s.name)."; continue }
            $dest = Join-Path $Results $s.name
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            foreach ($folder in $remote) {
                & scp @opts -r "$($s.ssh):$folder" $dest
                if ($LASTEXITCODE -ne 0) { Write-Warning "Copy of $folder from $($s.name) failed." }
            }
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $latestFile) | Out-Null
        Set-Content -Path $latestFile -Value $Results
        Write-Host ''
        Write-Host "Logs saved in $Results" -ForegroundColor Green
        Write-Host 'Next: pull the Cruza flight log (tools\pull-flight-logs.py), then run "report -CruzaLog <file>.BIN".'
    }

    'report' {
        if (-not $PythonExe) {
            $bundled = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
            if (Test-Path -LiteralPath $bundled) { $PythonExe = $bundled }
            else { $PythonExe = 'python' }
        }
        if (-not $Results) {
            if (Test-Path $latestFile) { $Results = (Get-Content $latestFile -Raw).Trim() }
            else { throw 'Pass -Results <folder from collect>' }
        }
        $deps = Join-Path $repo '.flightlog-deps'
        & $PythonExe -c "import sys; sys.path.insert(0, r'$deps'); import matplotlib, pymavlink" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Show-Step 'Installing report libraries into .flightlog-deps (one time)'
            & $PythonExe -m pip install --target $deps -r (Join-Path $repo 'tools\flightlog-requirements.txt')
            if ($LASTEXITCODE -ne 0) { throw 'Report dependency installation failed' }
        }
        $pyArgs = @((Join-Path $here 'report.py'), '--collected', $Results)
        if ($CruzaLog) { $pyArgs += @('--cruza-log', $CruzaLog) }
        else { Write-Warning 'No -CruzaLog given: the report cannot show distance or the airborne period.' }
        & $PythonExe @pyArgs
        if ($LASTEXITCODE -eq 0) { Start-Process (Join-Path $Results 'report\report.html') }
    }
}
