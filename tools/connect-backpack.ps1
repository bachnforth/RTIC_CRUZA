<#
  Connect a Wi-Fi adapter to the Pocket's ELRS TX backpack and check that MAVLink forwarding works.

  Why this exists: the backpack's network name ("ExpressLRS TX Backpack XXXXXX") has changed on us
  (217F95 -> A3144A), there are other ELRS radios nearby, and Windows sometimes leaves the adapter on a
  169.254.x.x address after joining. This script handles all three; it never guesses which radio is yours.

  Usage (normal PowerShell, no admin needed):
      .\tools\connect-backpack.ps1                      # uses adapter "Wi-Fi 2"
      .\tools\connect-backpack.ps1 -Adapter "Wi-Fi 2" -Pick A3144A   # skip the menu
#>
param(
  [string]$Adapter = 'Wi-Fi 2',
  [string]$Pick = ''
)

$ErrorActionPreference = 'Stop'
$prefix = 'ExpressLRS TX Backpack'

function Get-Backpacks {
  $t = netsh wlan show networks mode=bssid interface="$Adapter" | Out-String
  $out = @()
  foreach ($b in [regex]::Split($t, '(?=SSID \d+ : )')) {
    if ($b -match "SSID \d+ : ($prefix[^\r\n]*)") {
      $ssid = $Matches[1].Trim()
      $sig = ([regex]::Matches($b, 'Signal\s+:\s+(\d+)%') | ForEach-Object { [int]$_.Groups[1].Value } | Measure-Object -Maximum).Maximum
      $out += [pscustomobject]@{ SSID = $ssid; Signal = $sig }
    }
  }
  $out
}

function Get-Ssid { (netsh wlan show interfaces | Out-String) -split "(?=\s+Name\s+:)" | Where-Object { $_ -match "Name\s+:\s+$([regex]::Escape($Adapter))\s" } | ForEach-Object { if ($_ -match '\sSSID\s+:\s+([^\r\n]+)') { $Matches[1].Trim() } } }

# 1. Already on a backpack? Otherwise scan and choose.
$current = Get-Ssid
if ($current -like "$prefix*") {
  Write-Host "[$Adapter] already on '$current'."
} else {
  $found = @(Get-Backpacks)
  if ($found.Count -eq 0) {
    Write-Host "No '$prefix' networks visible. Check: Pocket on, Backpack > Telemetry = WiFi (toggle Off/WiFi to restart it), wait 20 s."
    exit 1
  }
  Write-Host "Backpack networks in range:"
  $i = 0; $found | ForEach-Object { $i++; Write-Host ("  [{0}] {1}   signal {2}%" -f $i, $_.SSID, $_.Signal) }
  if ($Pick) { $choice = $found | Where-Object { $_.SSID -like "*$Pick" } | Select-Object -First 1 }
  else {
    $n = Read-Host "Which one is YOURS? (number; turn your Pocket off/on and watch which one disappears/returns)"
    $choice = $found[[int]$n - 1]
  }
  if (-not $choice) { Write-Host "No such network."; exit 1 }
  $profiles = netsh wlan show profiles | Out-String
  if ($profiles -notmatch [regex]::Escape($choice.SSID)) {
    $xml = @"
<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1"><name>$($choice.SSID)</name><SSIDConfig><SSID><name>$($choice.SSID)</name></SSID></SSIDConfig><connectionType>ESS</connectionType><connectionMode>manual</connectionMode><MSM><security><authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption><sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>expresslrs</keyMaterial></sharedKey></security></MSM></WLANProfile>
"@
    $tmp = Join-Path $env:TEMP 'elrs-backpack-profile.xml'
    $xml | Set-Content -Path $tmp -Encoding UTF8
    netsh wlan add profile filename="$tmp" interface="$Adapter" | Out-Null
    Remove-Item $tmp -ErrorAction SilentlyContinue
  }
  netsh wlan connect name="$($choice.SSID)" interface="$Adapter" | Out-Null
  Start-Sleep 8
}

# 2. Make sure we got a real 10.0.0.x address (Windows sometimes leaves 169.254.x.x).
$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $Adapter -ErrorAction SilentlyContinue | Select-Object -First 1).IPAddress
if (-not $ip -or $ip -like '169.254.*') {
  Write-Host "Got '$ip' - renewing DHCP..."
  ipconfig /renew "$Adapter" | Out-Null
  Start-Sleep 4
  $ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $Adapter | Select-Object -First 1).IPAddress
}
Write-Host "[$Adapter] address: $ip"

# 3. Read the backpack's own status twice, 4 s apart.
function Get-Json($path) { for ($k = 0; $k -lt 3; $k++) { try { return (Invoke-WebRequest "http://10.0.0.1$path" -UseBasicParsing -TimeoutSec 6).Content | ConvertFrom-Json } catch { Start-Sleep 2 } } }
$cfg = Get-Json '/config'
$m1 = Get-Json '/mavlink'; Start-Sleep 4; $m2 = Get-Json '/mavlink'
if (-not $m2) { Write-Host "Backpack page not reachable at http://10.0.0.1"; exit 1 }
"product : $($cfg.config.product_name)"
"enabled : $($m2.enabled)    gcs ip: $($m2.ip.gcs)"
"down    : $($m1.counters.packets_down) -> $($m2.counters.packets_down)   up: $($m1.counters.packets_up) -> $($m2.counters.packets_up)   overflows: $($m2.counters.overflows_down)"
if ($m2.enabled -and $m2.counters.packets_down -gt $m1.counters.packets_down) { Write-Host "MAVLink is flowing." -ForegroundColor Green } else { Write-Host "NOT flowing yet." -ForegroundColor Yellow }

Write-Host ""
Write-Host "BEFORE YOU USE QGC: confirm the vehicle is YOURS - flip your channel 7 mode switch and watch QGC's mode follow." -ForegroundColor Cyan
Write-Host "Other Pocket radios (with their own backpacks) are in range. If the mode does not follow, disconnect QGC."
