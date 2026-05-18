# SPDX-License-Identifier: MIT
"""Configuration loader for Lares agents.

Single source of truth: `~/.config/lares/config.toml`. Validated at startup
with pydantic v2; missing required keys hard-fail with the file path
embedded in the error message.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OllamaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: str = "http://127.0.0.1:11434"
    model: str
    timeout_s: Annotated[int, Field(ge=1, le=600)] = 30
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.0


class LaresShared(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    log_level: str = "INFO"
    ollama: OllamaConfig

    @field_validator("log_level")
    @classmethod
    def _log_level_known(cls, v: str) -> str:
        if v.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unknown log_level: {v!r}")
        return v.upper()


class KMailWatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    extra_collection_names: list[str] = Field(default_factory=list)


class KMailConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    state_db_path: Path = Path("~/.local/state/lares/kmail.db")
    body_truncate_bytes: Annotated[int, Field(ge=128, le=1_048_576)] = 8192
    classify_timeout_s: Annotated[int, Field(ge=1, le=600)] = 30
    max_retries: Annotated[int, Field(ge=0, le=1000)] = 10
    catchup_limit: Annotated[int, Field(ge=0, le=100_000)] = 200
    min_confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    helper_binary_path: str = ""
    tags: dict[str, str]
    watch: KMailWatch = Field(default_factory=KMailWatch)

    @field_validator("tags")
    @classmethod
    def _at_least_one_tag(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError("kmail.tags must define at least one tag")
        for name, desc in v.items():
            if not name or not desc:
                raise ValueError(f"kmail.tags entry must be non-empty: {name!r}={desc!r}")
        return v

    @model_validator(mode="after")
    def _expand_state_db_path(self) -> KMailConfig:
        # expanduser().resolve() must run even when the default value is used,
        # which field_validator(mode="after") does not guarantee for defaults.
        object.__setattr__(self, "state_db_path", self.state_db_path.expanduser().resolve())
        return self


class LaresConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lares: LaresShared
    kmail: KMailConfig


def load_config(path: Path) -> LaresConfig:
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    # Promote bare `[lares.ollama]` (without [lares]) into a synthesised [lares] block.
    if "lares" not in data:
        data["lares"] = {}
    if "ollama" not in data["lares"] and "lares.ollama" in data:
        # tomllib already nests dotted-table keys, this branch is paranoia only.
        data["lares"]["ollama"] = data.pop("lares.ollama")
    return LaresConfig.model_validate(data)
