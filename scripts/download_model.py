"""Download the Supertonic 3 model (~385 MB) into ./models/supertonic-3 if missing."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from audiobook_reader.storage.settings import DEFAULT_MODEL_DIR  # noqa: E402
from audiobook_reader.tts.supertonic_engine import (APPROX_DOWNLOAD_MB, MODEL_REPO, download_model,  # noqa: E402
                                                    model_present)

target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MODEL_DIR
if model_present(target):
    print(f"Модель уже є: {target}")
else:
    print(f"Завантаження {MODEL_REPO} (≈{APPROX_DOWNLOAD_MB} МБ) у {target} …")
    download_model(target)
    print("Готово.")
