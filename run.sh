#!/bin/bash
# Launch Local Audiobook Reader from the project's virtual environment.
# Works on macOS/Linux and on Windows under Git Bash (venv in .venv/Scripts).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$DIR/.venv/bin/python" ]; then
    PY="$DIR/.venv/bin/python"
    SRC="$DIR/src"
    SEP=":"
elif [ -x "$DIR/.venv/Scripts/python.exe" ]; then
    PY="$DIR/.venv/Scripts/python.exe"
    SRC="$(cygpath -w "$DIR/src")"
    SEP=";"
else
    echo "Середовище не встановлено. Спершу виконайте: $DIR/scripts/setup.sh" >&2
    exit 1
fi
export PYTHONPATH="$SRC${PYTHONPATH:+$SEP$PYTHONPATH}"
export HF_HUB_DISABLE_TELEMETRY=1
exec "$PY" -m audiobook_reader "$@"
