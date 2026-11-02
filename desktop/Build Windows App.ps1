$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" } }
if (!(Test-Path ".venv/Scripts/python.exe")) { py -3 -m venv .venv; Check-Exit }
& .venv/Scripts/python.exe -m pip install -r requirements.txt -r desktop/requirements-build.txt
Check-Exit
& .venv/Scripts/python.exe desktop/build_backend.py
Check-Exit
& .venv/Scripts/python.exe desktop/smoke_test.py desktop/backend-dist/salt-pepper-backend.exe
Check-Exit
$env:SALT_PEPPER_TEST_BACKEND = (Resolve-Path "desktop/backend-dist/salt-pepper-backend.exe").Path
cargo test --manifest-path desktop/src-tauri/Cargo.toml bundled_backend_starts_and_stops_without_a_window
Check-Exit
Push-Location desktop
try {
  npm ci; Check-Exit
  npm run build; Check-Exit
} finally { Pop-Location }
New-Item -ItemType Directory -Force dist/windows | Out-Null
Copy-Item desktop/src-tauri/target/release/bundle/nsis/*-setup.exe dist/windows/
Write-Host "Ready: dist/windows (Windows x64 installer)"
