"""
Register memsearch-win as a Claude Code plugin.

Run this once after cloning the repo:
    py register_plugin.py
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

NOW = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
PLUGIN_KEY = "memsearch-win@memsearch-plugins"
MARKETPLACE = "jv209/memsearch-win"
VERSION = "0.4.0"

CACHE_DIR = Path.home() / ".claude/plugins/cache/memsearch-plugins/memsearch-win" / VERSION
PLUGIN_SRC = Path(__file__).parent / "plugins/claude-code"

# --- Copy plugin files to cache ---
if CACHE_DIR.exists():
    shutil.rmtree(CACHE_DIR)
CACHE_DIR.mkdir(parents=True)
shutil.copytree(PLUGIN_SRC, CACHE_DIR, dirs_exist_ok=True)
print(f"Plugin copied to: {CACHE_DIR}")

# --- Update installed_plugins.json ---
installed_path = Path.home() / ".claude/plugins/installed_plugins.json"
with open(installed_path) as f:
    installed = json.load(f)

installed["plugins"][PLUGIN_KEY] = [
    {
        "scope": "user",
        "installPath": str(CACHE_DIR),
        "version": VERSION,
        "installedAt": NOW,
        "lastUpdated": NOW,
        "gitCommitSha": "local",
    }
]

with open(installed_path, "w") as f:
    json.dump(installed, f, indent=2)
print(f"installed_plugins.json: registered {PLUGIN_KEY}")

# --- Update settings.json ---
settings_path = Path.home() / ".claude/settings.json"
with open(settings_path) as f:
    settings = json.load(f)

settings.setdefault("enabledPlugins", {})[PLUGIN_KEY] = True
settings.setdefault("extraKnownMarketplaces", {})["memsearch-plugins"] = {
    "source": {"source": "github", "repo": MARKETPLACE}
}

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
print(f"settings.json: enabled {PLUGIN_KEY}")

print("\nDone. Run /reload-plugins in Claude Code to activate.")
