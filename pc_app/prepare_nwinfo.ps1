# Download a pinned official NWinfo CLI release and verify its SHA-256.
# This is the built-in CPU/GPU/SMART sensor engine, NOT the LHM backend.
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "dist\nwinfo")
)
$ErrorActionPreference = "Stop"
$Url = "https://github.com/a1ive/nwinfo/releases/download/v1.6.6/NWinfoLite.zip"
$ExpectedSha256 = "ecac2433c5157a0dbc7263fc13c19f75631403b461cc4bf0ede260e8fdaed904"

$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$archive = Join-Path ([System.IO.Path]::GetTempPath()) "FanARGB-NWinfoLite-v1.6.6.zip"
try {
    Invoke-WebRequest -Uri $Url -OutFile $archive -UseBasicParsing
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256) {
        throw "NWinfo SHA256 mismatch: expected $ExpectedSha256, actual $actual"
    }
    if (Test-Path $OutputDirectory) {
        Remove-Item -LiteralPath $OutputDirectory -Recurse -Force
    }
    New-Item -Path $OutputDirectory -ItemType Directory -Force | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $OutputDirectory -Force
    $cli = Get-ChildItem -LiteralPath $OutputDirectory -Recurse -File |
        Where-Object { $_.Name -ieq "nwinfo.exe" } |
        Select-Object -First 1
    if (-not $cli) {
        throw "NWinfoLite archive did not contain nwinfo.exe"
    }

    # Exclude unneeded alternative monitoring providers: LHM is NOT bundled
    # or used. Keep vendor's CPU/GPU/SMART drivers and CLI files in place.
    Get-ChildItem -LiteralPath $OutputDirectory -Recurse -File |
        Where-Object { $_.Name -match '^(liblhm|LibreHardwareMonitorLib|OpenHardwareMonitorLib)\.(dll|exe)$' } |
        Remove-Item -Force
    Write-Host ("Verified NWinfo v1.6.6, executable: " + $cli.FullName)
    Get-ChildItem -LiteralPath $OutputDirectory -Recurse -File |
        Select-Object FullName,Length | Format-Table | Out-String | Write-Host
}
finally {
    if (Test-Path $archive) { Remove-Item -LiteralPath $archive -Force }
}
