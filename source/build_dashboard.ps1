$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\tools\update_upstream.py"
if ($LASTEXITCODE -ne 0) { throw 'Upstream compatibility check failed; review the adapter before building' }
& "$PSScriptRoot\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name 'Cyberleek Watcher' --add-data "$PSScriptRoot\upstream\cyberleek_watcher.py;upstream" --add-data "$PSScriptRoot\upstream\compatibility.json;upstream" cyberleek_dashboard.py
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
if (-not (Test-Path -LiteralPath "$PSScriptRoot\dist\watcher_config.json")) {
    Copy-Item -LiteralPath "$PSScriptRoot\watcher_config.json" -Destination "$PSScriptRoot\dist\watcher_config.json"
}
