"""Claude Code hook (script form): python hook.py <working|done|attention|idle|resume>.
Prefer `Clawd --hook <state>` (what the tray's "Connect to Claude Code" installs); this wrapper does the same."""
import sys

import paths

if __name__ == "__main__":
    paths.hook_cli(sys.argv[1] if len(sys.argv) > 1 else "idle")
