#!/usr/bin/env bash
# Holographic memory — manual installer for Claude Code
# Copies plugin files to ~/.claude/holographic-memory/ and wires hooks into settings.json
#
# Alternative: add to ~/.claude/settings.json extraKnownMarketplaces and install via Claude Code:
#   "extraKnownMarketplaces": {
#     "holographic-memory": { "source": { "source": "git", "url": "https://github.com/jessebrizzi/claude-holographic.git" } }
#   }

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$REPO_DIR/plugins/holographic-memory"
PLUGIN_DIR="$HOME/.claude/holographic-memory"
SETTINGS="$HOME/.claude/settings.json"

echo "Installing holographic memory to $PLUGIN_DIR ..."

mkdir -p "$PLUGIN_DIR/hooks" "$PLUGIN_DIR/watermarks"

for f in holographic.py store.py retrieval.py holo.py; do
    cp "$PLUGIN_SRC/$f" "$PLUGIN_DIR/$f"
    echo "  copied: $f"
done

for f in hooks/startup.sh hooks/inject.sh hooks/collect.sh; do
    cp "$PLUGIN_SRC/$f" "$PLUGIN_DIR/$f"
    chmod +x "$PLUGIN_DIR/$f"
    echo "  copied: $f"
done

python3 - <<PYEOF
import json
from pathlib import Path

settings_path = Path("$SETTINGS")
plugin_dir = "$PLUGIN_DIR"

settings = {}
if settings_path.exists():
    try:
        settings = json.loads(settings_path.read_text())
    except Exception:
        settings = {}

if "hooks" not in settings:
    settings["hooks"] = {}

def _already_wired(event):
    for entry in settings["hooks"].get(event, []):
        if isinstance(entry, dict):
            for h in entry.get("hooks", []):
                if "holographic-memory" in h.get("command", ""):
                    return True
    return False

def _add_hook(event, command, timeout=10):
    if _already_wired(event):
        print(f"  {event}: already wired")
        return
    settings["hooks"].setdefault(event, []).append({
        "hooks": [{"type": "command", "command": command, "timeout": timeout}]
    })
    print(f"  {event}: wired")

_add_hook("SessionStart",     f'bash "{plugin_dir}/hooks/startup.sh"', timeout=10)
_add_hook("UserPromptSubmit", f'bash "{plugin_dir}/hooks/inject.sh"',  timeout=5)
_add_hook("Stop",             f'bash "{plugin_dir}/hooks/collect.sh"', timeout=15)

settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print("  settings.json updated")
PYEOF

echo ""
echo "Testing..."
uv run "$PLUGIN_DIR/holo.py" startup
echo ""
echo "Done. Restart Claude Code to activate."
