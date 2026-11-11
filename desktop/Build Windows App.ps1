[CmdletBinding()]
param(
  [string]$KiCadRoot = "",
  [string]$ExampleProject = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" } }
if ($env:OS -ne "Windows_NT") { throw "Run this script on Windows x64." }
foreach ($tool in @("cargo", "node", "npm")) {
  if (!(Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing $tool. Read README.md." }
}
if ($ExampleProject -and !(Test-Path $ExampleProject)) { throw "Missing optional example ZIP: $ExampleProject" }
if ($KiCadRoot) { $env:KICAD_INSTALL_ROOT = (Resolve-Path $KiCadRoot).Path }
if (!(Test-Path ".venv/Scripts/python.exe")) { py -3.11 -m venv .venv; Check-Exit }
& .venv/Scripts/python.exe -c "import struct,sys; assert struct.calcsize('P')==8 and sys.version_info >= (3,11), 'Use 64-bit Python 3.11 or newer'"
Check-Exit
& .venv/Scripts/python.exe -m pip install --upgrade pip
Check-Exit
& .venv/Scripts/python.exe -m pip install -r requirements.txt -r desktop/requirements-build.txt
Check-Exit
node tools/check_windows_workspace_ui.cjs
Check-Exit
& .venv/Scripts/python.exe -m unittest pcb_simulator.test_windows_workspace pcb_simulator.test_workspace_archive pcb_simulator.test_preview_quality pcb_simulator.test_through_hole_pads pcb_simulator.test_kicad_workbench pcb_simulator.test_kicad_preview pcb_simulator.test_kicad_details pcb_simulator.test_kicad_import_speed pcb_simulator.test_odb_preview pcb_simulator.test_odb_symbols pcb_simulator.test_server pcb_simulator.test_backend pcb_simulator.viewer.test_results
Check-Exit
cargo fetch --locked --manifest-path desktop/src-tauri/Cargo.toml
Check-Exit
& .venv/Scripts/python.exe desktop/bundle_kicad_windows.py
Check-Exit
if ($ExampleProject) {
  & .venv/Scripts/python.exe desktop/build_backend.py --example-project $ExampleProject
} else {
  & .venv/Scripts/python.exe desktop/build_backend.py
}
Check-Exit
& .venv/Scripts/python.exe desktop/smoke_test.py desktop/backend-dist/salt-pepper-backend.exe
Check-Exit
# Stage the final resource layout. The smoke test removes Python/KiCad overrides
# and PATH, proving that this candidate uses its own runtime and embedded example.
$package = "desktop/backend-build/windows-package-test"
if (Test-Path $package) { Remove-Item -Recurse -Force $package }
New-Item -ItemType Directory -Force "$package/backend" | Out-Null
Copy-Item desktop/backend-dist/salt-pepper-backend.exe "$package/backend/"
Copy-Item -Recurse desktop/kicad-runtime "$package/kicad"
New-Item -ItemType Directory -Force dist/windows | Out-Null
if ($ExampleProject) {
  & .venv/Scripts/python.exe desktop/smoke_test_bundled_example.py "$package/backend/salt-pepper-backend.exe" --report dist/windows/bundled-example-verification.json
} else {
  & .venv/Scripts/python.exe desktop/smoke_test_kicad.py "$package/backend/salt-pepper-backend.exe" --kicad-cli "$package/kicad/bin/kicad-cli.exe" --board examples/two-layer-demo.kicad_pcb --sample demo --report dist/windows/bundled-example-verification.json
}
Check-Exit
$env:SALT_PEPPER_TEST_BACKEND = (Resolve-Path "$package/backend/salt-pepper-backend.exe").Path
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml bundled_backend_starts_and_stops_without_a_window
Check-Exit
Push-Location desktop
try {
  npm ci; Check-Exit
  npm run build -- --config src-tauri/tauri.windows.conf.json; Check-Exit
} finally { Pop-Location }
Copy-Item desktop/src-tauri/target/release/bundle/nsis/*-setup.exe dist/windows/
Get-ChildItem dist/windows/*-setup.exe | ForEach-Object {
  $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  [System.IO.File]::WriteAllText($_.FullName + ".sha256", "$hash  $($_.Name)`n")
}
Write-Host "Built: dist/windows (Windows x64 installer). Complete the README verification checks before calling it verified."
