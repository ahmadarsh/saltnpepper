#!/bin/zsh
set -eu
cd "$(dirname "$0")/.."
if [ -x "$PWD/.build-tools/cargo/bin/cargo" ]; then
  export CARGO_HOME="$PWD/.build-tools/cargo"
  export RUSTUP_HOME="$PWD/.build-tools/rustup"
  export PATH="$CARGO_HOME/bin:$PATH"
fi
command -v cargo >/dev/null || { echo "Install Rust from https://rustup.rs/ first."; exit 1; }
export PYINSTALLER_CONFIG_DIR="$PWD/desktop/backend-build/cache"
.venv/bin/python3 desktop/bundle_kicad.py
.venv/bin/python3 desktop/build_backend.py "$@"
cd desktop
npm ci --cache ../.build-tools/npm-cache
npm run build -- --bundles app
mkdir -p ../dist
if [ -d '../dist/Salt and Pepper.app' ]; then
  python3 -c 'import shutil; shutil.rmtree("../dist/Salt and Pepper.app")'
fi
ditto 'src-tauri/target/release/bundle/macos/Salt and Pepper.app' '../dist/Salt and Pepper.app'
ditto -c -k --sequesterRsrc --keepParent '../dist/Salt and Pepper.app' '../dist/Salt and Pepper Mac.zip'
app_version=$(../.venv/bin/python3 -c 'import json; print(json.load(open("package.json"))["version"])')
../.venv/bin/python3 create_macos_dmg.py \
  --app '../dist/Salt and Pepper.app' \
  --output "../dist/Salt-and-Pepper-${app_version}-macOS-arm64.dmg" \
  --version "$app_version"
echo "Ready: dist/Salt and Pepper.app and DMG"
