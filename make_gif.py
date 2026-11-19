"""Renders assets/demo.gif offscreen (no desktop content): working -> done -> waiting."""
import json, os, sys, tempfile, time
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
import clawd, i18n
tmp = Path(tempfile.mkdtemp())
clawd.STATE_FILE, clawd.CONFIG_FILE, clawd.STATUS_FILE = tmp/"s.json", tmp/"c.json", tmp/"st.json"
clawd.CONFIG_FILE.write_text(json.dumps({"lang": "en", "gadgets": False, "sound": False}))
app = QApplication(sys.argv)
pet = clawd.Clawd()
i18n.set_lang("en")
pet.sound = False
frames, t0 = [], time.time()
def state(s):
    clawd.STATE_FILE.write_text(json.dumps({"state": s, "ts": time.time()}))
script = [(0.3, "working"), (4.0, "done"), (7.5, "attention")]
END = 11.5
def tick():
    el = time.time() - t0
    while script and el >= script[0][0]:
        state(script.pop(0)[1])
    frames.append(pet.grab().toImage().copy())
    if el > END:
        app.quit()
t = QTimer(); t.timeout.connect(tick); t.start(80)
app.exec()
from PIL import Image
out = []
for im in frames[16:]:
    w, h = im.width(), im.height()
    im = im.convertToFormat(QImage.Format_RGBA8888)
    pil = Image.frombytes("RGBA", (w, h), bytes(im.constBits()))
    bg = Image.new("RGBA", (w, h), (36, 38, 46, 255)); bg.alpha_composite(pil)
    out.append(bg.crop((w//2-130, h-170, w//2+130, h)).convert("RGB").quantize(colors=48, dither=Image.Dither.NONE))
out[0].save("assets/demo.gif", save_all=True, append_images=out[1:], duration=80, loop=0, optimize=True)
print(len(out), os.path.getsize("assets/demo.gif"))
