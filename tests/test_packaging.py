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


def _credential_command(name: str) -> str:
    env = json.loads(MCP_MANIFEST.read_text())["mcpServers"]["mcp"]["env"]
    command = env[name]
    assert command.startswith("!"), "the harness only shell-evaluates a leading '!'"
    return command[1:]


def _run_credential_command(
    name: str,
    tmp_path: Path,
    *,
    keychain_host: str,
    keychain_api_key: str,
    inherited_host: str,
    inherited_api_key: str,
    failed_host_output: str = "",
    failed_api_key_output: str = "",
    inherited_host_scoped_api_key: str = "",
) -> str:
    """Execute one manifest command with a service-selecting fake Keychain."""
    security = tmp_path / "security"
    security.write_text(
        """#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-s" ]; then
    service=$2
    break
  fi
  shift
done
if [ "$service" = "aleph-mcp" ] && [ -n "$FAKE_KEYCHAIN_HOST" ]; then
  printf %s "$FAKE_KEYCHAIN_HOST"
  exit 0
fi
if [ "$service" = "aleph-mcp" ] && [ -n "$FAKE_FAILED_HOST_OUTPUT" ]; then
  printf %s "$FAKE_FAILED_HOST_OUTPUT"
  printf %s "fake Keychain lookup failed" >&2
  exit 1
fi
if [ "$service" = "aleph-mcp:$FAKE_KEYCHAIN_HOST" ] && [ -n "$FAKE_KEYCHAIN_API_KEY" ]; then
  printf %s "$FAKE_KEYCHAIN_API_KEY"
  exit 0
fi
if [ "$service" = "aleph-mcp:$ALEPHCLIENT_HOST" ] && [ -n "$FAKE_INHERITED_HOST_API_KEY" ]; then
  printf %s "$FAKE_INHERITED_HOST_API_KEY"
  exit 0
fi
if [ "$service" = "aleph-mcp:$FAKE_KEYCHAIN_HOST" ] && [ -n "$FAKE_FAILED_API_KEY_OUTPUT" ]; then
  printf %s "$FAKE_FAILED_API_KEY_OUTPUT"
  printf %s "fake Keychain lookup failed" >&2
  exit 1
fi
printf %s "fake Keychain lookup failed" >&2
exit 1
"""
    )
    security.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", _credential_command(name)],
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "USER": "nobody",
            "ALEPHCLIENT_HOST": inherited_host,
            "ALEPHCLIENT_API_KEY": inherited_api_key,
            "FAKE_KEYCHAIN_HOST": keychain_host,
            "FAKE_KEYCHAIN_API_KEY": keychain_api_key,
            "FAKE_FAILED_HOST_OUTPUT": failed_host_output,
            "FAKE_FAILED_API_KEY_OUTPUT": failed_api_key_output,
            "FAKE_INHERITED_HOST_API_KEY": inherited_host_scoped_api_key,
        },
    )
    assert result.stderr == ""
    return result.stdout


def test_keychain_host_and_key_take_precedence_over_inherited_values(tmp_path: Path) -> None:
    """The key fake answers only under its Keychain-selected host service."""
    keychain_host = "https://keychain.example"
    assert (
        _run_credential_command(
            "ALEPHCLIENT_HOST",
            tmp_path,
            keychain_host=keychain_host,
            keychain_api_key="keychain-api-key",
            inherited_host="https://inherited.example",
            inherited_api_key="inherited-api-key",
        )
        == keychain_host
    )
    assert (
        _run_credential_command(
            "ALEPHCLIENT_API_KEY",
            tmp_path,
            keychain_host=keychain_host,
            keychain_api_key="keychain-api-key",
            inherited_host="https://inherited.example",
            inherited_api_key="inherited-api-key",
        )
        == "keychain-api-key"
    )


def test_keychain_host_with_missing_key_falls_back_to_inherited_key(tmp_path: Path) -> None:
    assert (
        _run_credential_command(
            "ALEPHCLIENT_HOST",
            tmp_path,
            keychain_host="https://keychain.example",
            keychain_api_key="",
            inherited_host="https://inherited.example",
            inherited_api_key="inherited-api-key",
        )
        == "https://keychain.example"
    )
    assert (
        _run_credential_command(
            "ALEPHCLIENT_API_KEY",
            tmp_path,
            keychain_host="https://keychain.example",
            keychain_api_key="",
            inherited_host="https://inherited.example",
            inherited_api_key="inherited-api-key",
            failed_api_key_output="failed-key-output",
        )
        == "inherited-api-key"
    )


def test_missing_keychain_records_fall_back_to_both_inherited_values(tmp_path: Path) -> None:
    assert (
        _run_credential_command(
            "ALEPHCLIENT_HOST",
            tmp_path,
            keychain_host="",
            keychain_api_key="",
            inherited_host="https://inherited.example",
            inherited_api_key="inherited-api-key",
            failed_host_output="failed-host-output",
        )
        == "https://inherited.example"
    )
    assert (
        _run_credential_command(
            "ALEPHCLIENT_API_KEY",
            tmp_path,
            keychain_host="",
            keychain_api_key="",
            inherited_host="https://inherited.example",
            inherited_api_key="inherited-api-key",
            failed_host_output="failed-host-output",
        )
        == "inherited-api-key"
    )


def test_failed_host_lookup_stdout_does_not_select_an_api_key_service(tmp_path: Path) -> None:
    assert (
        _run_credential_command(
            "ALEPHCLIENT_API_KEY",
            tmp_path,
            keychain_host="",
            keychain_api_key="",
            inherited_host="https://inherited.example",
            inherited_api_key="inherited-api-key",
            failed_host_output="failed-host-output",
            inherited_host_scoped_api_key="keychain-key-for-inherited-host",
        )
        == "keychain-key-for-inherited-host"
    )
