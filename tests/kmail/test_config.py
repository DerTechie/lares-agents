# SPDX-License-Identifier: MIT
from pathlib import Path

import pytest
from pydantic import ValidationError

from lares.kmail.config import LaresConfig, load_config

_FULL = """
[lares]
log_level = "DEBUG"

[lares.ollama]
endpoint    = "http://127.0.0.1:11434"
model       = "qwen3:4b-instruct-2507-q4_K_M"
timeout_s   = 30
temperature = 0.0

[kmail]
enabled              = true
state_db_path        = "~/.local/state/lares/kmail.db"
body_truncate_bytes  = 8192
classify_timeout_s   = 30
max_retries          = 10
catchup_limit        = 200
min_confidence       = 0.5
helper_binary_path   = ""

[kmail.tags]
personal     = "A human writing to me."
business     = "Business inquiry."
newsletter   = "Marketing or digest."
notification = "Transactional notice."

[kmail.watch]
extra_collection_names = []
"""


def test_load_valid_config(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(_FULL)
    cfg = load_config(cfg_file)
    assert isinstance(cfg, LaresConfig)
    assert cfg.lares.ollama.model == "qwen3:4b-instruct-2507-q4_K_M"
    assert cfg.kmail.min_confidence == 0.5
    assert set(cfg.kmail.tags) == {"personal", "business", "newsletter", "notification"}


def test_defaults_apply_when_kmail_section_minimal(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[lares.ollama]
model = "qwen3:4b-instruct-2507-q4_K_M"

[kmail.tags]
personal = "h"
business = "b"
newsletter = "n"
notification = "t"
"""
    )
    cfg = load_config(cfg_file)
    assert cfg.kmail.body_truncate_bytes == 8192
    assert cfg.kmail.max_retries == 10
    assert cfg.lares.ollama.endpoint == "http://127.0.0.1:11434"


def test_state_db_path_user_home_expanded(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[lares.ollama]
model = "x"

[kmail.tags]
personal = "h"
business = "b"
newsletter = "n"
notification = "t"
"""
    )
    cfg = load_config(cfg_file)
    assert not str(cfg.kmail.state_db_path).startswith("~")
    assert cfg.kmail.state_db_path.is_absolute()


def test_min_confidence_must_be_in_range(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[lares.ollama]
model = "x"

[kmail]
min_confidence = 1.5

[kmail.tags]
personal = "h"
business = "b"
newsletter = "n"
notification = "t"
"""
    )
    with pytest.raises(ValidationError):
        load_config(cfg_file)


def test_tags_must_be_non_empty(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[lares.ollama]
model = "x"

[kmail.tags]
"""
    )
    with pytest.raises(ValidationError):
        load_config(cfg_file)


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_model_must_be_set(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[kmail.tags]
personal = "h"
business = "b"
newsletter = "n"
notification = "t"
"""
    )
    with pytest.raises(ValidationError):
        load_config(cfg_file)
