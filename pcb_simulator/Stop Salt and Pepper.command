#!/bin/zsh
set -eu
cd "$(dirname "$0")/.."
if [ -x ".venv/bin/python3" ]; then
  ".venv/bin/python3" pcb_simulator/server.py --stop "$@"
else
  python3 pcb_simulator/server.py --stop "$@"
fi

