# Build a standalone Windows desktop executable (Python 3.11+).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -3 -m pip install -r requirements.txt pyinstaller
py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --paths $PSScriptRoot --name FanARGBControl main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
py -3 verify_windows_bundle.py dist/FanARGBControl.exe
if ($LASTEXITCODE -ne 0) { throw "Windows bundle validation failed" }
Write-Host "Executable: $PSScriptRoot\dist\FanARGBControl.exe"
