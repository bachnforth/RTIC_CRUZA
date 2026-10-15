$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot 'runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$zip = Join-Path $runtime 'mediamtx.zip'
Invoke-WebRequest -Uri 'https://github.com/bluenviron/mediamtx/releases/download/v1.21.2/mediamtx_v1.21.2_windows_amd64.zip' -OutFile $zip
$actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne 'a84224f5a490855684e62ba6fb71e80ea2a5e16aed61883bb58380290e93e467') { throw 'MediaMTX checksum mismatch; not extracting.' }
Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $runtime 'mediamtx-v1.21.2') -Force
Write-Output 'MediaMTX v1.21.2 downloaded from the official release and SHA256 verified.'
