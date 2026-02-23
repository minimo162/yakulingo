$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "stop is deprecated."
Write-Host "LocaLingo now stops automatically after browser close (client idle timeout)."
Write-Host "To force refresh, run start.bat again. It will restart the server process."
