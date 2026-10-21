$ErrorActionPreference='Stop'
$log=Join-Path $PSScriptRoot 'runtime/mesh-routes.log'
try {
 $adapter=Get-NetAdapter -Name 'Wi-Fi 2'
 if($adapter.MacAddress -ne '00-C0-CA-B8-3F-80'){throw 'Unexpected mesh adapter; no routes added'}
 foreach($target in @('10.223.196.130/32','10.223.196.103/32','10.223.79.20/32')) {
  if(-not(Get-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix $target -ErrorAction SilentlyContinue)) {
   New-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix $target -NextHop 0.0.0.0 -RouteMetric 1 -PolicyStore ActiveStore | Out-Null
  }
 }
 'Three temporary mesh host routes installed.' | Set-Content -LiteralPath $log
} catch { $_.Exception.Message | Set-Content -LiteralPath $log; exit 1 }
