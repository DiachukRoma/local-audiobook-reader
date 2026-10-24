#!/bin/bash
# Launch Local Audiobook Reader from the project's virtual environment.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -x "$DIR/.venv/bin/python" ]; then
    echo "Середовище не встановлено. Спершу виконайте: $DIR/scripts/setup.sh" >&2
    exit 1
fi
export PYTHONPATH="$DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_DISABLE_TELEMETRY=1
exec "$DIR/.venv/bin/python" -m audiobook_reader "$@"
