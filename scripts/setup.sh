#!/bin/bash
# One-time setup: virtual environment, dependencies, speech model, .app bundle.
# Everything is installed inside this project folder; nothing system-wide, no sudo.
# Works on macOS/Linux and on Windows under Git Bash (the .app is built on macOS only).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
if [ -n "${PYTHON:-}" ]; then
    PY="$PYTHON"
elif command -v python3 >/dev/null 2>&1 && python3 -c '' >/dev/null 2>&1; then
    PY=python3
else
    PY=python
fi
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "Потрібен Python 3.11+"'
if [ -x .venv/bin/python ]; then
    VPY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then
    VPY=.venv/Scripts/python.exe
else
    "$PY" -m venv .venv
    if [ -x .venv/bin/python ]; then VPY=.venv/bin/python; else VPY=.venv/Scripts/python.exe; fi
fi
"$VPY" -m pip --version >/dev/null 2>&1 || "$VPY" -m ensurepip  # a venv made by uv has no pip
"$VPY" -m pip install --upgrade pip
"$VPY" -m pip install -r requirements.txt
"$VPY" scripts/download_model.py
echo
if [ "$(uname -s)" = "Darwin" ]; then
    scripts/build_app.sh
    echo "Готово. Запуск: $DIR/run.sh  або відкрийте «Local Audiobook Reader.app» у Finder."
else
    echo "Готово. Запуск: $DIR/run.sh"
fi
