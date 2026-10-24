"""Convert the 1024 px PNG icon into a multi-size Windows .ico (PNG-compressed entries, Qt only).

Usage: python scripts/make_ico.py assets/icon.png build/icon.ico
"""

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)

app = QGuiApplication([])
source = QImage(sys.argv[1])
if source.isNull():
    raise SystemExit(f"Cannot read {sys.argv[1]}")

images = []
for size in SIZES:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(buffer, "PNG")
    images.append((size, bytes(data)))

header = struct.pack("<HHH", 0, 1, len(images))
offset = len(header) + 16 * len(images)
entries, payload = b"", b""
for size, png in images:
    dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
    entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(payload))
    payload += png

os.makedirs(os.path.dirname(os.path.abspath(sys.argv[2])), exist_ok=True)
with open(sys.argv[2], "wb") as fh:
    fh.write(header + entries + payload)
print(f"Створено: {sys.argv[2]}")
