"""Draw the application icon (1024x1024 PNG) with Qt; no external assets."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402

app = QGuiApplication([])
size = 1024
img = QImage(size, size, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)

grad = QLinearGradient(0, 0, 0, size)
grad.setColorAt(0, QColor("#2f6fd6"))
grad.setColorAt(1, QColor("#f2b81f"))
p.setBrush(QBrush(grad))
p.setPen(Qt.NoPen)
p.drawRoundedRect(QRectF(80, 80, 864, 864), 190, 190)

# Open book
p.setBrush(QColor(255, 255, 255, 240))
for sign in (-1, 1):
    path = QPainterPath()
    path.moveTo(512, 380)
    path.cubicTo(512 + sign * 120, 330, 512 + sign * 230, 330, 512 + sign * 300, 360)
    path.lineTo(512 + sign * 300, 700)
    path.cubicTo(512 + sign * 230, 670, 512 + sign * 120, 670, 512, 720)
    path.closeSubpath()
    p.drawPath(path)

# Sound waves above the book
pen = QPen(QColor(255, 255, 255, 235), 34, Qt.SolidLine, Qt.RoundCap)
p.setPen(pen)
p.setBrush(Qt.NoBrush)
for r in (90, 160):
    p.drawArc(QRectF(512 - r, 330 - r, 2 * r, 2 * r), 45 * 16, 90 * 16)
p.setPen(Qt.NoPen)
p.setBrush(QColor(255, 255, 255, 235))
p.drawEllipse(QPointF(512, 318), 26, 26)
p.end()
img.save(sys.argv[1])
