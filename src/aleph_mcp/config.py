from __future__ import annotations

import os
import subprocess
from typing import Any

import httpx
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Older plugin manifests emitted this marker when their Keychain lookup failed. Keep
# refusing it so a stale launcher cannot turn it into a real credential.
KEYCHAIN_MISS = "aleph-mcp:keychain-miss"


def _read_keychain_value(service: str) -> str:
    """Return a non-empty login-Keychain value, or an empty string on an unavailable lookup."""
    account = os.environ.get("USER")
    if not account:
        return ""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


class _CredentialSource(PydanticBaseSettingsSource):
    """Select one complete credential pair without mixing sources."""

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        environment: PydanticBaseSettingsSource,
        dotenv: PydanticBaseSettingsSource,
    ) -> None:
        super().__init__(settings_cls)
        self._environment = environment
        self._dotenv = dotenv

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        environment = self._environment()
        dotenv = self._dotenv()
        values = {**dotenv, **environment}
        values.pop("ALEPHCLIENT_HOST", None)
        values.pop("ALEPHCLIENT_API_KEY", None)

        for source in (environment, dotenv):
            if "ALEPHCLIENT_HOST" in source and "ALEPHCLIENT_API_KEY" in source:
                values.update(
                    ALEPHCLIENT_HOST=source["ALEPHCLIENT_HOST"],
                    ALEPHCLIENT_API_KEY=source["ALEPHCLIENT_API_KEY"],
                )
                return values

        host = _read_keychain_value("aleph-mcp-host")
        api_key = _read_keychain_value("aleph-mcp-api-key")
        if host and api_key:
            values.update(ALEPHCLIENT_HOST=host, ALEPHCLIENT_API_KEY=api_key)
        return values


class Settings(BaseSettings):
    """Runtime configuration, read from the environment at process start.

    `host` and `api_key` deliberately reuse the `ALEPHCLIENT_*` names that upstream
    `alephclient` and the sibling `aleph-coldbackup` tool already read, so one
    exported key serves every Aleph tool on the machine.
    """

    model_config = SettingsConfigDict(
        env_prefix="ALEPH_MCP_",
        case_sensitive=False,
        extra="ignore",
        env_file=".env",
        # Keep the assembled settings dict — which holds the API key — out of the
        # string form of any validation error.
        hide_input_in_errors=True,
    )

    host: str = Field(
        ...,
        validation_alias=AliasChoices("ALEPHCLIENT_HOST", "ALEPH_HOST", "ALEPH_MCP_HOST"),
        description="Base URL of the Aleph instance, e.g. https://aleph.occrp.org",
    )
    api_key: SecretStr = Field(
        ...,
        validation_alias=AliasChoices("ALEPHCLIENT_API_KEY", "ALEPH_API_KEY", "ALEPH_MCP_API_KEY"),
        description="Aleph API key. Use a role with READ-only collection access.",
    )
    timeout_secs: float = Field(
        60,
        ge=1,
        description=(
            "Per-request HTTP timeout, and the total budget one call may spend retrying. "
            "Connecting is capped separately at MAX_CONNECT_SECS."
        ),
    )
    max_retries: int = Field(
        4,
        ge=1,
        le=10,
        description=(
            "Attempts per request on 429/5xx responses (honouring Retry-After) and on a "
            "connection failure. The backoff between them is drawn from timeout_secs."
        ),
    )
    verify_tls: bool = Field(True, description="Verify TLS certs (set false for self-signed).")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _CredentialSource(settings_cls, env_settings, dotenv_settings),
            file_secret_settings,
        )

    @field_validator("host")
    @classmethod
    def _normalise_host(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("host must start with http:// or https://")
        # httpx keeps userinfo on every request.url and renders it unmasked in str(), so a
        # password embedded here would surface in any message that names the target.
        if httpx.URL(v).userinfo:
            raise ValueError(
                "host must not carry userinfo (user:password@). Put the credential in "
                "ALEPHCLIENT_API_KEY, or in the Keychain entry the plugin reads."
            )
        # Tolerate someone exporting the API base rather than the site root.
        for suffix in ("/api/2", "/api"):
            if v.endswith(suffix):
                v = v[: -len(suffix)]
        return v.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def _require_a_key(cls, v: SecretStr) -> SecretStr:
        # An empty configured value must fail at startup rather than become a 401 on the
        # first tool call.
        if not v.get_secret_value().strip():
            raise ValueError(
                "api_key is empty. Set both ALEPHCLIENT_HOST and ALEPHCLIENT_API_KEY, "
                "or store both Keychain entries: "
                '`security add-generic-password -s "aleph-mcp-host" -a "$USER" '
                '-w "<host>" -U` and `security add-generic-password -s '
                '"aleph-mcp-api-key" -a "$USER" -w "<api-key>" -U`.'
            )
        return v

    @model_validator(mode="after")
    def _refuse_a_credential_not_minted_for_this_host(self) -> Settings:
        if self.api_key.get_secret_value() == KEYCHAIN_MISS:
            raise ValueError(
                f"no Keychain entry for {self.host}. The plugin binds the key to the host "
                "it was issued for, so a host taken from the ambient environment cannot "
                "borrow a credential minted for a different instance. Store it with "
                f'`security add-generic-password -s "aleph-mcp:{self.host}" -a "$USER" '
                "-w '<api-key>' -U`, and if the host is not the one you expected, check "
                "for a .env in the current directory."
            )
        return self
