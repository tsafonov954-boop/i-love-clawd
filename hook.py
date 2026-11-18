"""Хук Claude Code: hook.py <working|done|attention|idle|resume>

Пишет состояние в state.json рядом со скриптом (атомарно). Ничего не печатает.
resume = вернуть в "working", только если сейчас "attention" (после подтверждения инструмента).
"""
import json
import os
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HOME, "state.json")


def main():
    state = sys.argv[1] if len(sys.argv) > 1 else "idle"
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass
    if state == "resume":
        try:
            with open(FILE, encoding="utf-8") as f:
                if json.load(f).get("state") != "attention":
                    return
        except Exception:
            return
        state = "working"
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"state": state, "ts": time.time()}, f)
    os.replace(tmp, FILE)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
