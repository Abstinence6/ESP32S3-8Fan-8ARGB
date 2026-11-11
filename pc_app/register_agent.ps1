# Install background user-logon task. Uses the packaged EXE in pc_app/dist.
$ErrorActionPreference = 'Stop'
$exe = Join-Path $PSScriptRoot 'dist\FanARGBControl.exe'
if (-not (Test-Path $exe)) { throw 'Build dist\FanARGBControl.exe first.' }
$taskName = 'FanARGBControl Headless Agent'
$command = '"' + (Resolve-Path $exe).Path + '" --headless'
& schtasks.exe /Create /SC ONLOGON /TN $taskName /TR $command /F
if ($LASTEXITCODE -ne 0) { throw 'Unable to create Scheduled Task.' }
Write-Host 'Installed. Do not run GUI and agent concurrently; both need the same COM port.'
