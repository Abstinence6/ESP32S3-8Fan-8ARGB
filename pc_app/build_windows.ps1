# Build a standalone Windows desktop executable (Python 3.11+).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -3 -m pip install -r requirements.txt pyinstaller
py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --name FanARGBControl main.py
Write-Host "Executable: $PSScriptRoot\dist\FanARGBControl.exe"
