"""Add (or update) the 'allplan' stdio server in Claude Desktop config files.

Other servers and settings are kept; a .bak copy is written next to each file.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


SERVER_NAME = "allplan"


def configure(config_path: Path, command: str) -> bool:
    config: object = {}
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8-sig")
        if text.strip():
            try:
                config = json.loads(text)
            except json.JSONDecodeError as error:
                print(f"WARNING: {config_path} is not valid JSON ({error}); left untouched.")
                return False
        shutil.copy2(config_path, config_path.with_name(config_path.name + ".bak"))

    servers = config.get("mcpServers") if isinstance(config, dict) else None
    if not isinstance(config, dict) or not isinstance(servers, (dict, type(None))):
        print(f"WARNING: unexpected structure in {config_path}; left untouched.")
        return False
    if servers is None:
        servers = config["mcpServers"] = {}

    servers[SERVER_NAME] = {"command": command, "args": ["--transport", "stdio"]}

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Claude Desktop config updated: {config_path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", required=True, help="Path of allplan-mcp.exe")
    parser.add_argument("configs", nargs="+", type=Path, help="claude_desktop_config.json paths")
    args = parser.parse_args()

    results = [configure(path, args.command) for path in args.configs]
    return 0 if any(results) else 1


if __name__ == "__main__":
    sys.exit(main())
