"""Clawd - пиксельный маскот, который живёт поверх всех окон и реагирует на Claude Code.

Связь с Claude Code: хуки пишут состояние в state.json (рядом со скриптом),
маскот опрашивает файл 5 раз в секунду. См. hook.py и README.md.
"""
import ctypes
import json
import math
import os
import random
import sys
import tempfile
import threading
import time
import winsound
try:
    import hid as _hid            # pip install hidapi (нужен только для батареи наушников)
except Exception:
    _hid = None
from pathlib import Path

from gadgets import DECOR, DeviceScanner, draw_icon, icon_size
from PySide6.QtCore import QLockFile, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication,
                           QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

HOME = Path(__file__).resolve().parent
STATE_FILE = HOME / "state.json"      # сюда пишут хуки
CONFIG_FILE = HOME / "config.json"    # позиция между запусками
STATUS_FILE = HOME / "status.json"    # что сейчас делает маскот (для проверки)

P = 4                  # размер "пикселя" спрайта на экране
W, H = 380, 260        # размер окна
MARGIN = 6             # отступ от низа окна до подошв
HANG_Y = 100           # где в окне точка подвеса, когда его держат за лапку
G = 2800.0             # гравитация, px/s^2

ORANGE = QColor(212, 127, 89)
LIGHT = QColor(244, 160, 118)
SHADE = QColor(190, 94, 62)
DARK = QColor(150, 70, 45)
INK = QColor(8, 0, 0)
WHITE = QColor(255, 255, 255)
GOLD = QColor(255, 205, 90)
LGOLD = QColor(255, 236, 160)
COOKIE = QColor(222, 170, 98)
CHIP = QColor(104, 58, 32)
CONFETTI = [QColor(255, 90, 90), QColor(255, 200, 60), QColor(90, 200, 120),
            QColor(90, 160, 255), QColor(200, 110, 255), QColor(255, 140, 200)]

POKE_LINES = ["Привет!", "Эй, щекотно!", "Клац-клац!", "Хочу печеньку!", "Бип-буп!",
              "Я тут живу", "Пиксели не кусаются", "Давай кодить!", "Ой!"]
WORK_LINES = ["Думаю", "Пишу код", "Ищу в файлах"]


def R(p, x, y, w, h, c):
    p.fillRect(int(x), int(y), int(w), int(h), c)


# ---------------------------------------------------------------- спрайт
SPR_W, SPR_H = 24, 15     # сетка спрайта в клетках


def draw_sprite(p, d):
    """Спрайт строго по референсу (сетка 24x15, тело 18x12 в колонках 3..20):
    руки 3x3 по бокам, глаза 1x3 (колонки 6 и 17), ноги 2 клетки шириной, 2+2."""
    t = d["t"]
    by = d["by"]                       # на сколько клеток тело опущено (ноги короче)
    legs = d["legs"]
    L = 3 - by
    for i, x in enumerate((4, 7, 15, 18)):
        l = L
        if legs in ("walk", "dance") and L > 1 and math.sin(d["phase"] + (i // 2) * math.pi) > 0:
            l = L - 1
        elif legs == "air":
            l = max(1, L - 1 + (1 if math.sin(t * 16 + i * 1.7) > 0 else 0))
        R(p, x, 12 + by + (L - l if legs in ("walk", "dance", "air") else 0), 2, l, ORANGE)
    R(p, 3, by, 18, 12, ORANGE)                         # тело
    for side, (a, xs) in ((0, (d["cl"][0], 0)), (1, (d["cr"][0], 0))):
        top = by + 6 - round(a * 6)
        R(p, 0 if side == 0 else 21, top, 3, 3, ORANGE)  # рука
    if d.get("phones"):                                   # наушники на связи
        PH, CUP = QColor(58, 60, 70), QColor(40, 42, 50)
        R(p, 4, by - 2, 16, 1, PH)
        R(p, 3, by - 1, 1, 2, PH)
        R(p, 20, by - 1, 1, 2, PH)
        R(p, 2, by + 1, 1, 1, PH)
        R(p, 21, by + 1, 1, 1, PH)
        for cx_ in (0, 21):
            R(p, cx_, by + 1, 3, 5, CUP)
        R(p, 0, by + 2, 1, 3, QColor(220, 55, 55))
        R(p, 23, by + 2, 1, 3, QColor(220, 55, 55))
    ey = by + 3 + d["lookdy"]
    lx = d["look"]
    em = d["eyes"]
    for ei, x in enumerate((6 + lx, 17 + lx)):
        em = "closed" if (d.get("wink") and ei == 1) else d["eyes"]
        if em == "open":
            R(p, x, ey, 1, 3, INK)
        elif em == "wide":
            R(p, x, ey - 1, 1, 4, INK)
        elif em == "closed":
            R(p, x, ey + 1, 1, 1, INK)
        elif em == "half":
            R(p, x, ey + 1, 1, 2, INK)
        elif em == "happy":                              # дуга ^
            R(p, x - 1, ey + 1, 1, 1, INK)
            R(p, x, ey, 1, 1, INK)
            R(p, x + 1, ey + 1, 1, 1, INK)
        elif em == "x":
            R(p, x - 1, ey, 1, 1, INK)
            R(p, x + 1, ey, 1, 1, INK)
            R(p, x, ey + 1, 1, 1, INK)
            R(p, x - 1, ey + 2, 1, 1, INK)
            R(p, x + 1, ey + 2, 1, 1, INK)
    if d["cookie"] is not None:                          # реквизит для «ест печеньку»
        bites = int((1 - d["cookie"]) * 5)
        top = by + 6 - round(d["cr"][0] * 6)
        ox, oy = 22, top - 4
        for (x, y) in [(x, 0) for x in (1, 2, 3)] + [(x, y) for y in (1, 2, 3) for x in range(5)] + [(x, 4) for x in (1, 2, 3)]:
            if x < 5 - bites:
                R(p, ox + x - 2, oy + y, 1, 1, COOKIE)


def base_pose(t):
    return dict(t=t, by=0, legs="stand", phase=0.0, cl=(0.0, False), cr=(0.0, False), crx=0,
                eyes="open", look=0, lookdy=0, cookie=None, face=1, sqx=0.0, rot=0.0, bob=0.0, phones=False)


# ---------------------------------------------------------------- Win32
user32 = ctypes.windll.user32
user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x80, 0x08000000, 0x8
HWND_TOPMOST = ctypes.c_void_p(-1)


def keep_on_top(hwnd):
    # SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)


def harden_window(hwnd):
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
    keep_on_top(hwnd)


from ctypes import wintypes as wt

dwmapi = ctypes.windll.dwmapi
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.IsZoomed.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
                "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland", "NotifyIconOverflowWindow"}


user32.GetForegroundWindow.restype = wt.HWND
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.MonitorFromWindow.restype = wt.HANDLE
user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.c_void_p]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
# мышь, WASD, пробел, Shift/Ctrl, E Q R F, стрелки, цифры 1-5: только чтобы понять, насколько ты сейчас активен
WATCH_KEYS = (0x01, 0x02, 0x57, 0x41, 0x53, 0x44, 0x20, 0x10, 0x11, 0x45, 0x51, 0x52, 0x46,
              0x25, 0x26, 0x27, 0x28, 0x31, 0x32, 0x33, 0x34, 0x35)


def fullscreen_app_active(own_hwnd):
    """True, если на переднем плане игра / полноэкранное приложение (тогда маскот прячется)."""
    try:
        # 2 = занят/полный экран, 3 = полноэкранный Direct3D (игра), 4 = режим презентации
        st = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(st)) == 0 and st.value in (2, 3, 4):
            return True
        h = user32.GetForegroundWindow()
        if not h or h == own_hwnd:
            return False
        buf = ctypes.create_unicode_buffer(80)
        user32.GetClassNameW(h, buf, 80)
        if buf.value in SKIP_CLASSES:
            return False
        r = wt.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(user32.MonitorFromWindow(h, 2), ctypes.byref(mi))
        m = mi.rcMonitor
        # окно закрывает монитор целиком, вместе с панелью задач (обычное развёрнутое окно её не закрывает)
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    except Exception:
        return False


kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
psapi.EnumProcessModulesEx.argtypes = [wt.HANDLE, ctypes.POINTER(wt.HMODULE), wt.DWORD, ctypes.POINTER(wt.DWORD), wt.DWORD]
psapi.GetModuleBaseNameW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]

# папки, где живут игры; программы, которые игрой не считаются никогда
LAUNCH_DIRS = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\gog galaxy\\games\\",
               "\\ubisoft game launcher\\games\\", "\\xboxgames\\", "\\.minecraft\\", "\\rockstar games\\",
               "\\ea games\\", "\\battlestate games\\", "\\games\\")
NOT_GAMES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "code.exe", "claude.exe", "explorer.exe",
             "devenv.exe", "unity.exe", "unityhub.exe", "blender.exe", "discord.exe", "slack.exe", "spotify.exe",
             "teams.exe", "ms-teams.exe", "notepad.exe", "powershell.exe", "windowsterminal.exe", "cmd.exe",
             "python.exe", "pythonw.exe", "obs64.exe", "vlc.exe", "steam.exe", "epicgameslauncher.exe",
             "battle.net.exe", "telegram.exe", "whatsapp.exe", "winword.exe", "excel.exe", "powerpnt.exe"}
GFX_DLLS = ("d3d11.dll", "d3d12.dll", "d3d9.dll", "vulkan-1.dll", "unityplayer.dll")


def _proc_path(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wt.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(h)
    return ""


def _has_gfx_modules(pid):
    h = kernel32.OpenProcess(0x0410, False, pid)           # QUERY_INFORMATION | VM_READ
    if not h:
        return False
    try:
        arr = (wt.HMODULE * 1024)()
        need = wt.DWORD(0)
        if not psapi.EnumProcessModulesEx(h, arr, ctypes.sizeof(arr), ctypes.byref(need), 3):
            return False
        name = ctypes.create_unicode_buffer(260)
        for i in range(min(1024, need.value // ctypes.sizeof(wt.HMODULE))):
            if psapi.GetModuleBaseNameW(h, arr[i], name, 260) and name.value.lower() in GFX_DLLS:
                return True
    finally:
        kernel32.CloseHandle(h)
    return False


def windowed_game_active(own_hwnd, cache, extra=()):
    """Игра в окне / безрамочная: передний план - не обычная программа, а процесс из папки игр,
    Minecraft по заголовку, либо крупное окно с графическим API (D3D/Vulkan). Результат кэшируется на окно."""
    try:
        h = user32.GetForegroundWindow()
        if not h or h == own_hwnd:
            return False
        hit = cache.get(h)
        if hit and time.time() - hit[0] < 8:
            return hit[1]
        res = False
        buf = ctypes.create_unicode_buffer(80)
        user32.GetClassNameW(h, buf, 80)
        if buf.value not in SKIP_CLASSES:
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            path = _proc_path(pid.value)
            exe = os.path.basename(path).lower()
            tb = ctypes.create_unicode_buffer(200)
            user32.GetWindowTextW(h, tb, 200)
            title = tb.value.lower()
            if exe and exe in extra:                              # твой список из config.json (game_exes)
                res = True
            elif exe and exe not in NOT_GAMES and not any(x in exe for x in ("launcher", "helper", "crash", "setup", "updater")):
                lp = path.lower()
                if any(d in lp for d in LAUNCH_DIRS) or "minecraft" in title:
                    res = True
                else:
                    r = wt.RECT()
                    user32.GetWindowRect(h, ctypes.byref(r))
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(mi)
                    user32.GetMonitorInfoW(user32.MonitorFromWindow(h, 2), ctypes.byref(mi))
                    m = mi.rcMonitor
                    area = max(1, (m.right - m.left) * (m.bottom - m.top))
                    frac = max(0, r.right - r.left) * max(0, r.bottom - r.top) / area
                    res = frac >= 0.7 and _has_gfx_modules(pid.value)
        cache[h] = (time.time(), res)
        if len(cache) > 40:
            cache.clear()
        return res
    except Exception:
        return False


def foreign_windows(own_hwnd):
    """Видимые окна верхнего уровня (кроме нашего и системных): (l, t, r, b, maximized)."""
    out = []

    def cb(h, _):
        try:
            if h == own_hwnd or not user32.IsWindowVisible(h) or user32.IsIconic(h):
                return True
            cloaked = wt.DWORD(0)
            dwmapi.DwmGetWindowAttribute(h, 14, ctypes.byref(cloaked), 4)
            if cloaked.value or user32.GetWindowTextLengthW(h) == 0:
                return True
            buf = ctypes.create_unicode_buffer(80)
            user32.GetClassNameW(h, buf, 80)
            if buf.value in SKIP_CLASSES:
                return True
            ex = user32.GetWindowLongPtrW(h, GWL_EXSTYLE)
            if (ex & 0x20) and (ex & 0x80000):      # прозрачные для кликов оверлеи
                return True
            r = wt.RECT()
            if dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
                user32.GetWindowRect(h, ctypes.byref(r))
            if r.right > r.left and r.bottom > r.top:
                out.append((r.left, r.top, r.right, r.bottom, bool(user32.IsZoomed(h))))
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


# ---------------------------------------------------------------- батарея наушников HyperX Cloud III Wireless
HX_VID, HX_PIDS = 0x03F0, (0x05B7, 0x0C9D)


def read_headset_battery():
    """Процент заряда наушников или None (приёмника нет, наушники выключены, нет hidapi).
    Запрос 0x66 0x89 только читает заряд; ответ: байт 4 = процент."""
    if _hid is None:
        return None
    try:
        devs = [d for d in _hid.enumerate() if d["vendor_id"] == HX_VID and d["product_id"] in HX_PIDS]
        pref = [d for d in devs if d["usage_page"] == 0xFEF3 and d["usage"] == 1] or \
               [d for d in devs if d["usage_page"] == 0xFF13]
        if not pref:
            return None
        h = _hid.device()
        h.open_path(pref[0]["path"])
        try:
            h.set_nonblocking(False)
            req = [0] * 52
            req[0], req[1] = 0x66, 0x89
            h.write(req)
            r = h.read(20, 1000)
        finally:
            h.close()
        if len(r) > 4 and 1 <= r[4] <= 100:
            return int(r[4])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- эмоции (пиксельные значки)
EMOTES = {
    "heart": ([".XX.XX.", "XXXXXXX", "XXXXXXX", ".XXXXX.", "..XXX..", "...X..."], QColor(235, 70, 95)),
    "q": ([".XXX.", "X...X", "....X", "...X.", "..X..", ".....", "..X.."], QColor(255, 210, 80)),
    "!": (["XX", "XX", "XX", "XX", "..", "XX"], QColor(255, 80, 60)),
    "note": (["..XXX", "..X.X", "..X..", "..X..", "XXX..", "XXX.."], QColor(120, 190, 255)),
    "sweat": (["..X..", ".XXX.", "XXXXX", "XXXXX", ".XXX."], QColor(110, 180, 255)),
    "spark": (["..X..", "..X..", "XXXXX", "..X..", "..X.."], QColor(255, 215, 90)),
}

EMOTES["cookie"] = (["..XXX..", ".XXXXX.", "XXXXXXX", "XXXXXXX", "XXXXXXX", ".XXXXX.", "..XXX.."], COOKIE)
MOVERS = {"walk": (85, 9, 0.45), "flee": (300, 20, 0.07), "zoomies": (430, 24, 0.05), "sneak": (35, 6, 9.9)}

THOUGHTS = ["Хм...", "Скучно...", "Интересно", "♪ ♪ ♪", "Где печеньки?", "Кто-нибудь кодит?",
            "Пиксели — это красиво", "Ля-ля-ля", "Эй, ты тут?"]
IDLE_PICKS = [("walk", 22), ("stand", 6), ("sit", 9), ("jump", 6), ("hungry", 6), ("sleep", 6), ("fall", 3),
              ("look", 9), ("stretch", 4), ("wiggle", 4), ("curious", 8), ("hop3", 4),
              ("juggle", 5), ("sneeze", 3), ("sing", 5), ("spin", 4), ("butterfly", 5), ("zoomies", 4),
              ("sneak", 4), ("workout", 3), ("stargaze", 4)]


def draw_emote(p, name, x, y, cell=4):
    rows, col = EMOTES[name]
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch == "X":
                    p.fillRect(int(x + i * cell + dx), int(y + j * cell + dy), cell, cell, QColor(50, 35, 35))
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == "X":
                p.fillRect(int(x + i * cell), int(y + j * cell), cell, cell, col)


def play(seq):
    """Мелодия из (частота Гц, длительность мс) в фоновом потоке."""
    def run():
        try:
            for f, ms in seq:
                winsound.Beep(f, ms)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


SND_DONE = [(784, 110), (988, 110), (1175, 110), (1568, 280)]
SND_ATTENTION = [(880, 150), (660, 220)]


def approach(v, target, step):
    return min(target, v + step) if v < target else max(target, v - step)


# ---------------------------------------------------------------- маскот
class Clawd(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(W, H)
        self.setWindowTitle("Clawd")

        self.hwnd = 0
        self.t = 0.0
        self.last = time.perf_counter()
        self.phase = 0.0
        self.dir = -1
        self.mode = "idle"
        self.beh = "stand"
        self.bt = 0.0
        self.dur = 2.0
        self.air = False
        self.vy = 0.0
        self.vx = 0.0
        self.thrown, self.bounces, self.tumble, self.slide = False, 0, 0.0, 0.0
        self.drag_samples = []
        self.hang, self.hang_ang, self.hang_vel = 0, 0.0, 0.0   # висит на той точке, за которую схватили
        self.hang_px = self.hang_py = 0.0                       # точка подвеса в клетках спрайта
        self.hang_tgt, self.hang_arm = 0.0, 0
        self.press_local = QPoint(0, 0)
        self.batt = None                     # заряд наушников, % (None = нет связи)
        self.batt_show_until = 0.0
        self.batt_next = 0.0
        self.batt_warn = 0.0
        self.peak_y = 0.0
        self.pending = None          # (когда, vy, vx) - прыжок после приседания
        self.sq = 0.0                # сжатие (+) / растяжение (-)
        self.sqv = 0.0
        self.rot = 0.0
        self.happy_until = 0.0
        self.annoy_until = 0.0
        self.cookie = None
        self.emote = None            # (имя, до, старт)
        self.gaze = (0, 0)
        self.next_glance = 0.0
        self.next_blink = 2.0
        self.blink_until = 0.0
        self.hover_t = 0.0
        self.click_times = []
        self.next_thought = 20.0
        self.arrived = None
        self.dust_t = 0.0
        self.mode_bubble = None      # (text, expire)
        self.temp_bubble = None
        self.next_say = 0.0
        self.done_left = 0.0
        self.last_hop = 0.0
        self.particles = []
        self.confetti_left = 0.0
        self.dragging = False
        self.pressed = False
        self.setCursor(Qt.OpenHandCursor)
        self.cursor_prev = QCursor.pos()
        self.cspeed = 0.0
        self.poll_acc = 0.0
        self.top_acc = 0.0
        self.state_mtime = self._mtime()
        self.pose = base_pose(0)
        self.blockers = []
        self.sound = True
        self.show_gadgets = True
        self.game_pos = None                  # где он стоит в играх: (x от левого края экрана, высота подошв над низом)
        self.game_target, self.game_arrived = (0.0, 0.0), False
        self.keys_down, self.key_events, self.intensity = set(), [], 0.0
        self.react, self.next_react = None, 0.0
        self.force_game, self._game_cache = False, {}
        self.game_exes = set()
        self._g_first, self._g_last, self._g_prev, self._kmove, self._hint = None, -99.0, False, False, False
        self.scanner = DeviceScanner()
        self.still_since, self.prev_cx, self.items_alpha = 0.0, 0.0, 0.0
        self.hover, self.gadget_rects = None, []
        self.tray = None
        self.block_acc = 0.0
        self.target_x = None
        self.tight_t = -99.0
        self.last_q = -99.0

        a = self.avail_default()
        self.cx = a.right() - 130.0
        self.y = float(a.bottom() + 1 - H + MARGIN)
        cfg = self.load_config()
        if cfg:
            self.sound = bool(cfg.get("sound", True))
            self.show_gadgets = bool(cfg.get("gadgets", True))
            self.game_pos = cfg.get("game_pos")
            self.game_exes = {str(x).lower() for x in cfg.get("game_exes", [])}
        if cfg and "cx" in cfg:
            for s in QGuiApplication.screens():
                g = s.availableGeometry()
                if g.left() + 60 <= cfg["cx"] <= g.right() - 60:
                    self.cx = float(cfg["cx"])
                    self.y = float(g.bottom() + 1 - H + MARGIN)
                    break
        self.move(int(self.cx - W / 2), int(self.y))
        self._batt_raw = None
        threading.Thread(target=self._batt_loop, daemon=True).start()
        self.enter("hello")
        self.show()
        self.hwnd = int(self.winId())
        harden_window(self.hwnd)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.write_status()

    # ------------------------------------------------ служебное
    def avail_default(self):
        return QGuiApplication.primaryScreen().availableGeometry()

    def avail(self):
        s = QGuiApplication.screenAt(QPoint(int(self.cx), int(self.y + H - 10)))
        return (s or QGuiApplication.primaryScreen()).availableGeometry()

    def _mtime(self):
        try:
            return os.stat(STATE_FILE).st_mtime_ns
        except OSError:
            return 0

    def load_config(self):
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_config(self):
        try:
            CONFIG_FILE.write_text(json.dumps({"cx": int(self.cx), "sound": self.sound, "gadgets": self.show_gadgets,
                                           "game_pos": self.game_pos,
                                           "game_exes": sorted(self.game_exes)}), encoding="utf-8")
        except OSError:
            pass

    def write_status(self):
        try:
            tmp = STATUS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps({"mode": self.mode, "behavior": self.beh, "hang": self.hang, "hwnd": self.hwnd,
                                       "cx": int(self.cx), "pid": os.getpid(),
                                       "time": time.time()}), encoding="utf-8")
            os.replace(tmp, STATUS_FILE)
        except OSError:
            pass

    def notify(self, kind):
        """Звук и уведомление Windows, чтобы заметить маскота, даже если он закрыт окном."""
        if not self.sound:
            return
        if kind == "done":
            play(SND_DONE)
            title, msg = "Clawd", "Claude закончил. Готово!"
        else:
            play(SND_ATTENTION)
            title, msg = "Clawd", "Claude ждёт тебя"
        if self.tray is not None:
            self.tray.showMessage(title, msg, QSystemTrayIcon.NoIcon, 4000)

    def _batt_loop(self):
        while True:
            self._batt_raw = read_headset_battery()
            time.sleep(40)

    def update_battery(self):
        """Следит за зарядом наушников: когда показать батарейку и когда предупредить."""
        raw = self._batt_fake if hasattr(self, "_batt_fake") else self._batt_raw
        if raw != self.batt:
            prev, self.batt = self.batt, raw
            if raw is not None and prev is None:
                self.batt_show_until = self.t + 6.0
                self.batt_next = self.t + 240
                self.say("Наушники на связи!", 2.4)
            elif raw is None and prev is not None:
                self.say("Наушники отключились", 2.4)
            if self.tray is not None:
                self.tray.setToolTip("Clawd" + (f" — наушники {raw}%" if raw is not None else ""))
        if raw is None:
            return
        if self.t >= self.batt_next and self.beh not in ("sleep",):
            self.batt_show_until = self.t + 5.0
            self.batt_next = self.t + (240 if raw > 20 else 120 if raw > 10 else 60)
        if raw <= 20 and self.t >= self.batt_warn:
            self.batt_warn = self.t + (300 if raw > 10 else 120)
            self.batt_show_until = self.t + 6.0
            self.say(f"Наушники садятся: {raw}%", 3.2)
            self.show_emote("sweat", 2.0)
            if self.sound and self.tray is not None:
                play(SND_ATTENTION)
                self.tray.showMessage("Clawd", f"Заряд наушников {raw}%. Пора на зарядку", QSystemTrayIcon.NoIcon, 4000)

    def show_battery(self):
        self.batt_show_until = self.t + 5.0
        if self.batt is None:
            self.say("Наушники не на связи", 2.2)

    def set_gadgets(self, on):
        self.show_gadgets = bool(on)
        self.save_config()

    def set_sound(self, on):
        self.sound = bool(on)
        self.save_config()

    def say(self, text, secs=2.5):
        self.temp_bubble = (text, self.t + secs)

    def show_emote(self, name, secs=1.8):
        self.emote = (name, self.t + secs, self.t)

    # ------------------------------------------------ режимы от хуков
    def poll_state(self):
        m = self._mtime()
        if m == self.state_mtime:
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        self.state_mtime = m
        st = data.get("state")
        if st in ("idle", "working", "done", "attention"):
            self.set_mode(st)
        if data.get("debug"):
            self.enter(data["debug"])
        if "fake_batt" in data:                      # только для проверки
            self._batt_fake = data["fake_batt"]

    def set_mode(self, m):
        self.mode = m
        self.mode_bubble = None
        self.cookie = None
        self.emote = None
        if m == "working":
            self.enter("work")
            self.next_say = self.t + random.uniform(1.0, 3.0)
        elif m == "done":
            self.done_left = 5.0
            self.mode_bubble = ("Готово!", self.t + 5.0)
            self.confetti_left = 3.5
            self.burst(70)
            self.show_emote("spark", 1.2)
            self.notify("done")
            self.enter("dance")
        elif m == "attention":
            self.mode_bubble = ("Жду тебя!", float("inf"))
            self.notify("attention")
            self.enter("wave")
        else:
            self.pick()
        self.write_status()

    # ------------------------------------------------ поведение
    def launch(self, vy, vx=0.0, delay=0.0):
        """Прыжок. С delay маскот сначала приседает (предвкушение), потом прыгает."""
        if delay > 0 and not self.air:
            self.pending = (self.t + delay, vy, vx)
            return
        self.vy, self.vx = vy, vx
        self.air = True
        self.peak_y = self.y
        self.dust(5)

    def enter(self, b):
        self.beh, self.bt = b, 0.0
        self.arrived = None
        a = self.avail()
        if b == "walk":
            self.dur = random.uniform(3, 7)
            self.dir = random.choice((-1, 1))
        elif b == "stand":
            self.dur = random.uniform(2, 4)
        elif b == "sit":
            self.dur = random.uniform(4, 8)
        elif b == "sleep":
            self.dur = random.uniform(12, 22)
        elif b == "yawn":
            self.dur = 1.8
        elif b == "stretch":
            self.dur = 1.8
        elif b == "look":
            self.dur = random.uniform(2.5, 4)
        elif b == "wiggle":
            self.dur = 1.4
        elif b == "hop3":
            self.dur = 2.2
            self.last_hop = self.t - 1
        elif b == "curious":
            self.dur = 10.0
        elif b == "jump":
            self.dur = 1.0
            self.launch(-720, delay=0.12)
        elif b == "eat":
            self.dur = 5.5
            self.cookie = 1.0
        elif b == "fall":
            self.dur = 99
            gy = a.bottom() + 1 - H + MARGIN
            room = max(60.0, gy - a.top() - 30)
            self.show_emote("!", 0.9)
            self.launch(-min(1500.0, math.sqrt(2 * G * room)), random.choice((-1, 1)) * 60.0, delay=0.18)
        elif b == "dizzy":
            self.dur = 1.8
            self.say("Ой-ой...", 1.6)
        elif b == "flee":
            self.dur = 1.3
            self.show_emote("sweat", 1.3)
        elif b == "evade":
            self.dur = 6.0
        elif b == "hungry":
            self.dur = 1.9
            self.say("Бр-р-р...", 1.7)
            self.show_emote("cookie", 1.9)
        elif b == "juggle":
            self.dur = 5.5
        elif b == "sneeze":
            self.dur = 2.0
            self.sneezed = False
        elif b == "sing":
            self.dur = 6.0
            self.last_hop = self.t - 1
        elif b == "spin":
            self.dur = 1.8
            self.launch(-380, delay=0.08)
        elif b == "butterfly":
            self.dur = 8.0
            self.last_hop = self.t
        elif b == "zoomies":
            self.dur = 3.2
            self.dir = random.choice((-1, 1))
            self.last_hop = self.t
        elif b == "sneak":
            self.dur = 4.5
        elif b == "workout":
            self.dur = 4.2
            self.reps = 0
            self.last_hop = self.t - 0.4
        elif b == "stargaze":
            self.dur = 6.0
        elif b == "hello":
            self.dur = 2.6
            self.say("Привет!", 2.2)
        elif b == "bye":
            self.dur = 1.5
            self.say("Пока!", 1.3)
        elif b in ("dance", "wave"):
            self.last_hop = self.t
        self.write_status()

    def pick(self):
        if self.mode == "working":
            return self.enter("work")
        if self.mode == "attention":
            return self.enter("wave")
        if self.mode == "done":
            return self.enter("dance")
        cur = QCursor.pos()
        opts = [o for o in IDLE_PICKS if o[0] != self.beh]
        hr = time.localtime().tm_hour
        if hr >= 23 or hr < 6:
            opts = [(n, 20 if n == "sleep" else wgt) for n, wgt in opts]
        if abs(cur.x() - self.cx) < 220:
            opts = [o for o in opts if o[0] != "curious"]
        names, w = zip(*opts)
        c = random.choices(names, w)[0]
        self.enter("yawn" if c == "sleep" else c)

    def land(self, impact):
        if self.thrown and abs(impact) > 420 and self.bounces < 4:
            self.bounces += 1                          # отскакивает от пола
            self.vy = -abs(impact) * 0.42
            self.vx *= 0.8
            self.sq = min(0.34, 0.08 + abs(impact) / 4500.0)
            self.sqv = 0.0
            self.dust(6)
            return
        if self.thrown:
            speed = abs(self.vx)
            self.slide = self.vx * 0.9                 # проезжает по земле
            self.thrown = False
            self.tumble -= 360 * round(self.tumble / 360)
            self.rot -= 360 * round(self.rot / 360)
            if speed > 700 and self.mode == "idle":
                self.enter("dizzy")
        self.air = False
        self.vx = 0.0
        self.vy = 0.0
        self.sq = min(0.34, 0.08 + abs(impact) / 4500.0)
        self.sqv = 0.0
        self.dust(8)
        drop = self.y - self.peak_y
        if self.mode == "idle" and (self.beh == "fall" or drop > 300):
            self.enter("dizzy")

    def dust(self, n):
        for _ in range(n):
            life = random.uniform(0.35, 0.6)
            self.particles.append(dict(kind="d", x=W / 2 + random.uniform(-SPR_W * P / 2, SPR_W * P / 2), y=H - MARGIN - 3,
                                       vx=random.uniform(-60, 60), vy=random.uniform(-30, -5),
                                       col=QColor(205, 195, 180), spin=0, life=life, l0=life))

    def burst(self, n):
        for _ in range(n):
            self.particles.append(dict(kind="c", x=random.uniform(10, W - 10), y=random.uniform(-10, 60),
                                       vx=random.uniform(-70, 70), vy=random.uniform(60, 260),
                                       col=random.choice(CONFETTI), spin=random.uniform(0, 6.28),
                                       life=random.uniform(2.5, 4.5)))

    def crumb(self):
        self.particles.append(dict(kind="k", x=W / 2 + random.uniform(-10, 14), y=H - MARGIN - SPR_H * P * 0.7,
                                   vx=random.uniform(-40, 40), vy=random.uniform(-60, 0),
                                   col=COOKIE, spin=0, life=0.7))

    # ------------------------------------------------ тик
    def tick(self):
        now = time.perf_counter()
        dt = min(now - self.last, 0.05)
        self.last = now
        self.t += dt

        self.poll_acc += dt
        if self.poll_acc >= 0.2:
            self.poll_acc = 0
            self.poll_state()
        self.block_acc += dt
        if self.block_acc >= 0.4:
            self.block_acc = 0
            gaming = self.detect_game()
            if gaming and not getattr(self, "in_game", False):
                self.in_game = True                     # игра: стоит на экране и играет вместе с тобой
                sg = self.cur_screen().geometry()
                if self.game_pos:
                    tx = sg.left() + float(self.game_pos[0])
                    fa = float(self.game_pos[1])
                else:
                    tx, fa = sg.right() - 170.0, 0.0
                self.game_target = (tx, sg.bottom() + 1 - H + MARGIN - fa)
                self.game_arrived = False
                self.next_react = self.t + random.uniform(4, 8)
                self.react = None
                if self._hint:
                    self.say("Играем!", 2.0)
                else:
                    self._hint = True
                    self.say("Играем! Ctrl+Alt+стрелки двигают меня", 4.5)
            elif not gaming and getattr(self, "in_game", False):
                self.in_game = False
                self.air = True
                self.peak_y = self.y
                self.enter("hello")
            self.refresh_blockers()
            self.update_battery()
        self.top_acc += dt
        if self.top_acc >= 1.5:
            self.top_acc = 0
            keep_on_top(self.hwnd)

        self.poll_hotkeys(dt)
        cur = QCursor.pos()
        inst = math.hypot(cur.x() - self.cursor_prev.x(), cur.y() - self.cursor_prev.y()) / max(dt, 1e-3)
        self.cspeed = self.cspeed * 0.8 + inst * 0.2
        self.cursor_prev = cur

        a = self.avail()
        lo, hi = a.left() + 68, a.right() - 68
        game = getattr(self, "in_game", False)
        gy = a.bottom() + 1 - H + MARGIN
        if game:                                        # в игре панели задач нет; он стоит где поставишь
            sg = self.cur_screen().geometry()
            a = sg
            lo, hi = sg.left() + 40, sg.right() - 40
            gy = sg.bottom() + 1 - H + MARGIN
            self.game_step(dt, cur)

        if game:
            if self.dragging:
                self.air = True
                if self.hang:
                    diff = (self.hang_ang - self.hang_tgt + 180.0) % 360.0 - 180.0
                    self.hang_vel += (-46.0 * diff - 5.0 * self.hang_vel) * dt
                    self.hang_ang += self.hang_vel * dt
            else:
                self.air = False
                self.vx = self.vy = 0.0
                tx, ty = self.game_target
                if not self.game_arrived:                # идёт на своё место
                    dxx, dyy = tx - self.cx, ty - self.y
                    dist = math.hypot(dxx, dyy)
                    if dist < 6:
                        self.cx, self.y, self.game_arrived = tx, ty, True
                        self.beh = "play"
                        self.write_status()
                    else:
                        stp = min(dist, 560 * dt)
                        self.cx += dxx / dist * stp
                        self.y += dyy / dist * stp
                        if abs(dxx) > 3:
                            self.dir = 1 if dxx > 0 else -1
                        self.phase += dt * 16
                        self.beh = "walk"
                else:
                    self.beh = "play"
        elif self.dragging:
            self.air = True
            if self.hang:
                diff = (self.hang_ang - self.hang_tgt + 180.0) % 360.0 - 180.0
                acc = -46.0 * diff - 5.0 * self.hang_vel
                self.hang_vel += acc * dt
                self.hang_ang += self.hang_vel * dt
        else:
            self.logic(dt, cur, lo, hi)
            if self.pending and self.t >= self.pending[0]:
                _, pvy, pvx = self.pending
                self.pending = None
                self.launch(pvy, pvx)
            if self.y < gy - 0.5 and not self.air:
                self.air = True
                self.peak_y = self.y
                self.vy = 0.0
            if self.air:
                self.vy += G * dt
                self.y += self.vy * dt
                self.cx += self.vx * dt
                if self.thrown:
                    spin = 230.0 + abs(self.vx) * 0.7               # градусов в секунду
                    self.tumble += (1 if self.vx >= 0 else -1) * spin * dt
                    for edge, sgn in ((lo, 1), (hi, -1)):
                        if (self.cx - edge) * sgn < 0:                 # стена: отскок
                            self.cx = edge
                            if abs(self.vx) > 150:
                                self.dust(5)
                                self.sq = 0.2
                            self.vx = abs(self.vx) * 0.62 * sgn
                top = a.top() - 10
                if self.y < top:
                    self.y = top
                    self.vy = abs(self.vy) * 0.4 if self.thrown else 0.0
                if self.y >= gy and self.vy > 0:
                    self.y = gy
                    self.land(self.vy)
            else:
                self.y = gy
        if not self.air and not self.dragging and abs(self.slide) > 12:
            self.cx += self.slide * dt
            self.slide *= math.exp(-6.0 * dt)
            if random.random() < 0.35:
                self.dust(1)
            if self.cx <= lo or self.cx >= hi:
                self.slide *= -0.4
        elif abs(self.slide) <= 12:
            self.slide = 0.0
        if not self.air and not self.dragging and self.tumble:
            self.tumble *= math.exp(-3.2 * dt)           # плавно поднимается, без щелчка
            if abs(self.tumble) < 0.4:
                self.tumble = 0.0
        self.cx = max(lo, min(hi, self.cx))
        if game:
            self.y = max(a.top() - 20.0, min(float(gy), self.y))

        # пружина сжатия/растяжения
        if self.pending:
            self.sq = approach(self.sq, 0.24, 2.2 * dt)
            self.sqv = 0.0
        elif self.air and not self.dragging:
            self.sq = -min(0.24, abs(self.vy) / 4800.0)
            self.sqv = 0.0
        else:
            self.sqv += (-170 * self.sq - 12 * self.sqv) * dt
            self.sq += self.sqv * dt

        for pt in self.particles:
            pt["life"] -= dt
            pt["x"] += pt["vx"] * dt
            pt["y"] += pt["vy"] * dt
            pt["vy"] += {"c": 200, "k": 600, "d": 0}[pt["kind"]] * dt
            pt["spin"] += dt * 9
        self.particles = [q for q in self.particles if q["life"] > 0 and q["y"] < H + 20]

        moved = abs(self.cx - self.prev_cx) > 0.6 or self.air or self.dragging or getattr(self, "in_game", False)
        self.prev_cx = self.cx
        if moved:
            self.still_since = self.t
        want = self.show_gadgets and (self.t - self.still_since) > 1.2 and not self.dragging
        self.items_alpha = approach(self.items_alpha, 1.0 if want else 0.0, dt * 3.0)
        self.hover = None
        if self.items_alpha > 0.6:
            lp = QPointF(cur.x() - self.pos().x(), cur.y() - self.pos().y())
            for rect, item in self.gadget_rects:
                if rect.contains(lp):
                    self.hover = item
                    break
        self.update_face(dt, cur)
        self.pose = self.make_pose(cur)
        k = min(1.0, dt * 14)
        self.rot += (self.pose["rot"] - self.rot) * k
        if self.dragging and self.hang:
            self.rot = self.hang_ang
        self.move(int(round(self.cx - W / 2)), int(round(self.y)))
        self.update()

    def cur_screen(self):
        return QGuiApplication.screenAt(QPoint(int(self.cx), int(self.y + H - 10))) or QGuiApplication.primaryScreen()

    def screen_bottom(self):
        return self.cur_screen().geometry().bottom() + 1

    def peek_pos(self, t):
        """Висит на боковом краю экрана: снаружи одни ручки; раз в ~9 с выглядывает глазом."""
        sg = self.cur_screen().geometry()
        c = t % 9.0
        if c < 4.0:
            up = 0.0
        elif c < 4.45:
            up = (c - 4.0) / 0.45
        elif c < 7.2:
            up = 1.0
        elif c < 7.65:
            up = 1.0 - (c - 7.2) / 0.45
        else:
            up = 0.0
        self.peek_up = up
        show = 12 + up * 24                              # сколько спрайта торчит из-за края, px
        half = SPR_W * P / 2
        if self.peek_side > 0:
            tx = sg.right() + 1 - show + half
        else:
            tx = sg.left() + show - half
        ty = sg.top() + sg.height() * 0.6 - (H - MARGIN - SPR_H * P / 2)
        return tx, ty

    def detect_game(self):
        """Игра сейчас на переднем плане? С задержкой на вход и выход, чтобы Alt-Tab не дёргал маскота."""
        raw = self.force_game or fullscreen_app_active(self.hwnd) or windowed_game_active(self.hwnd, self._game_cache, self.game_exes)
        now = self.t
        if raw:
            if self._g_first is None:
                self._g_first = now
            self._g_last = now
        else:
            self._g_first = None
        if not getattr(self, "in_game", False):
            return self.force_game or (self._g_first is not None and now - self._g_first >= 0.8)
        return raw or (now - self._g_last < 2.5)

    def set_force_game(self, on):
        self.force_game = bool(on)
        self.say("Режим игры включён" if on else "Режим игры выключен", 2.0)

    def save_game_pos(self):
        sg = self.cur_screen().geometry()
        gyy = sg.bottom() + 1 - H + MARGIN
        self.game_pos = [round(self.cx - sg.left()), round(gyy - self.y)]
        self.save_config()

    def poll_hotkeys(self, dt):
        """Ctrl+Alt+G - режим игры вручную; Ctrl+Alt+стрелки - двигать маскота без мыши (курсор в игре захвачен)."""
        try:
            gs = user32.GetAsyncKeyState
            combo = bool(gs(0x11) & 0x8000) and bool(gs(0x12) & 0x8000)
            g = combo and bool(gs(0x47) & 0x8000)
            if g and not self._g_prev:
                self.set_force_game(not self.force_game)
                self.menu_force_sync()
            self._g_prev = g
            dx = dy = 0
            if combo and getattr(self, "in_game", False) and self.game_arrived and not self.dragging:
                dx = (1 if gs(0x27) & 0x8000 else 0) - (1 if gs(0x25) & 0x8000 else 0)
                dy = (1 if gs(0x28) & 0x8000 else 0) - (1 if gs(0x26) & 0x8000 else 0)
            if dx or dy:
                self.cx += dx * 520 * dt
                self.y += dy * 520 * dt
                self.game_target = (self.cx, self.y)
                self._kmove = True
                if dx:
                    self.dir = dx
            elif self._kmove:
                self._kmove = False
                self.save_game_pos()
        except Exception:
            pass

    def menu_force_sync(self):
        act = getattr(self, "force_action", None)
        if act is not None:
            act.blockSignals(True)
            act.setChecked(self.force_game)
            act.blockSignals(False)

    def game_step(self, dt, cur):
        """Считает, как активно ты играешь, и иногда реагирует на происходящее."""
        now = self.t
        down = set()
        try:
            for k in WATCH_KEYS:
                if user32.GetAsyncKeyState(k) & 0x8000:
                    down.add(k)
        except Exception:
            pass
        for _k in down - self.keys_down:                 # новые нажатия
            self.key_events.append(now)
        self.keys_down = down
        self.key_events = [q for q in self.key_events if now - q < 2.0]
        rate = len(self.key_events) / 2.0 + (1.5 if self.cspeed > 900 else 0.0)
        self.intensity = approach(self.intensity, min(1.0, rate / 6.0), dt * 1.5)
        if self.react and now > self.react[1]:
            self.react = None
        if not self.game_arrived or self.dragging or now < self.next_react:
            return
        self.next_react = now + random.uniform(7, 15) - 4 * self.intensity
        pool = [("cheer", 3), ("gasp", 2), ("tense", 2), ("ouch", 1)]
        if self.intensity > 0.6:
            pool += [("tense", 3), ("gasp", 2)]
        name = random.choices([n for n, _ in pool], [w for _, w in pool])[0]
        self.react = (name, now + 1.2, now)
        if name == "cheer":
            self.say(random.choice(("Ура!", "GG!", "Так держать!", "Круто!")), 1.6)
            self.show_emote(random.choice(("heart", "spark")), 1.5)
        elif name == "gasp":
            self.say(random.choice(("Ого!", "Видел?!", "Ничего себе!")), 1.5)
            self.show_emote("!", 1.3)
        elif name == "tense":
            self.say(random.choice(("Осторожно!", "Он сзади!", "Держись!")), 1.5)
            self.show_emote("sweat", 1.3)
        else:
            self.say(random.choice(("Ай!", "Мимо...", "Не повезло")), 1.4)
            self.show_emote("sweat", 1.3)

    def in_game_flag(self):
        return getattr(self, "in_game", False)

    def refresh_blockers(self):
        """Окна, которые накрывают полосу, где стоит маскот (кроме развёрнутых на весь экран)."""
        dpr = self.devicePixelRatioF() or 1.0
        scr = QGuiApplication.screenAt(QPoint(int(self.cx), int(self.y + H - 10))) or QGuiApplication.primaryScreen()
        sg = scr.geometry()
        feet = (self.y + H - MARGIN) * dpr
        top = feet - (SPR_H * P + 6) * dpr
        res = []
        for l, t, r, b, zoomed in foreign_windows(self.hwnd):
            if zoomed or ((r - l) >= sg.width() * dpr * 0.97 and (b - t) >= sg.height() * dpr * 0.9):
                continue
            if b <= top + 8 or t >= feet - 4:
                continue
            res.append((l / dpr, r / dpr))
        self.blockers = res

    def blocked(self, x):
        return any(l < x + 54 and r > x - 54 for l, r in self.blockers)

    def find_free(self, lo, hi):
        best, x = None, float(lo)
        while x <= hi:
            if not self.blocked(x) and (best is None or abs(x - self.cx) < abs(best - self.cx)):
                best = x
            x += 16
        return best

    def butterfly_pos(self):
        t = self.t
        head_y = H - MARGIN - SPR_H * P
        life = self.bt / max(self.dur, 0.1)
        x = W / 2 + 78 * math.sin(t * 0.9)
        y = head_y - 16 - 26 * abs(math.sin(t * 0.6)) + 6 * math.sin(t * 4) - max(0.0, life - 0.85) * 600
        return x, y

    def update_face(self, dt, cur):
        t = self.t
        if t >= self.next_blink:
            self.blink_until = t + 0.11
            self.next_blink = t + (0.24 if random.random() < 0.22 else random.uniform(2.2, 5.0))
        if self.beh in ("sleep", "yawn", "stretch"):
            self.gaze = (0, 0)
            return
        dx, dy = cur.x() - self.cx, cur.y() - (self.y + H - 60)
        if abs(dx) < 560 and abs(dy) < 520:           # глаза следят за курсором
            gx = 0 if abs(dx) < 40 else (1 if dx > 0 else -1)
            gyv = -1 if dy < -120 else (1 if dy > 50 else 0)
            self.gaze = (gx, gyv)
        elif t >= self.next_glance:                    # иначе оглядывается
            self.gaze = random.choice([(-1, 0), (1, 0), (0, 0), (0, 0), (-1, -1), (1, -1), (0, 1)])
            self.next_glance = t + random.uniform(0.8, 3.0)

    def logic(self, dt, cur, lo, hi):
        self.bt += dt
        b = self.beh
        t = self.t
        dx, dy = cur.x() - self.cx, cur.y() - (self.y + H - 55)
        near = abs(dx) < 120 and abs(dy) < 100
        if self.hover is not None or (self.items_alpha > 0.4 and 56 < abs(dx) < W / 2 and 1 < dy < 55):
            near = False                                # тянется к его вещам - не пугается
        calm = ("stand", "walk", "sit", "eat", "sleep", "jump", "look", "stretch", "yawn", "curious", "hop3", "juggle",
                "sing", "butterfly", "sneak", "stargaze", "hungry", "hello", "spin", "workout")
        if self.mode == "idle" and near and self.cspeed > 250 and not self.air and b in calm:
            self.dir = -1 if dx > 0 else 1
            self.cookie = None
            self.enter("flee")
            b = "flee"
        # окно накрыло маскота - убегаем на свободное место
        if (self.blockers and not self.air and not self.dragging and not self.pending
                and b not in ("evade", "flee") and self.blocked(self.cx)):
            tx = self.find_free(lo, hi)
            if tx is not None and abs(tx - self.cx) > 20:
                self.target_x = tx
                self.cookie = None
                self.show_emote("!", 1.0)
                self.enter("evade")
                b = "evade"
            elif t - self.tight_t > 20:
                self.tight_t = t
                self.say("Тесно тут!", 2.0)
        # приятно, когда рядом спокойный курсор
        if (self.mode == "idle" and self.hover is None and abs(dx) < 110 and abs(dy) < 110 and self.cspeed < 120
                and b in ("stand", "sit", "look", "walk")):
            self.hover_t += dt
            if self.hover_t > 2.2:
                self.hover_t = -8.0
                self.show_emote("heart", 2.0)
                self.say("Ты тут?", 1.8)
                self.enter("wiggle")
                b = "wiggle"
        elif self.hover_t < 0:
            self.hover_t = min(0.0, self.hover_t + dt)       # пауза между приступами нежности
        else:
            self.hover_t = max(0.0, self.hover_t - dt)
        if self.mode == "idle" and t >= self.next_thought and b in ("stand", "sit", "walk", "look"):
            self.say(random.choice(THOUGHTS), 2.5)
            self.next_thought = t + random.uniform(25, 50)
        if self.mode == "done":
            self.done_left -= dt
            if self.done_left <= 0:
                self.set_mode("idle")
                b = self.beh
        if self.confetti_left > 0:
            self.confetti_left -= dt
            if random.random() < dt * 22:
                self.burst(1)

        if b in MOVERS:
            sp, ph, di = MOVERS[b]
            nx = self.cx + self.dir * sp * dt
            if b != "flee" and self.blockers and self.blocked(nx):
                self.dir = -self.dir                      # упёрся в окно - разворот
                nx = self.cx
            self.cx = nx
            self.phase += dt * ph
            self.dust_t -= dt
            if self.dust_t <= 0:
                self.dust_t = di
                self.dust(1 if b in ("walk", "sneak") else 2)
            if b == "zoomies" and t - self.last_hop > 0.75:
                self.last_hop = t
                if random.random() < 0.5:
                    self.dir = -self.dir
                if not self.air:
                    self.launch(-430, delay=0.04)
            if self.cx <= lo + 1 or self.cx >= hi - 1:
                self.dir = -self.dir
                if b == "flee" and not self.air:
                    self.launch(-850, self.dir * 380)
                else:
                    self.cx = max(lo + 2, min(hi - 2, self.cx))
        elif b == "sing":
            if t - self.last_hop > 0.9:
                self.last_hop = t
                self.show_emote("note", 0.9)
        elif b == "sneeze":
            if self.bt >= 0.9 and not self.sneezed:
                self.sneezed = True
                self.sq, self.sqv = 0.35, 0.0
                self.say("Апчхи!", 1.4)
                self.launch(-260, -self.dir * 140)
                for _ in range(12):
                    life = random.uniform(0.3, 0.5)
                    self.particles.append(dict(kind="d", x=W / 2 + self.dir * 22, y=H - MARGIN - SPR_H * P * 0.55,
                                               vx=self.dir * random.uniform(120, 280), vy=random.uniform(-50, 50),
                                               col=QColor(235, 245, 255), spin=0, life=life, l0=life))
        elif b == "workout":
            if not self.air and not self.pending and self.reps < 5 and t - self.last_hop > 0.62:
                self.last_hop = t
                self.reps += 1
                self.launch(-430, delay=0.05)
                self.say(str(self.reps), 0.6)
        elif b == "butterfly":
            bx, _ = self.butterfly_pos()
            if not self.air and not self.pending and t - self.last_hop > 1.8 and abs(bx - W / 2) < 70:
                self.last_hop = t
                self.launch(-600, delay=0.1)
        elif b == "evade":
            d = 1 if self.target_x > self.cx else -1
            self.dir = d
            step = 300 * dt
            self.phase += dt * 20
            self.dust_t -= dt
            if self.dust_t <= 0:
                self.dust_t = 0.07
                self.dust(2)
            if abs(self.target_x - self.cx) <= step:
                self.cx = self.target_x
                self.pick()
            else:
                self.cx += d * step
        elif b == "curious":
            if self.arrived is None:
                d = 1 if dx > 0 else -1
                self.dir = d
                if self.blockers and self.blocked(self.cx + d * 12):
                    self.pick()
                    return
                self.cx += d * 95 * dt
                self.phase += dt * 9
                if abs(dx) < 150:
                    self.arrived = self.bt
                    self.show_emote("q", 2.6)
            elif self.bt - self.arrived > 2.6:
                self.pick()
        elif b == "work":
            self.phase += dt * 8
            if t >= self.next_say:
                self.mode_bubble = (random.choice(WORK_LINES), t + 3.0)
                self.next_say = t + random.uniform(8, 14)
                if random.random() < 0.35:
                    self.show_emote("spark", 1.2)
            if 7.2 < t % 9 < 7.35 and t - self.last_q > 2:
                self.last_q = t
                self.show_emote("q", 1.4)
        elif b == "dance":
            self.phase += dt * 11
            if not self.air and t - self.last_hop > 0.5:
                self.last_hop = t
                self.launch(-470, delay=0.05)
                self.show_emote(random.choice(("note", "note", "spark")), 0.9)
        elif b == "wave":
            self.phase += dt * 10
            if not self.air and self.bt > 1.2 and t - self.last_hop > 2.2:
                self.last_hop = t
                self.launch(-520, delay=0.1)
        elif b == "hop3":
            if not self.air and t - self.last_hop > 0.55:
                self.last_hop = t
                self.launch(-520, delay=0.08)
        elif b == "wiggle":
            self.phase += dt * 14
        elif b == "eat":
            if self.cookie is not None:
                self.cookie = max(0.0, 1 - self.bt / 4.5)
                if random.random() < dt * 5 and self.cookie < 0.95:
                    self.crumb()
        timed = ("walk", "stand", "sit", "sleep", "eat", "flee", "dizzy", "look", "stretch", "yawn", "wiggle",
                 "juggle", "sneeze", "sing", "spin", "butterfly", "zoomies", "sneak", "workout", "stargaze",
                 "hungry", "hello")
        if b in timed and self.bt >= self.dur:
            self.cookie = None
            if b == "yawn":
                self.enter("sleep")
            elif b == "sleep":
                self.enter("stretch")
            elif b == "hungry":
                self.enter("eat")
            elif b == "sneak" and random.random() < 0.6:
                self.enter("zoomies")
            else:
                if b == "workout":
                    self.say("Уф!", 1.5)
                    self.show_emote("sweat", 1.5)
                elif b == "butterfly":
                    self.say("Улетела...", 1.8)
                if b == "eat":
                    self.show_emote("heart", 1.6)
                self.pick()
        elif b in ("jump", "hop3") and self.bt >= self.dur and not self.air and not self.pending:
            self.pick()
        elif b in ("curious", "evade") and self.bt >= self.dur:
            self.pick()

    # ------------------------------------------------ поза
    def make_pose(self, cur):
        t = self.t
        d = base_pose(t)
        b = self.beh
        air = self.air
        d["phase"] = self.phase
        d["face"] = self.dir
        d["look"], d["lookdy"] = self.gaze
        d["eyes"] = "closed" if t < self.blink_until else "open"
        sph = math.sin(self.phase)
        d["cl"] = (0.06 + 0.05 * math.sin(t * 1.7), False)
        d["cr"] = (0.06 + 0.05 * math.sin(t * 1.7 + 1.3), False)
        rot, bob, sqx = 0.0, 0.0, 0.0
        sqx += 0.012 * math.sin(t * 2.2)            # дыхание

        if b == "walk":
            d["legs"] = "walk"
            d["look"] = self.dir
            d["cl"] = (0.18 + 0.20 * sph, False)
            d["cr"] = (0.18 - 0.20 * sph, False)
            rot = 2.5 * sph + self.dir * 1.5
            bob = -abs(sph) * 3
        elif b == "curious":
            moving = self.arrived is None
            d["legs"] = "walk" if moving else "stand"
            d["eyes"] = "wide" if not moving else d["eyes"]
            d["look"] = 1 if cur.x() > self.cx else -1
            d["cl"] = (0.15 + (0.2 * sph if moving else 0), False)
            d["cr"] = (0.15 - (0.2 * sph if moving else 0), False)
            rot = (2.5 * sph if moving else 4 * math.sin(t * 3)) + self.dir * 3
            bob = -abs(sph) * 3 if moving else 0
        elif b in ("flee", "evade"):
            d["legs"] = "walk"
            d["look"] = -self.dir
            d["eyes"] = "wide"
            d["cl"] = (0.80 + 0.15 * math.sin(self.phase * 2), False)
            d["cr"] = (0.80 - 0.15 * math.sin(self.phase * 2), False)
            rot = self.dir * 9
            bob = -abs(sph) * 4
        elif b == "sit":
            d["by"] = 8
            d["legs"] = "sit"
            rot = 1.5 * math.sin(t * 0.8)
        elif b == "look":
            rot = 3 * math.sin(t * 1.5)
            d["cr"] = (0.06 + 0.04 * math.sin(t * 3), False)
        elif b == "yawn":
            f = min(1.0, self.bt / self.dur)
            d["eyes"] = "half" if f < 0.3 else "closed"
            d["cl"] = (0.15 + 0.5 * math.sin(f * math.pi), False)
            d["cr"] = (0.15 + 0.5 * math.sin(f * math.pi), False)
            sqx = -0.12 * math.sin(f * math.pi)
            d["look"], d["lookdy"] = 0, 0
        elif b == "stretch":
            f = min(1.0, self.bt / self.dur)
            s = math.sin(f * math.pi)
            d["eyes"] = "closed" if 0.15 < f < 0.8 else "half"
            d["cl"] = (min(1.0, 1.2 * s), False)
            d["cr"] = (min(1.0, 1.2 * s), False)
            sqx = -0.16 * s
            rot = 2 * math.sin(f * 12) * s
            d["look"], d["lookdy"] = 0, 0
        elif b == "sleep":
            d["by"] = 8
            d["legs"] = "sit"
            d["eyes"] = "closed"
            d["look"], d["lookdy"] = 0, 0
            d["cl"] = (0.0, False)
            d["cr"] = (0.0, False)
            sqx = -0.035 * math.sin(t * 1.6)
            rot = 1.5 * math.sin(t * 0.9)
        elif b == "eat":
            d["cookie"] = self.cookie if self.cookie else None
            d["eyes"] = "happy" if int(t * 3) % 4 == 0 else d["eyes"]
            d["cr"] = (0.30 + 0.06 * math.sin(t * 9), False)
            sqx = 0.02 * math.sin(t * 9)
            rot = 2 * math.sin(t * 4.5)
        elif b == "work":
            d["by"] = 8
            d["legs"] = "sit"
            d["lookdy"] = 1
            d["look"] = [-1, 0, 1, 0][int(t * 4) % 4]    # глаза бегают по строкам
            tap = int(t * 9) % 2
            d["cl"] = (0.0, False) if tap else (0.17, False)
            d["cr"] = (0.17, False) if tap else (0.0, False)
            rot = 1.2 * math.sin(t * 9)
            sqx += 0.012 * math.sin(t * 9)
            if 7.2 < t % 9 < 8.6:                       # задумался, чешет голову
                d["cr"] = (0.92 + 0.05 * math.sin(t * 20), False)
                d["cl"] = (0.0, False)
                d["lookdy"], d["look"] = -1, 1
                rot = 3 * math.sin(t * 2)
        elif b == "dance":
            d["legs"] = "dance"
            d["eyes"] = "happy"
            d["cl"] = (0.55 + 0.45 * sph, False)
            d["cr"] = (0.55 - 0.45 * sph, False)
            rot = 8 * math.sin(self.phase * 0.5)
        elif b == "wave":
            d["eyes"] = "wide" if int(t * 2) % 2 else d["eyes"]
            d["cl"] = (0.50 + 0.40 * math.sin(t * 9 + math.pi), False)
            d["cr"] = (0.60 + 0.40 * math.sin(t * 9), False)
            rot = 3.5 * math.sin(t * 9)
            d["look"], d["lookdy"] = 0, 0
        elif b == "wiggle":
            d["legs"] = "dance"
            d["eyes"] = "happy"
            d["cl"] = (0.50 + 0.50 * math.sin(self.phase), False)
            d["cr"] = (0.50 - 0.50 * math.sin(self.phase), False)
            rot = 7 * math.sin(self.phase * 1.6)
        elif b == "hop3":
            d["eyes"] = "happy"
            d["cl"] = (0.85, False)
            d["cr"] = (0.85, False)
        elif b == "dizzy":
            d["by"] = 8
            d["legs"] = "sit"
            d["eyes"] = "x"
            d["cl"] = (0.0, False)
            d["cr"] = (0.0, False)
            rot = 8 * math.sin(t * 9)
        elif b == "juggle":
            th = t * 3.2
            d["eyes"] = "wide" if int(t * 5) % 3 == 0 else "open"
            d["look"] = 1 if math.cos(th) > 0 else -1
            d["lookdy"] = -1
            d["cl"] = (0.75 + 0.2 * math.sin(th), False)
            d["cr"] = (0.75 - 0.2 * math.sin(th), False)
            rot = 3 * math.sin(th)
        elif b == "sneeze":
            f = self.bt
            if f < 0.9:
                k = f / 0.9
                d["eyes"] = "half" if k < 0.5 else "closed"
                sqx = -0.20 * k
                d["cl"] = (0.35 * k, False)
                d["cr"] = (0.35 * k, False)
                rot = -self.dir * 4 * k
            else:
                d["eyes"] = "closed"
                d["cl"] = (0.5, False)
                d["cr"] = (0.5, False)
                rot = self.dir * 6 * math.exp(-(f - 0.9) * 4)
        elif b == "sing":
            d["eyes"] = "happy" if int(t * 2) % 2 else "closed"
            d["cl"] = (0.4 + 0.3 * math.sin(t * 3), False)
            d["cr"] = (0.4 + 0.3 * math.sin(t * 3 + 2), False)
            rot = 6 * math.sin(t * 3)
            sqx += 0.03 * math.sin(t * 6)
        elif b == "spin":
            d["eyes"] = "happy"
            d["legs"] = "dance"
            d["cl"] = (0.6, False)
            d["cr"] = (0.6, False)
            d["sxm"] = abs(math.cos(2 * math.pi * 2 * self.bt / self.dur)) * 0.92 + 0.08
        elif b == "butterfly":
            bx, _ = self.butterfly_pos()
            right = bx > W / 2
            d["look"] = 1 if right else -1
            d["lookdy"] = -1
            d["eyes"] = "wide"
            reach = 0.6 + 0.3 * math.sin(t * 5)
            d["cr"] = (reach if right else 0.15, False)
            d["cl"] = (0.15 if right else reach, False)
            rot = 4 if right else -4
        elif b == "zoomies":
            d["legs"] = "walk"
            d["eyes"] = "happy"
            d["cl"] = (0.8 + 0.15 * math.sin(self.phase * 2), False)
            d["cr"] = (0.8 - 0.15 * math.sin(self.phase * 2), False)
            rot = self.dir * 10
            bob = -abs(sph) * 5
        elif b == "sneak":
            d["by"] = 7
            d["legs"] = "walk"
            d["look"] = [-1, 1][int(t * 2) % 2]
            d["eyes"] = "wide"
            d["cl"] = (0.0, False)
            d["cr"] = (0.0, False)
            rot = self.dir * 3 + 2 * sph
        elif b == "workout":
            s2 = 0.5 + 0.5 * math.sin(t * 10)
            d["legs"] = "dance"
            d["cl"] = (s2, False)
            d["cr"] = (s2, False)
            d["eyes"] = "wide" if s2 > 0.7 else "open"
        elif b == "stargaze":
            d["by"] = 8
            d["legs"] = "sit"
            d["lookdy"] = -1
            d["look"] = [-1, 0, 1, 0][int(t * 0.7) % 4]
            rot = 1.5 * math.sin(t * 0.8)
        elif b == "hungry":
            d["eyes"] = "half"
            d["lookdy"] = 1
            sqx += 0.05 * math.sin(t * 26)
            rot = 2 * math.sin(t * 30)
        elif b == "hello":
            d["eyes"] = "happy"
            d["cr"] = (0.85 + 0.15 * math.sin(t * 11), False)
            rot = 3 * math.sin(t * 6)
        elif b == "peek":
            d["eyes"] = "wide" if (t % 9.0) > 5.0 else "open"
            d["look"] = -self.peek_side if getattr(self, "peek_up", 0) > 0.5 else -self.peek_side * (1 if (t * 0.9) % 3.0 < 1.5 else 0)
            d["cl"] = d["cr"] = (0.85, False)             # цепляется ручками за край
            d["legs"] = "stand"
            d["face"] = -self.peek_side
        elif b == "play":
            it = self.intensity
            sg = self.cur_screen().geometry()
            dxs = sg.center().x() - self.cx
            d["look"] = 1 if dxs > 50 else -1 if dxs < -50 else 0       # смотрит в экран
            d["lookdy"] = 0
            rate = 5 + 14 * it
            d["legs"] = "stand"
            d["cl"] = (0.30 + 0.14 * math.sin(t * rate), False)          # давит на кнопки
            d["cr"] = (0.30 + 0.14 * math.sin(t * rate + 2.1), False)
            d["eyes"] = "wide" if it > 0.55 else "open"
            rot = (1.2 + 3.0 * it) * math.sin(t * 2.2)
            sqx += 0.02 * math.sin(t * rate)
            if self.react:
                kind, until, t0 = self.react
                f = (t - t0)
                if kind == "cheer":
                    bob = -abs(math.sin(f * 9)) * 16
                    d["cl"] = d["cr"] = (1.0, False)
                    d["eyes"] = "happy"
                elif kind == "gasp":
                    d["eyes"] = "wide"
                    sqx += -0.10 * min(1.0, f * 6)
                    d["cl"] = d["cr"] = (0.7, False)
                elif kind == "tense":
                    d["eyes"] = "wide"
                    sqx += 0.07
                    rot += 5 * math.sin(f * 30)
                else:
                    d["eyes"] = "x"
                    rot += 7 * math.sin(f * 24)
        elif b == "bye":
            d["eyes"] = "happy"
            if self.bt < 0.9:
                d["cr"] = (0.85 + 0.15 * math.sin(t * 14), False)
                rot = 3 * math.sin(t * 8)
            else:                                       # приседает и схлопывается
                f = min(1.0, (self.bt - 0.9) / 0.5)
                d["eyes"] = "closed"
                d["cl"] = d["cr"] = (0.0, False)
                sqx += 0.55 * f
        if b in ("stand", "sit", "look", "hello"):
            if (t % 11) < 0.4:
                d["wink"] = 1                           # подмигивает
            if (t % 7) < 0.45 and b != "hello":         # пожимает плечами
                d["cl"] = (0.55, False)
                d["cr"] = (0.55, False)
        if self.dragging:
            d["legs"] = "air"
            d["eyes"] = "wide"
            d["cl"] = (0.85 + 0.12 * math.sin(t * 14), False)
            d["cr"] = (0.85 - 0.12 * math.sin(t * 14), False)
            d["by"] = 6
            d["cookie"] = None
            rot = 14 * math.sin(t * 5)
            if self.hang:                                 # висит на одной лапке
                held, free = (0.7, False), (0.1, False)
                if self.hang_arm == 0:
                    d["cl"] = d["cr"] = free
                else:
                    d["cl"], d["cr"] = (held, free) if self.hang_arm > 0 else (free, held)
                d["eyes"] = "wide"
                rot = self.hang_ang
        elif air and b not in ("dance", "wave", "hop3"):
            d["legs"] = "air"
            d["eyes"] = "wide"
            d["cl"] = (0.85 + 0.1 * math.sin(t * 14), False)
            d["cr"] = (0.85 - 0.1 * math.sin(t * 14), False)
            d["by"] = 6
            d["cookie"] = None
        elif air:
            d["legs"] = "air"
        if t < self.happy_until and b not in ("dance", "dizzy"):
            d["eyes"] = "happy"
        if t < self.annoy_until:
            d["eyes"] = "half"
            d["cl"] = (0.0, False)
            d["cr"] = (0.0, False)
            rot += 5 * math.sin(t * 34)
        d["by"] = max(0, min(2, d["by"] - 6))
        if self.thrown or self.tumble:
            rot = self.tumble
            if self.thrown:
                d["eyes"] = "x" if abs(self.vx) > 900 else "wide"
        d["phones"] = self.batt is not None
        d["rot"], d["bob"], d["sqx"] = rot, bob, sqx
        return d

    # ------------------------------------------------ рисование
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        d = self.pose
        total_sq = self.sq + d["sqx"]
        sy = max(0.6, 1.0 - total_sq)
        sx = (1.0 + total_sq * 0.7) * d.get("sxm", 1.0)
        feet_y = H - MARGIN
        if not self.air and not self.dragging:
            half = SPR_W * P * 0.55 * sx
            p.fillRect(int(W / 2 - half), feet_y - 1, int(half * 2), 4, QColor(0, 0, 0, 55))
        p.save()
        if self.dragging and self.hang:
            p.translate(W / 2, HANG_Y)                    # вращаем вокруг лапки, за которую держат
            p.rotate(self.hang_ang)
            p.scale(P, P)
            p.translate(-self.hang_px, -self.hang_py)
        elif self.dragging:
            p.translate(W / 2, feet_y - SPR_H * P)
            p.rotate(self.rot)
            p.scale(P * sx, P * sy)
            p.translate(-12, 0)
        else:
            # вращаем вокруг центра тела; самый нижний угол всегда стоит на земле (не вылезает из окна)
            th = math.radians(self.rot)
            hw, hh = SPR_W * P / 2 * sx, SPR_H * P / 2 * sy
            ext = hw * abs(math.sin(th)) + hh * abs(math.cos(th))
            p.translate(W / 2, feet_y - ext + d["bob"])
            p.rotate(self.rot)
            p.scale(P * sx, P * sy)
            p.translate(-12, -SPR_H / 2)
        draw_sprite(p, d)
        p.restore()

        self.paint_extras(p, d)
        self.paint_gadgets(p)
        self.paint_particles(p)
        self.paint_bubble(p)
        p.end()

    def paint_battery(self, p, head_y):
        left = self.batt_show_until - self.t
        alpha = max(0.0, min(1.0, left / 0.5, (6.0 - left) / 0.25 if left > 5.5 else 1.0))
        pct = self.batt
        side = -1 if self.cx > self.cur_screen().geometry().center().x() else 1
        bw, bh = 30, 14
        x = W / 2 + side * (SPR_W * P / 2 + 8) + (0 if side > 0 else -bw - 4)
        y = head_y + 6 + 2 * math.sin(self.t * 4)
        col = QColor(90, 205, 115) if pct > 50 else QColor(245, 205, 70) if pct > 20 else QColor(235, 70, 70)
        if pct <= 15 and int(self.t * 3) % 2:
            col = QColor(255, 140, 120)
        p.save()
        p.setOpacity(alpha)
        p.fillRect(int(x - 2), int(y - 2), bw + 4, bh + 4, QColor(25, 25, 30, 235))
        p.fillRect(int(x + bw + 2), int(y + 4), 3, bh - 8, QColor(25, 25, 30, 235))
        p.fillRect(int(x), int(y), bw, bh, QColor(55, 55, 62))
        p.fillRect(int(x), int(y), max(2, int(bw * pct / 100)), bh, col)
        f = QFont("Segoe UI", 9)
        f.setBold(True)
        p.setFont(f)
        txt = f"{pct}%"
        for ox, oy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            p.setPen(QColor(20, 20, 24))
            p.drawText(QRectF(x + ox, y + bh + 3 + oy, bw, 16), Qt.AlignCenter, txt)
        p.setPen(WHITE)
        p.drawText(QRectF(x, y + bh + 3, bw, 16), Qt.AlignCenter, txt)
        p.restore()

    def paint_extras(self, p, d):
        t = self.t
        head_y = H - MARGIN - SPR_H * P + d["by"] * P
        if self.beh == "play" and not self.dragging:
            shake = 0 if self.intensity < 0.2 else int(2 * math.sin(t * 40))
            draw_icon(p, "gamepad", W / 2 - 18 + shake, H - MARGIN - 38 + d["bob"], t=t)
            if self.intensity > 0.3 and int(t * 12) % 2:       # кнопки мигают, когда жмёшь
                p.fillRect(int(W / 2 + 9), int(H - MARGIN - 32 + d["bob"]), 3, 3, QColor(255, 235, 140))
        if self.batt is not None and self.t < self.batt_show_until:
            self.paint_battery(p, head_y)
        if self.beh == "work":
            self.paint_workstation(p, t)
            n = int(t * 2.6) % 4
            for i in range(min(n, 3)):
                bounce = -6 * max(0.0, math.sin(t * 7 - i * 1.0))
                x = W / 2 + (i - 1) * 16
                y = head_y - 16 + bounce
                p.fillRect(int(x - 5), int(y - 5), 10, 10, WHITE)
                p.fillRect(int(x - 3), int(y - 3), 6, 6, QColor(60, 50, 55))
        if self.beh in ("sleep", "yawn"):
            for i in range(3):
                ph = (t * 0.5 + i / 3.0) % 1.0
                f = QFont("Segoe UI", 10 + i * 3)
                f.setBold(True)
                p.setFont(f)
                x = W / 2 + 26 + ph * 16 + i * 4
                y = head_y + 8 - ph * 40
                al = int(255 * (1 - ph))
                p.setPen(QColor(40, 40, 60, al))
                p.drawText(int(x + 1), int(y + 1), "z")
                p.setPen(QColor(255, 255, 255, al))
                p.drawText(int(x), int(y), "z")
        if self.mode == "attention":
            f = QFont("Segoe UI", 26)
            f.setBold(True)
            p.setFont(f)
            y = head_y - 14 - abs(math.sin(t * 7)) * 8
            p.setPen(QColor(40, 20, 20))
            p.drawText(int(W / 2 + 36), int(y + 2), "!")
            p.setPen(QColor(255, 90, 60))
            p.drawText(int(W / 2 + 34), int(y), "!")
        if self.beh == "juggle":
            for i, c in enumerate((QColor(255, 90, 90), QColor(255, 210, 70), QColor(90, 170, 255))):
                th = t * 3.2 + i * 2.094
                x = W / 2 + 34 * math.cos(th)
                y = head_y - 8 + 16 * math.sin(th)
                p.fillRect(int(x - 4), int(y - 4), 8, 8, QColor(40, 30, 30))
                p.fillRect(int(x - 3), int(y - 3), 6, 6, c)
        if self.beh == "butterfly":
            bx, by_ = self.butterfly_pos()
            w = 6 if int(t * 14) % 2 else 3
            p.fillRect(int(bx - 1), int(by_ - 3), 2, 7, QColor(50, 35, 35))
            p.fillRect(int(bx - 1 - w), int(by_ - 4), w, 5, QColor(255, 150, 200))
            p.fillRect(int(bx + 1), int(by_ - 4), w, 5, QColor(255, 150, 200))
            p.fillRect(int(bx - w), int(by_ + 1), w - 1, 3, QColor(255, 205, 120))
            p.fillRect(int(bx + 1), int(by_ + 1), w - 1, 3, QColor(255, 205, 120))
        if self.beh == "stargaze":
            xs = (-70, -40, 50, 80, -15, 25)
            ys = (30, 62, 46, 26, 74, 58)
            for i in range(6):
                al = int(255 * max(0.0, math.sin(t * 2 + i * 1.3)))
                c = QColor(255, 236, 160, al)
                x, y = W / 2 + xs[i], head_y - ys[i]
                p.fillRect(int(x - 1), int(y - 4), 2, 8, c)
                p.fillRect(int(x - 4), int(y - 1), 8, 2, c)
        if self.emote and t < self.emote[1]:
            name, until, t0 = self.emote
            age = t - t0
            cell = 4 if age >= 0.15 else 3
            y = head_y - 34 - abs(math.sin(age * 6)) * 5
            draw_emote(p, name, W / 2 + 30, y, cell)

    def paint_workstation(self, p, t):
        feet_y = H - MARGIN
        # клавиатура перед ним: клавиши мигают в такт печати
        kx, ky, kw, kh = W / 2 - 52, feet_y - 16, 104, 10
        p.fillRect(int(kx), int(ky), kw, kh, QColor(58, 60, 70))
        p.fillRect(int(kx), int(ky), kw, 2, QColor(92, 96, 110))
        for i in range(12):
            for j in range(2):
                on = (i * 7 + j * 3 + int(t * 9) * 5) % 11 == 0
                col = QColor(130, 200, 255) if on else QColor(98, 102, 116)
                p.fillRect(int(kx + 4 + i * 8), int(ky + 3 + j * 3), 6, 2, col)
        # мини-монитор с бегущим кодом (со стороны, где больше места)
        a = self.avail()
        side = -1 if self.cx > a.center().x() else 1
        px = W / 2 + side * (SPR_W * P / 2 + 12) + (0 if side > 0 else -72)
        py = feet_y - 66
        p.fillRect(int(px - 2), int(py - 2), 76, 54, QColor(90, 95, 110))
        p.fillRect(int(px), int(py), 72, 50, QColor(26, 28, 36))
        for i, c in enumerate((QColor(255, 95, 90), QColor(255, 190, 60), QColor(80, 200, 110))):
            p.fillRect(int(px + 3 + i * 6), int(py + 3), 4, 4, c)
        scroll = int(t * 3)
        pal = (QColor(217, 127, 89), QColor(130, 200, 255), QColor(160, 230, 140),
               QColor(220, 220, 235), QColor(200, 150, 255))
        for i in range(5):
            n = i + scroll
            ln = 10 + (n * 37) % 38
            ind = ((n * 5) % 3) * 6
            p.fillRect(int(px + 4 + ind), int(py + 12 + i * 7), int(ln), 3, pal[n % len(pal)])
        if int(t * 2) % 2 == 0:
            n = 4 + scroll
            p.fillRect(int(px + 4 + ((n * 5) % 3) * 6 + 10 + (n * 37) % 38 + 2), int(py + 12 + 4 * 7), 3, 5, WHITE)

    def paint_particles(self, p):
        for q in self.particles:
            if q["kind"] == "c":
                p.fillRect(int(q["x"]), int(q["y"]), 7, max(1, int(5 * abs(math.cos(q["spin"])))), q["col"])
            elif q["kind"] == "d":
                f = q["life"] / q["l0"]
                s = int(3 + (1 - f) * 6)
                c = QColor(q["col"])
                c.setAlpha(int(150 * f))
                p.fillRect(int(q["x"]), int(q["y"] - s / 2), s, s, c)
            else:
                p.fillRect(int(q["x"]), int(q["y"]), 3, 3, q["col"])

    def gadget_items(self):
        devs = list(self.scanner.devices)
        if self.batt is not None:
            devs.insert(0, dict(key="headset", label="Наушники HyperX", pct=self.batt, approx=None, note=""))
        decor = [dict(key=k, label=tip, pct=None, approx=None, note="", decor=True) for k, tip in DECOR]
        return devs + decor

    def paint_gadgets(self, p):
        """Вещи вокруг маскота: подключённые гаджеты и всякая мебель; при наведении - заряд."""
        self.gadget_rects = []
        if self.items_alpha <= 0.01:
            return
        feet_y = H - MARGIN
        pref = -1 if self.cx > self.cur_screen().geometry().center().x() else 1
        used = {1: SPR_W * P / 2 + 16, -1: SPR_W * P / 2 + 16}
        limit = W / 2 - 4
        side = pref
        p.save()
        p.setOpacity(self.items_alpha)
        hovered = None
        for item in self.gadget_items():
            w, h = icon_size(item["key"])
            if used[side] + w > limit:
                side = -side
                if used[side] + w > limit:
                    continue
            off = used[side]
            used[side] += w + 8
            x = W / 2 + off if side > 0 else W / 2 - off - w
            is_h = self.hover is not None and item["key"] == self.hover["key"]
            lift = 3 if is_h else 0
            y = feet_y - h - lift
            draw_icon(p, item["key"], x, y, t=self.t, glow=is_h)
            item_rect = QRectF(x - 3, y - 4, w + 6, h + 8)
            self.gadget_rects.append((item_rect, item))
            if is_h:
                hovered = (item, item_rect)
        if hovered:
            self.paint_gadget_tip(p, *hovered)
        p.restore()

    def paint_gadget_tip(self, p, item, rect):
        if item.get("decor"):
            text, pct = item["label"], None
        else:
            pct = item["pct"] if item["pct"] is not None else item.get("approx")
            if item["pct"] is not None:
                text = f"{item['label']}: {item['pct']}%"
            else:
                text = f"{item['label']}: {item['note'] or 'нет данных'}"
        f = QFont("Segoe UI", 9)
        f.setBold(True)
        p.setFont(f)
        tw = QFontMetrics(f).horizontalAdvance(text)
        bw, bh = tw + 18, 28 if pct is not None else 24
        bx = max(4, min(W - bw - 4, rect.center().x() - bw / 2))
        by = rect.top() - bh - 8
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(28, 28, 34, 240))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 6, 6)
        p.setPen(WHITE)
        p.drawText(QRectF(bx, by + 2, bw, 20), Qt.AlignCenter, text)
        if pct is not None:
            col = QColor(90, 205, 115) if pct > 50 else QColor(245, 205, 70) if pct > 20 else QColor(235, 70, 70)
            p.fillRect(int(bx + 9), int(by + bh - 7), int(bw - 18), 3, QColor(70, 70, 78))
            p.fillRect(int(bx + 9), int(by + bh - 7), max(2, int((bw - 18) * pct / 100)), 3, col)

    def paint_bubble(self, p):
        text = None
        if self.temp_bubble and self.t < self.temp_bubble[1]:
            text = self.temp_bubble[0]
        elif self.mode_bubble and self.t < self.mode_bubble[1]:
            text = self.mode_bubble[0]
        if not text:
            return
        f = QFont("Segoe UI", 12)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 28, fm.height() + 14
        bottom = H - MARGIN - SPR_H * P - 34
        x, y = W / 2 - w / 2, bottom - h
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), 10, 10)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(60, 40, 38), 2.5)
        p.setPen(pen)
        p.setBrush(QColor(255, 253, 248))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(W / 2 - 7, bottom - 1), QPointF(W / 2 + 7, bottom - 1),
                                 QPointF(W / 2, bottom + 11)]))
        p.setPen(pen)
        p.drawLine(QPointF(W / 2 - 7, bottom), QPointF(W / 2, bottom + 11))
        p.drawLine(QPointF(W / 2 + 7, bottom), QPointF(W / 2, bottom + 11))
        p.setPen(QColor(50, 34, 32))
        p.drawText(QRectF(x, y, w, h), Qt.AlignCenter, text)
        p.setRenderHint(QPainter.Antialiasing, False)

    # ------------------------------------------------ мышь
    def mousePressEvent(self, e):
        if self.hover is not None:
            return
        if e.button() == Qt.LeftButton:
            self.pressed = True
            self.press_global = e.globalPosition().toPoint()
            self.drag_off = self.press_global - self.pos()
            self.press_local = e.position().toPoint()
            self.dragging = False

    def mouseMoveEvent(self, e):
        if not self.pressed:
            return
        g = e.globalPosition().toPoint()
        if not self.dragging and (g - self.press_global).manhattanLength() > 6:
            self.dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self.drag_samples = []
            self.slide = 0.0
            self.cookie = None
            self.pending = None
            self.beh = "drag"
            self.vy = self.vx = 0.0
            self.show_emote("!", 1.0)
            # висит на той точке, за которую схватили: тело свешивается вниз под ней
            lx, ly = self.press_local.x(), self.press_local.y()
            x0 = W / 2 - SPR_W * P / 2
            top = H - MARGIN - SPR_H * P
            self.hang = 1
            self.hang_px = max(0.0, min(float(SPR_W), (lx - x0) / P))
            self.hang_py = max(0.0, min(float(SPR_H), (ly - top) / P))
            vcx, vcy = 12 - self.hang_px, 7.5 - self.hang_py
            self.hang_tgt = 0.0 if math.hypot(vcx, vcy) < 1.5 else 90.0 - math.degrees(math.atan2(vcy, vcx))
            self.hang_arm = 0
            if self.hang_py < 10:
                if self.hang_px < 3.5:
                    self.hang_arm = 1
                elif self.hang_px > 20.5:
                    self.hang_arm = -1
            self.hang_ang, self.hang_vel = self.rot, 0.0
            self.write_status()
        if self.dragging and self.hang:
            self.hang_vel += (g.x() - getattr(self, "_last_gx", g.x())) * 2.2    # раскачивается за мышью
            self.cx = float(g.x())
            self.y = float(g.y() - HANG_Y)
        elif self.dragging:
            tl = g - self.drag_off
            self.cx = tl.x() + W / 2
            self.y = float(tl.y())
        self._last_gx = g.x()
        if self.dragging:
            now = time.perf_counter()
            self.drag_samples = [q for q in self.drag_samples if now - q[0] < 0.12] + [(now, float(g.x()), float(g.y()))]

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self.pressed:
            return
        self.pressed = False
        if self.dragging:
            was_hang = self.hang
            if was_hang:                                   # перенос окна так, чтобы тело осталось там же
                th = math.radians(self.hang_ang)
                dx = (12 - self.hang_px) * P
                dy = (7.5 - self.hang_py) * P
                wx = self.cx + dx * math.cos(th) - dy * math.sin(th)
                wy = self.y + HANG_Y + dx * math.sin(th) + dy * math.cos(th)
                ext = SPR_W * P / 2 * abs(math.sin(th)) + SPR_H * P / 2 * abs(math.cos(th))
                self.cx = wx
                self.y = wy - (H - MARGIN - ext)
                self.rot = self.hang_ang
                self.hang = 0
            self.dragging = False
            self.setCursor(Qt.OpenHandCursor)
            if getattr(self, "in_game", False):         # в игре: ставишь его куда хочешь, он там и стоит
                sg = self.cur_screen().geometry()
                self.air = False
                self.thrown = False
                self.vx = self.vy = 0.0
                self.tumble = self.rot
                self.drag_samples = []
                gyy = sg.bottom() + 1 - H + MARGIN
                self.cx = max(sg.left() + 40.0, min(sg.right() - 40.0, self.cx))
                self.y = max(sg.top() - 20.0, min(float(gyy), self.y))
                self.game_target, self.game_arrived = (self.cx, self.y), True
                self.game_pos = [round(self.cx - sg.left()), round(gyy - self.y)]
                self.say("Тут постою", 1.6)
                self.save_config()
                return
            self.air = True
            self.peak_y = self.y
            self.pick() if self.mode != "idle" else self.enter("stand")
            vx = vy = 0.0
            now = time.perf_counter()
            sm = [q for q in self.drag_samples if now - q[0] < 0.12]
            if len(sm) >= 2 and now - sm[-1][0] < 0.07 and sm[-1][0] > sm[0][0]:
                dtm = max(sm[-1][0] - sm[0][0], 0.06)       # короткий отрезок = шум, не разгон
                dpr = self.devicePixelRatioF() or 1.0
                vx = (sm[-1][1] - sm[0][1]) / dtm / dpr
                vy = (sm[-1][2] - sm[0][2]) / dtm / dpr
                sp = math.hypot(vx, vy)
                # мёртвая зона: лёгкий толчок просто роняет, сильный бросок летит, но мягче
                eff = max(0.0, sp - 450.0) * 0.55
                eff = min(eff, 1800.0)
                if sp > 0:
                    vx, vy = vx * eff / sp, vy * eff / sp
            self.vx, self.vy = vx, vy
            self.pending = None
            self.thrown = math.hypot(vx, vy) > 120       # бросок: летит по инерции
            self.bounces = 0
            self.tumble = self.rot
            if was_hang:                                   # упал с лапки: падает с кувырком
                self.thrown = True
                if abs(self.vx) < 60:
                    self.vx = 60.0 if self.hang_ang > 0 else -60.0
            if self.thrown:
                self.show_emote("!", 0.8)
            self.drag_samples = []
            self.save_config()
            return
        t = self.t
        self.click_times = [c for c in self.click_times if t - c < 1.6] + [t]
        n = len(self.click_times)
        if self.beh in ("sleep", "yawn"):
            self.enter("stand")
        if n >= 4:                                   # надоело
            self.annoy_until = t + 1.6
            self.say("Хватит!", 1.6)
            self.show_emote("sweat", 1.6)
            self.click_times = []
        elif n == 3:
            self.say("Ха-ха, щекотно!", 1.8)
            self.show_emote("heart", 1.8)
            self.enter("wiggle")
        else:
            if not self.air:
                self.launch(-820, delay=0.07)
            self.happy_until = t + 1.2
            self.say(random.choice(POKE_LINES), 2.0)
            self.show_emote(random.choice(("heart", "spark", "heart")), 1.5)

    def contextMenuEvent(self, e):
        m = QMenu()
        bt = m.addAction(f"Наушники: {self.batt}%" if self.batt is not None else "Наушники: не на связи")
        bt.triggered.connect(self.show_battery)
        m.addAction("Дать печеньку").triggered.connect(self.give_cookie)
        m.addAction("Спать").triggered.connect(lambda: self.enter("yawn") if self.mode == "idle" else None)
        snd = m.addAction("Звук и уведомления")
        snd.setCheckable(True)
        snd.setChecked(self.sound)
        snd.toggled.connect(self.set_sound)
        fg = m.addAction("Режим игры вручную (Ctrl+Alt+G)")
        fg.setCheckable(True)
        fg.setChecked(self.force_game)
        fg.toggled.connect(self.set_force_game)
        gd = m.addAction("Вещи вокруг (гаджеты)")
        gd.setCheckable(True)
        gd.setChecked(self.show_gadgets)
        gd.toggled.connect(self.set_gadgets)
        m.addSeparator()
        m.addAction("Выход").triggered.connect(QApplication.quit)
        m.exec(e.globalPos())

    def give_cookie(self):
        if self.mode == "idle":
            self.enter("eat")


def tray_icon():
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.translate(0, 8)
    p.scale(1.33, 1.33)
    d = base_pose(0)
    draw_sprite(p, d)
    p.end()
    return QIcon(pm)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "clawd-pet.lock"))
    if not lock.tryLock(100):
        return 0
    pet = Clawd()
    tray = QSystemTrayIcon(tray_icon(), app)
    tray.setToolTip("Clawd")
    menu = QMenu()
    menu.addAction("Показать заряд наушников").triggered.connect(pet.show_battery)
    menu.addAction("Дать печеньку").triggered.connect(pet.give_cookie)
    snd = menu.addAction("Звук и уведомления")
    snd.setCheckable(True)
    snd.setChecked(pet.sound)
    snd.toggled.connect(pet.set_sound)
    fg = menu.addAction("Режим игры вручную (Ctrl+Alt+G)")
    fg.setCheckable(True)
    fg.setChecked(pet.force_game)
    fg.toggled.connect(pet.set_force_game)
    pet.force_action = fg
    gd = menu.addAction("Вещи вокруг (гаджеты)")
    gd.setCheckable(True)
    gd.setChecked(pet.show_gadgets)
    gd.toggled.connect(pet.set_gadgets)
    menu.addAction("Выход").triggered.connect(app.quit)
    pet.tray = tray
    tray.setContextMenu(menu)
    tray.show()
    app.aboutToQuit.connect(pet.save_config)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
