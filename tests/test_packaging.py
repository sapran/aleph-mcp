"""Packaging invariants for the shipped plugin manifest.

A 0.1.4 release shipped as 0.1.2 to every marketplace user because the catalog entry
was the copy nobody remembered. These assertions are cheap; the drift is not.
"""

import json
import re
import subprocess
from pathlib import Path

import aleph_mcp

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
CLAUDE_ROOT = ROOT / "plugins" / "aleph"
PLUGIN = CLAUDE_ROOT / ".claude-plugin" / "plugin.json"
MCP_MANIFEST = CLAUDE_ROOT / ".mcp.json"
NATIVE_ROOT = ROOT / "plugins" / "aleph-omp"
NATIVE_PACKAGE = NATIVE_ROOT / "package.json"
NATIVE_MCP_MANIFEST = NATIVE_ROOT / ".mcp.json"
SKILL_PATH = Path("skills/aleph-mcp-entity-graph")
EXPECTED_NATIVE_FILES = {
    ".mcp.json",
    "LICENSE",
    "README.md",
    "package.json",
    "skills/aleph-mcp-entity-graph/SKILL.md",
    "skills/aleph-mcp-entity-graph/references/profiles.md",
}


def test_every_declared_version_agrees_with_the_package() -> None:
    catalog = json.loads(MARKETPLACE.read_text())
    entry = next(p for p in catalog["plugins"] if p["name"] == "aleph")
    plugin = json.loads(PLUGIN.read_text())
    native = json.loads(NATIVE_PACKAGE.read_text())
    documented = tuple(
        re.search(
            r"omp plugin install @sapran/aleph-mcp-plugin@(\d+\.\d+\.\d+)",
            path.read_text(),
        ).group(1)
        for path in (README, NATIVE_ROOT / "README.md")
    )
    assert (entry["version"], plugin["version"], native["version"], *documented) == (
        aleph_mcp.__version__,
    ) * 5


def test_native_omp_package_manifest_is_safe() -> None:
    package = json.loads(NATIVE_PACKAGE.read_text())

    assert package["name"] == "@sapran/aleph-mcp-plugin"
    assert package["omp"] == {}
    assert package["publishConfig"] == {"access": "public"}
    assert not package.get("scripts")


def test_native_omp_package_contains_only_runtime_assets() -> None:
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json", "--ignore-scripts"],
        cwd=NATIVE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    paths = {entry["path"] for entry in payload[0]["files"]}

    assert paths == EXPECTED_NATIVE_FILES


def test_native_and_claude_bundles_share_one_runtime_contract() -> None:
    claude_manifest = json.loads(MCP_MANIFEST.read_text())
    native_manifest = json.loads(NATIVE_MCP_MANIFEST.read_text())

    assert set(native_manifest["mcpServers"]) == {"aleph:mcp"}
    assert native_manifest["mcpServers"]["aleph:mcp"] == claude_manifest["mcpServers"]["mcp"]

    claude_skill = CLAUDE_ROOT / SKILL_PATH
    native_skill = NATIVE_ROOT / SKILL_PATH
    claude_files = {
        path.relative_to(claude_skill): path.read_bytes()
        for path in claude_skill.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }
    native_files = {
        path.relative_to(native_skill): path.read_bytes()
        for path in native_skill.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }
    assert native_files == claude_files


def test_the_plugin_installs_from_an_immutable_commit() -> None:
    """Both manifests must build from a full commit SHA, never a movable branch or tag."""
    for manifest, key in ((MCP_MANIFEST, "mcp"), (NATIVE_MCP_MANIFEST, "aleph:mcp")):
        args = json.loads(manifest.read_text())["mcpServers"][key]["args"]
        spec = args[args.index("--from") + 1]
        assert re.fullmatch(r"git\+https://github\.com/sapran/aleph-mcp\.git@[0-9a-f]{40}", spec), (
            spec
        )


def test_the_manifest_does_not_override_runtime_credential_sources() -> None:
    """Settings owns environment, project dotenv, and Keychain precedence."""
    for manifest, key in ((MCP_MANIFEST, "mcp"), (NATIVE_MCP_MANIFEST, "aleph:mcp")):
        server = json.loads(manifest.read_text())["mcpServers"][key]
        assert "env" not in server
        assert "ALEPHCLIENT_" not in manifest.read_text()
