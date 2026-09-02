from __future__ import annotations

import httpx
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# What the shipped plugin manifest emits when the login Keychain holds no entry for the
# host it was told to talk to. It is a literal rather than an empty string on purpose: the
# harness drops an `env` entry whose command prints nothing, which would let the child
# inherit an ambient ALEPHCLIENT_API_KEY and attach the operator's real credential to a
# host that some `.env` in the working directory chose. Failing closed is the whole point.
KEYCHAIN_MISS = "aleph-mcp:keychain-miss"


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
        # An empty string is what a failed Keychain lookup yields, and pydantic would
        # accept it as a present str. Refusing here turns a silent 401 on the first tool
        # call into a startup error that names the cause.
        if not v.get_secret_value().strip():
            raise ValueError(
                "api_key is empty. If the plugin reads it from the macOS Keychain, the "
                "entry is keyed on the host: store it with "
                '`security add-generic-password -s "aleph-mcp:$ALEPHCLIENT_HOST" '
                "-a \"$USER\" -w '<api-key>' -U`."
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
