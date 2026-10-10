$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name 'Cyberleek Watcher' cyberleek_dashboard.py
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
if (-not (Test-Path -LiteralPath "$PSScriptRoot\dist\watcher_config.json")) {
    Copy-Item -LiteralPath "$PSScriptRoot\watcher_config.json" -Destination "$PSScriptRoot\dist\watcher_config.json"
}
