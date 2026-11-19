"""Renders assets/clawd.ico (and a 256px png) from the in-game sprite."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtCore import Qt

app = QGuiApplication(sys.argv)
import clawd

os.makedirs("assets", exist_ok=True)
img = QImage(256, 256, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.translate(0, 256 * 0.5 - 15 * 10.5 / 2 * 1.0)
p.scale(10.66, 10.66)
clawd.draw_sprite(p, clawd.base_pose(0))
p.end()
img.save("assets/clawd.png")
from PIL import Image
Image.open("assets/clawd.png").save("assets/clawd.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok")
