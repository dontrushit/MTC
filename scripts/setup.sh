#!/usr/bin/env bash
# Bootstrap MTC on macOS/Linux: create .venv, install dependencies, run check_env.
# Usage: scripts/setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."

pick_python() {
  local candidate
  for candidate in python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PY="$(pick_python)"; then
  echo "Python 3.11 or 3.12 not found (3.13+ is not supported)." >&2
  echo "Arch/CachyOS: sudo pacman -S python312   Debian/Ubuntu: sudo apt install python3.12 python3.12-venv" >&2
  exit 1
fi

echo "Using $("$PY" --version) at $(command -v "$PY")"

need_venv=1
if [[ -x .venv/bin/python ]]; then
  if .venv/bin/python -c 'import sys; raise SystemExit(0 if (3, 11) <= (sys.version_info[:2]) < (3, 13) else 1)'; then
    need_venv=0
  fi
fi

if [[ "$need_venv" == "1" ]]; then
  echo "Creating .venv"
  rm -rf .venv
  "$PY" -m venv .venv
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

EXTRAS="core,dev,audio,asr,llm,api,ui"

if command -v uv >/dev/null 2>&1; then
  INSTALL=(uv pip install -p .venv)
else
  echo "uv not found, using pip"
  .venv/bin/python -m pip install --upgrade pip
  INSTALL=(.venv/bin/python -m pip install)
fi

# Without an NVIDIA GPU, CUDA wheels (~2–3 GB) are useless — install CPU torch first.
if [[ "$(uname)" == "Linux" ]] && ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "No NVIDIA GPU detected: installing CPU-only torch"
  "${INSTALL[@]}" torch --index-url https://download.pytorch.org/whl/cpu
fi

echo "Installing dependencies"
"${INSTALL[@]}" -e ".[${EXTRAS}]"

echo
.venv/bin/python scripts/check_env.py
