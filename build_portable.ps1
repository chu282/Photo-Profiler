$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:TEMP = Join-Path $PSScriptRoot '.temp'
$env:TMP = $env:TEMP
$env:PYINSTALLER_CONFIG_DIR = Join-Path $env:TEMP 'pyinstaller'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$appManifest = Join-Path $PSScriptRoot 'app.manifest'
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --onedir --windowed --name 'Photo Profiler' --manifest $appManifest --distpath dist --workpath build --specpath build portable.py
if ($LASTEXITCODE -ne 0) { throw 'Portable build failed.' }
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --onefile --windowed --name 'PhotoProfilerUpdate' --distpath build\update --workpath build\update-work --specpath build update_helper.py
if ($LASTEXITCODE -ne 0) { throw 'Updater helper build failed.' }
