"""The version is written in three places, and the install pin and credential lookup in
one — the shipped `.mcp.json`, which no other test exercises.

A 0.1.4 release shipped as 0.1.2 to every marketplace user because the catalog entry
was the copy nobody remembered. These assertions are cheap; the drift is not.
"""

import json
import re
import subprocess
from pathlib import Path

import aleph_mcp
from aleph_mcp.config import KEYCHAIN_MISS

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


def _credential_command() -> str:
    env = json.loads(MCP_MANIFEST.read_text())["mcpServers"]["mcp"]["env"]
    command = env["ALEPHCLIENT_API_KEY"]
    assert command.startswith("!"), "the harness only shell-evaluates a leading '!'"
    return command[1:]


def test_the_credential_lookup_is_scoped_to_the_host() -> None:
    assert "aleph-mcp:$ALEPHCLIENT_HOST" in _credential_command()


def test_a_keychain_miss_yields_the_marker_and_never_the_ambient_key() -> None:
    """The load-bearing property. The harness omits an `env` entry whose command prints
    only whitespace, and an omitted entry means the server inherits ALEPHCLIENT_API_KEY
    from the ambient environment — which is how a substituted host would get handed the
    operator's real credential. So the command must always print something."""
    out = subprocess.run(
        ["bash", "-c", _credential_command()],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "USER": "nobody",
            "ALEPHCLIENT_HOST": "https://not-a-real-host.invalid",
            "ALEPHCLIENT_API_KEY": "the-operators-real-key",
        },
    ).stdout
    assert out == KEYCHAIN_MISS
    assert "the-operators-real-key" not in out
