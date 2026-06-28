$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..")

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --onefile `
    --distpath "." `
    --workpath "build\launcher" `
    --specpath "build\launcher" `
    --name "EcuadorPublicSpendingMonitor" `
    launcher.py

Write-Host "Ejecutable creado en .\EcuadorPublicSpendingMonitor.exe"
