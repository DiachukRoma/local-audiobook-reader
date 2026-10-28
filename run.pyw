"""Windows launcher without a console window: .venv\\Scripts\\pythonw.exe run.pyw (used by the desktop shortcut,
see scripts/create_shortcut.ps1). On macOS/Linux use run.sh."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from audiobook_reader.app import main  # noqa: E402

sys.exit(main(sys.argv))
