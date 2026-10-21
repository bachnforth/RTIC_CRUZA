$ErrorActionPreference = 'Stop'
# Only this local viewer shuts down; neither aircraft service is controlled.
Invoke-WebRequest -Method Post -Uri 'http://127.0.0.1:8765/shutdown' -Headers @{Origin='http://127.0.0.1:8765'} | Out-Null
