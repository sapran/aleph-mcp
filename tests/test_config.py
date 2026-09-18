import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

import aleph_mcp.config as config
from aleph_mcp.config import KEYCHAIN_MISS, Settings


def _clear_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "ALEPHCLIENT_HOST",
        "ALEPHCLIENT_API_KEY",
        "ALEPH_HOST",
        "ALEPH_API_KEY",
        "ALEPH_MCP_HOST",
        "ALEPH_MCP_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def _set_keychain_values(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    monkeypatch.setattr(config, "_read_keychain_value", lambda service: values.get(service, ""))


def test_failed_keychain_lookup_does_not_use_its_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedLookup:
        returncode = 1
        stdout = "failed-lookup-output"

    captured: list[str] = []

    def run(command: list[str], **_: object) -> FailedLookup:
        captured.extend(command)
        return FailedLookup()

    monkeypatch.setenv("USER", "test-account")
    monkeypatch.setattr(config.subprocess, "run", run)
    assert config._read_keychain_value("aleph-mcp-host") == ""
    assert captured == [
        "security",
        "find-generic-password",
        "-s",
        "aleph-mcp-host",
        "-a",
        "test-account",
        "-w",
    ]


def test_required_fields_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _set_keychain_values(monkeypatch, {})
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_environment_credentials_win_over_dotenv_and_keychain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ALEPHCLIENT_HOST=https://dotenv.test\nALEPHCLIENT_API_KEY=dotenv-key\n"
    )
    monkeypatch.setenv("ALEPHCLIENT_HOST", "https://environment.test")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", "environment-key")
    _set_keychain_values(
        monkeypatch,
        {"aleph-mcp-host": "https://keychain.test", "aleph-mcp-api-key": "keychain-key"},
    )
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.host, settings.api_key.get_secret_value()) == (
        "https://environment.test",
        "environment-key",
    )


def test_project_dotenv_credentials_win_over_keychain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ALEPHCLIENT_HOST=https://dotenv.test\nALEPHCLIENT_API_KEY=dotenv-key\n"
    )
    _set_keychain_values(
        monkeypatch,
        {"aleph-mcp-host": "https://keychain.test", "aleph-mcp-api-key": "keychain-key"},
    )
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.host, settings.api_key.get_secret_value()) == (
        "https://dotenv.test",
        "dotenv-key",
    )


def test_keychain_credentials_are_used_when_other_sources_are_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _set_keychain_values(
        monkeypatch,
        {"aleph-mcp-host": "https://keychain.test", "aleph-mcp-api-key": "keychain-key"},
    )
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.host, settings.api_key.get_secret_value()) == (
        "https://keychain.test",
        "keychain-key",
    )


def test_incomplete_environment_does_not_mix_with_lower_priority_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ALEPHCLIENT_HOST=https://dotenv.test\nALEPHCLIENT_API_KEY=dotenv-key\n"
    )
    monkeypatch.setenv("ALEPHCLIENT_HOST", "https://environment.test")
    _set_keychain_values(
        monkeypatch,
        {"aleph-mcp-host": "https://keychain.test", "aleph-mcp-api-key": "keychain-key"},
    )
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.host, settings.api_key.get_secret_value()) == (
        "https://dotenv.test",
        "dotenv-key",
    )


def test_host_trailing_slash_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALEPHCLIENT_HOST", "https://aleph.test/")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", "k")
    assert Settings().host == "https://aleph.test"  # type: ignore[call-arg]


@pytest.mark.parametrize("suffix", ["/api/2", "/api/2/", "/api"])
def test_host_api_suffix_stripped(monkeypatch: pytest.MonkeyPatch, suffix: str) -> None:
    monkeypatch.setenv("ALEPHCLIENT_HOST", f"https://aleph.test{suffix}")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", "k")
    assert Settings().host == "https://aleph.test"  # type: ignore[call-arg]


def test_host_without_scheme_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALEPHCLIENT_HOST", "aleph.test")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", "k")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("host_var", "api_key_var"),
    [("ALEPH_HOST", "ALEPH_API_KEY"), ("ALEPH_MCP_HOST", "ALEPH_MCP_API_KEY")],
)
def test_supported_environment_aliases_beat_keychain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, host_var: str, api_key_var: str
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(host_var, "https://other.test")
    monkeypatch.setenv(api_key_var, "k2")
    _set_keychain_values(
        monkeypatch,
        {"aleph-mcp-host": "https://keychain.test", "aleph-mcp-api-key": "keychain-key"},
    )
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.host, settings.api_key.get_secret_value()) == ("https://other.test", "k2")


def test_host_with_userinfo_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALEPHCLIENT_HOST", "https://svc:hunter2@aleph.test")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", "k")
    with pytest.raises(ValidationError, match="must not carry userinfo"):
        Settings()  # type: ignore[call-arg]


def test_the_legacy_keychain_miss_marker_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALEPHCLIENT_HOST", "https://evil.example")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", KEYCHAIN_MISS)
    with pytest.raises(ValidationError, match=r"no Keychain entry for https://evil\.example"):
        Settings()  # type: ignore[call-arg]


def test_legacy_marker_is_not_disclosed_by_the_cli(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "aleph_mcp"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "ALEPHCLIENT_HOST": "https://aleph.test",
            "ALEPHCLIENT_API_KEY": KEYCHAIN_MISS,
        },
        check=False,
    )
    assert result.returncode == 2
    assert KEYCHAIN_MISS not in result.stderr
    assert "aleph-mcp: configuration error:" in result.stderr


@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "whitespace"])
def test_a_blank_key_is_refused_at_startup(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ALEPHCLIENT_HOST", "https://aleph.test")
    monkeypatch.setenv("ALEPHCLIENT_API_KEY", value)
    with pytest.raises(ValidationError, match="api_key is empty"):
        Settings()  # type: ignore[call-arg]
