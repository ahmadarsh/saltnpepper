#!/bin/zsh
set -eu
cd "$(dirname "$0")/.."

trap 'echo "Setup failed. See the error above."; read "?Press Return to close."' ZERR
if ! command -v python3 >/dev/null 2>&1; then
  echo "Install Python 3.9 or newer from https://www.python.org/downloads/macos/, then run this again."
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 9), "Python 3.9 or newer is required"'
if [ ! -x .venv/bin/python3 ]; then
  python3 -m venv .venv
fi
.venv/bin/python3 -m pip install --upgrade pip
.venv/bin/python3 -m pip install -r requirements.txt
.venv/bin/python3 -c 'import numpy, scipy, matplotlib, gmsh; gmsh.initialize(); gmsh.finalize(); print("Native CAD and solver dependencies are ready.")'
echo "Setup complete. Open Start Salt and Pepper.command to launch."
read "?Press Return to close."
