# PyInstaller recipe for a self-contained build (no Python or .venv needed on the target computer).
# Used by scripts/build_macos.sh and scripts/build_windows.ps1; not meant to be run by hand.
#
# Environment:
#   BUNDLE_MODEL=0   build without the speech model (the app offers to download it on first start)
#                    and, on Windows, without the OCR models (downloaded on first OCR)
#   APP_ICON=<path>  .icns (macOS) or .ico (Windows) application icon

import os
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
APP_NAME = "Local Audiobook Reader"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
MODEL_DIR = ROOT / "models" / "supertonic-3"
OCR_MODEL_DIR = ROOT / "models" / "rapidocr"
ICON = os.environ.get("APP_ICON") or None

datas = [(str(ROOT / "assets" / "icon.png"), "assets")]
datas += collect_data_files("supertonic")
# PyMuPDF loads its page-layout models (pymupdf/layout) from files at runtime; skip its C headers/static libs.
datas += collect_data_files("pymupdf", excludes=["mupdf-devel/**"])
if os.environ.get("BUNDLE_MODEL", "1") != "0":
    if not (MODEL_DIR / "onnx").is_dir():
        raise SystemExit(f"Speech model not found in {MODEL_DIR}; run scripts/download_model.py or set BUNDLE_MODEL=0")
    for path in MODEL_DIR.rglob("*"):
        if path.is_file() and not path.name.startswith(".") and ".cache" not in path.parts:
            datas.append((str(path), str(Path("models/supertonic-3") / path.parent.relative_to(MODEL_DIR))))
if sys.platform != "darwin":
    # RapidOCR reads its config.yaml / default_models.yaml at runtime; its models live in models/rapidocr.
    datas += collect_data_files("rapidocr", excludes=["models/**"])
    if os.environ.get("BUNDLE_MODEL", "1") != "0":
        if not any(OCR_MODEL_DIR.glob("*.onnx")):
            raise SystemExit(f"OCR models not found in {OCR_MODEL_DIR}; run scripts/download_model.py or set BUNDLE_MODEL=0")
        for path in OCR_MODEL_DIR.iterdir():
            if path.is_file():
                datas.append((str(path), "models/rapidocr"))

# num2words picks its language module by name at runtime.
hiddenimports = collect_submodules("num2words")
hiddenimports += collect_submodules("pymupdf")  # includes optional extension modules such as pymupdf._tgif
if sys.platform == "darwin":
    hiddenimports += ["Foundation", "objc", "Vision"]  # Apple Vision OCR

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "supertonic.server", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=ICON,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier="local.audiobook-reader",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.books",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Book",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": [
                    "com.adobe.pdf",
                    "org.idpf.epub-container",
                    "public.plain-text",
                    "org.openxmlformats.wordprocessingml.document",
                ],
            }],
        },
    )
