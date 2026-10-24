#!/bin/bash
# One-time setup: virtual environment, dependencies, speech model, .app bundle.
# Everything is installed inside this project folder; nothing system-wide, no sudo.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "Потрібен Python 3.11+"'
if [ ! -x .venv/bin/python ]; then
    "$PY" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/download_model.py
scripts/build_app.sh
echo
echo "Готово. Запуск: $DIR/run.sh  або відкрийте «Local Audiobook Reader.app» у Finder."
