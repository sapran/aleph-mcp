from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    )

    host: str = Field(
        ...,
        validation_alias=AliasChoices("ALEPHCLIENT_HOST", "ALEPH_HOST", "ALEPH_MCP_HOST"),
        description="Base URL of the Aleph instance, e.g. https://aleph.occrp.org",
    )
    api_key: str = Field(
        ...,
        validation_alias=AliasChoices("ALEPHCLIENT_API_KEY", "ALEPH_API_KEY", "ALEPH_MCP_API_KEY"),
        description="Aleph API key. Use a role with READ-only collection access.",
    )
    timeout_secs: float = Field(60, ge=1, description="Per-request HTTP timeout.")
    max_retries: int = Field(
        4, ge=1, le=10, description="Attempts per request for 429/5xx responses."
    )
    verify_tls: bool = Field(True, description="Verify TLS certs (set false for self-signed).")

    @field_validator("host")
    @classmethod
    def _normalise_host(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("host must start with http:// or https://")
        # Tolerate someone exporting the API base rather than the site root.
        for suffix in ("/api/2", "/api"):
            if v.endswith(suffix):
                v = v[: -len(suffix)]
        return v.rstrip("/")
