# Run from an interactive PowerShell terminal. The sudo password stays in SSH.
$ErrorActionPreference = 'Stop'
$sshKey = Join-Path $env:USERPROFILE '.ssh/id_ed25519_rpi'
$remoteCommand = 'umask 077; tailscale debug prefs > ~/linktest/tailscale-before-mesh-$(date -u +%Y%m%dT%H%M%SZ).json; sudo tailscale set --accept-routes=true && ip -4 route get 10.223.79.20'
& ssh -t -i $sshKey -o StrictHostKeyChecking=yes -o HostKeyAlias=10.229.125.15 -o ConnectTimeout=10 ebach@100.100.0.58 $remoteCommand
if ($LASTEXITCODE -ne 0) { throw 'Cruza route acceptance was not confirmed.' }
