"""Runtime configuration for goojprt-server.

Values are read from environment variables (``GOOJPRT_*``) with CLI flags
taking precedence (the CLI constructs ``Settings(**overrides)``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GOOJPRT_",
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    ble_address: str = Field(..., description="Bluetooth address of the PT-210")
    host: str = "127.0.0.1"
    port: int = 8080
    log_level: Literal["debug", "info", "warning"] = "info"
    log_json: bool = False
    queue_max_size: int = 100
    reconnect_interval_s: float = 5.0
    reconnect_job_wait_s: float = 60.0
    reconnect_log_interval_s: float = 30.0
    job_ttl_s: int = 3600
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    no_dashboard: bool = False
    log_file: Path | None = None
    no_log_file: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v
