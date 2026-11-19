"""Гаджеты вокруг Clawd: пиксельные иконки и опрос зарядов устройств.

Заряд читается только у того, что подключено прямо сейчас:
  * геймпад Xbox - через XInput (и точный процент из свойств Bluetooth, если Windows его отдаёт)
  * телефон / TWS-наушники по Bluetooth - только если Windows знает их заряд (часто не знает)
  * батарея ноутбука - через GetSystemPowerStatus
  * наушники HyperX Cloud III Wireless читает сам clawd.py
Всё остальное (кружка, фикус, книги, мышка) - просто мебель.
"""
import ctypes
import json
import re
import subprocess
import threading
import time

from PySide6.QtGui import QColor

PAL = {
    "K": (46, 48, 60), "X": (118, 124, 144), "L": (176, 182, 200), "R": (225, 60, 60), "G": (90, 200, 120),
    "B": (90, 150, 240), "Y": (245, 205, 80), "W": (240, 240, 245), "S": (120, 200, 255),
    "O": (217, 127, 89), "N": (140, 90, 60), "P": (240, 130, 170), "T": (70, 190, 190),
}

ICONS = {
    "gamepad": ["..KKKKKKKK..",
                ".KXXXXXXXXK.",
                "KXXKXXXXYXXK",
                "KXKKKXXYXBXK",
                "KXXKXXXXGXXK",
                "KXXXKKKKXXXK",
                ".KKK......KK"],
    "headset": ["..LLLLLL..",
                ".L......L.",
                "L........L",
                "LRL....LRL",
                "LRL....LRL",
                "LLL....LLL"],
    "phone": ["KKWWKK",
              "KSSSSK",
              "KSSSSK",
              "KSBBSK",
              "KSSSSK",
              "KSSSSK",
              "KSSSSK",
              "KSSSSK",
              "KKKKKK"],
    "earbuds": [".KKKKKK.",
                "KWWWWWWK",
                "KWWKGWWK",
                "KWWKKWWK",
                "KWWWWWWK",
                ".KKKKKK."],
    "laptop": [".KKKKKKKKKK.",
               ".KSSSSSSSSK.",
               ".KSSSSBBSSK.",
               ".KSSSSSSSSK.",
               ".KKKKKKKKKK.",
               "KXXXXXXXXXXK",
               "KKKKKKKKKKKK"],
    "mouse": [".KKKK.",
              "KXXLXK",
              "KXXLXK",
              "KXXXXK",
              "KXXXXK",
              "KXXXXK",
              "KXXXXK",
              ".KKKK."],
    "mug": ["KWWWWK..",
            "KWWWWKK.",
            "KWWWWK.K",
            "KWWWWKK.",
            "KWWWWK.."],
    "plant": ["..G.G..",
              ".GGGGG.",
              "G.GGG.G",
              "..GGG..",
              "...G...",
              ".NNNNN.",
              "..NNN.."],
    "books": ["RRRRRRRR..",
              "KKKKKKKK..",
              ".BBBBBBBB.",
              ".KKKKKKKK.",
              "TTTTTTTTT.",
              "KKKKKKKKK."],
}

# мебель: что рисовать всегда, и как это назвать при наведении
DECOR = [("mug", "d_mug"), ("plant", "d_plant"), ("books", "d_books"), ("mouse", "d_mouse")]   # (icon, translation key)
NAMES = {"gamepad": "n_gamepad", "phone": "n_phone", "earbuds": "n_earbuds", "laptop": "n_laptop", "headset": "n_headset"}   # translation keys


def icon_size(key, scale=3):
    rows = ICONS[key]
    return len(rows[0]) * scale, len(rows) * scale


def draw_icon(p, key, x, y, scale=3, t=0.0, glow=False):
    """Рисует иконку в точке (x, y) - левый верхний угол. Возвращает (ширина, высота)."""
    rows = ICONS[key]
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch != ".":
                p.fillRect(int(x + i * scale), int(y + j * scale), scale, scale, QColor(*PAL[ch]))
    w, h = len(rows[0]) * scale, len(rows) * scale
    if key == "mug":                                      # пар над кружкой
        for k in range(2):
            ph = (t * 0.8 + k * 0.5) % 1.0
            p.fillRect(int(x + 6 + k * 8 + (3 if (int(t * 3) + k) % 2 else 0)), int(y - 3 - ph * 8), 3, 4,
                       QColor(230, 230, 240, int(200 * (1 - ph))))
    if glow:
        p.fillRect(int(x - 2), int(y - 2), int(w + 4), 1, QColor(255, 255, 255, 190))
        p.fillRect(int(x - 2), int(y + h + 1), int(w + 4), 1, QColor(255, 255, 255, 190))
    return w, h


# ---------------------------------------------------------------- опрос устройств
class _XState(ctypes.Structure):
    _fields_ = [("pkt", ctypes.c_uint32), ("buttons", ctypes.c_uint16), ("lt", ctypes.c_ubyte),
                ("rt", ctypes.c_ubyte), ("lx", ctypes.c_short), ("ly", ctypes.c_short),
                ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


class _XBattery(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ubyte), ("level", ctypes.c_ubyte)]


def xinput_gamepads():
    """Подключённые геймпады: [{'key','label','pct','note'}]. Уровень XInput грубый (4 ступени)."""
    out = []
    dll = None
    for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            dll = ctypes.WinDLL(name)
            break
        except OSError:
            continue
    if dll is None:
        return out
    for i in range(4):
        try:
            st = _XState()
            if dll.XInputGetState(i, ctypes.byref(st)) != 0:
                continue
            b = _XBattery()
            note, pct = "", None
            if dll.XInputGetBatteryInformation(i, 0, ctypes.byref(b)) == 0:
                if b.type == 1:
                    note = "wired"
                else:
                    note, pct = {0: ("lvl0", 5), 1: ("lvl1", 20), 2: ("lvl2", 55),
                                 3: ("lvl3", 100)}.get(b.level, ("", None))
            out.append(dict(key="gamepad", label="n_gamepad", pct=None, approx=pct, note=note))
        except Exception:
            pass
    return out


def laptop_battery():
    class SPS(ctypes.Structure):
        _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("pct", ctypes.c_ubyte),
                    ("saver", ctypes.c_ubyte), ("life", ctypes.c_uint32), ("full", ctypes.c_uint32)]
    s = SPS()
    try:
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)) and s.flag != 128 and s.pct <= 100:
            return [dict(key="laptop", label="n_laptop", pct=int(s.pct),
                         note="ac" if s.ac == 1 else "")]
    except Exception:
        pass
    return []


_PS = r"""
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$bat='{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2'; $con='{83DA6326-97A6-4088-9453-A1923F573B29} 15'
$o=@()
Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | ForEach-Object {
  $b=(Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $bat -ErrorAction SilentlyContinue).Data
  $c=(Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $con -ErrorAction SilentlyContinue).Data
  if($c -eq $true){ $o += [pscustomobject]@{name=$_.FriendlyName;battery=$b} }
}
if($o.Count -eq 0){ '[]' } else { ConvertTo-Json -InputObject @($o) -Compress }
"""
_NOISE = re.compile(r"avrcp|service|profile|protocol|enumerator|wireless bluetooth|rfcomm|generic|transport|"
                    r"adapter|radio|object push|phonebook|device information|attribute|access|intel|microsoft|"
                    r"personal area|pan\b|гарнитур|bluetooth le|адаптер", re.I)
_KINDS = (("gamepad", re.compile(r"xbox|controller|dualsense|dualshock|gamepad|joy-?con", re.I)),
          ("earbuds", re.compile(r"buds|airpods|earbud|tws|\bi\d{2}\b|headphone|headset", re.I)),
          ("phone", re.compile(r"phone|galaxy|iphone|pixel|redmi|xiaomi|oneplus|huawei|\b[AS]\d{2}\b", re.I)))


def bluetooth_devices():
    """Подключённые сейчас Bluetooth-устройства (PowerShell, около 10 секунд - вызывать из потока)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS],
                           capture_output=True, timeout=90, creationflags=0x08000000)
        data = json.loads(r.stdout.decode("utf-8", "replace").strip() or "[]")
    except Exception:
        return []
    out = []
    for d in data if isinstance(data, list) else [data]:
        name = d.get("name") or ""
        if not name or _NOISE.search(name):
            continue
        key = next((k for k, rx in _KINDS if rx.search(name)), None)
        if key is None:
            continue
        pct = d.get("battery")
        out.append(dict(key=key, label=NAMES[key], pct=int(pct) if isinstance(pct, (int, float)) else None,
                        approx=None, note="" if isinstance(pct, (int, float)) else "unavail"))
    return out


class DeviceScanner:
    """Фоновый опрос: быстрые источники каждые 15 с, Bluetooth каждые 90 с."""

    def __init__(self):
        self.devices = []
        self._bt = []
        self._bt_at = 0.0
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                if time.time() - self._bt_at > 90:
                    self._bt, self._bt_at = bluetooth_devices(), time.time()
                pads = xinput_gamepads()
                bt = list(self._bt)
                if pads:                                   # точный процент геймпада из Bluetooth, если есть
                    exact = next((d for d in bt if d["key"] == "gamepad" and d["pct"] is not None), None)
                    if exact:
                        pads[0]["pct"] = exact["pct"]
                bt = [d for d in bt if d["key"] != "gamepad"]
                self.devices = pads + bt + laptop_battery()
            except Exception:
                pass
            time.sleep(15)
