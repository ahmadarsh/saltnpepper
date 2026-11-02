#!/bin/zsh
set -eu
cd "$(dirname "$0")/.."
trap 'echo "Startup failed. See the error above."; read "?Press Return to close."' ZERR
if [ ! -x .venv/bin/python3 ]; then
  echo "Run Setup Salt and Pepper.command first to install the macOS backend."
  read "?Press Return to close."
  exit 1
fi
.venv/bin/python3 -c 'import numpy, scipy, matplotlib, gmsh; gmsh.initialize(); gmsh.finalize()'
exec .venv/bin/python3 pcb_simulator/server.py "$@"

