"""The version is written in three places and the install pin in one.

A 0.1.4 release shipped as 0.1.2 to every marketplace user because the catalog entry
was the copy nobody remembered. These assertions are cheap; the drift is not.
"""

import json
import re
from pathlib import Path

import aleph_mcp

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN = ROOT / "plugins" / "aleph" / ".claude-plugin" / "plugin.json"
MCP_MANIFEST = ROOT / "plugins" / "aleph" / ".mcp.json"


def test_every_declared_version_agrees_with_the_package() -> None:
    catalog = json.loads(MARKETPLACE.read_text())
    entry = next(p for p in catalog["plugins"] if p["name"] == "aleph")
    plugin = json.loads(PLUGIN.read_text())
    assert (entry["version"], plugin["version"]) == (aleph_mcp.__version__, aleph_mcp.__version__)


def test_the_plugin_installs_from_an_immutable_commit() -> None:
    """The manifest hands the server the operator's Aleph key, so the ref it builds from
    must be a full commit SHA — not a branch, and not a movable tag."""
    args = json.loads(MCP_MANIFEST.read_text())["mcpServers"]["mcp"]["args"]
    spec = args[args.index("--from") + 1]
    assert re.fullmatch(r"git\+https://github\.com/sapran/aleph-mcp\.git@[0-9a-f]{40}", spec), spec
