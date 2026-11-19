"""Runtime data location, hook entry point, Claude Code hook installer and autostart (no Qt here)."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "Clawd"
DATA.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA / "state.json"      # hooks write here
CONFIG_FILE = DATA / "config.json"
STATUS_FILE = DATA / "status.json"

FROZEN = bool(getattr(sys, "frozen", False))
SCRIPT = Path(sys.executable if FROZEN else __file__).resolve()
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
EVENTS = {"UserPromptSubmit": "working", "PostToolUse": "resume", "Stop": "done", "Notification": "attention"}
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def write_state(state):
    if state == "resume":
        try:
            if json.loads(STATE_FILE.read_text(encoding="utf-8")).get("state") != "attention":
                return
        except Exception:
            return
        state = "working"
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"state": state, "ts": time.time()}), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def hook_cli(state):
    """Called by Claude Code hooks: `Clawd.exe --hook done`. Never fails, prints nothing."""
    try:
        if sys.stdin is not None and not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass
    try:
        write_state(state)
    except Exception:
        pass


def _quote(p):
    return '"' + str(p).replace("\\", "/") + '"'


def launch_command():
    """Command line that starts the app (no console window)."""
    if FROZEN:
        return _quote(SCRIPT)
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return f"{_quote(pyw if pyw.exists() else py)} {_quote(SCRIPT)}"


def _load_settings():
    try:
        return json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        raise


def _is_ours(entry):
    return any("--hook" in h.get("command", "") or "clawd" in h.get("command", "").lower()
               for h in entry.get("hooks", []))


def hooks_installed():
    try:
        hooks = _load_settings().get("hooks", {})
        return all(any(_is_ours(e) for e in hooks.get(ev, [])) for ev in EVENTS)
    except Exception:
        return False


def install_hooks():
    """Add Clawd's hooks to ~/.claude/settings.json (other hooks are kept, a backup is made)."""
    s = _load_settings()
    if CLAUDE_SETTINGS.exists():
        shutil.copy(CLAUDE_SETTINGS, CLAUDE_SETTINGS.with_name("settings.json.clawd-backup"))
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    hooks = s.setdefault("hooks", {})
    for ev, st in EVENTS.items():
        lst = [e for e in hooks.get(ev, []) if not _is_ours(e)]
        lst.append({"hooks": [{"type": "command", "command": f"{launch_command()} --hook {st}"}]})
        hooks[ev] = lst
    CLAUDE_SETTINGS.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


def remove_hooks():
    s = _load_settings()
    hooks = s.get("hooks", {})
    for ev in EVENTS:
        lst = [e for e in hooks.get(ev, []) if not _is_ours(e)]
        if lst:
            hooks[ev] = lst
        else:
            hooks.pop(ev, None)
    if not hooks:
        s.pop("hooks", None)
    CLAUDE_SETTINGS.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Clawd")
        return True
    except Exception:
        return False


def set_autostart(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "Clawd", 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, "Clawd")
            except FileNotFoundError:
                pass
