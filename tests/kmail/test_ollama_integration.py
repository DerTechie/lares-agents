# SPDX-License-Identifier: MIT
"""Integration tests for the classifier against a real local Ollama.

Run manually with:

    OLLAMA_TEST_MODEL=qwen3:1.7b-instruct-2507 \
    pytest -m integration tests/kmail/test_ollama_integration.py
"""

from __future__ import annotations

import email
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from lares.kmail.classifier import Classifier, FetchedItem
from lares.kmail.config import KMailConfig, LaresConfig, LaresShared, OllamaConfig

if TYPE_CHECKING:
    from email.message import Message


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif("OLLAMA_TEST_MODEL" not in os.environ, reason="OLLAMA_TEST_MODEL unset"),
]


_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> Message:
    return email.message_from_bytes((_FIXTURES_DIR / name).read_bytes())


def _to_fetched(msg: Message, item_id: int = 1) -> FetchedItem:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                # get_payload(decode=True) returns bytes|None; typeshed types
                # the legacy Message API too broadly, so cast is required.
                raw = cast("bytes | None", part.get_payload(decode=True))
                body = raw.decode("utf-8", errors="replace") if raw else ""
                break
    else:
        # same narrowing needed for the non-multipart path
        raw = cast("bytes | None", msg.get_payload(decode=True))
        body = raw.decode("utf-8", errors="replace") if raw else ""
    return FetchedItem(
        item_id=item_id,
        headers={
            "From": msg.get("From", ""),
            "To": msg.get("To", ""),
            "Subject": msg.get("Subject", ""),
            "List-Id": msg.get("List-Id", ""),
            "Date": msg.get("Date", ""),
        },
        body_text=body,
    )


def _cfg() -> LaresConfig:
    return LaresConfig(
        lares=LaresShared(
            log_level="INFO",
            ollama=OllamaConfig(model=os.environ["OLLAMA_TEST_MODEL"]),
        ),
        kmail=KMailConfig(
            tags={
                "personal": "A real human writing to me directly.",
                "business": "Business inquiry / contract / invoice.",
                "newsletter": "Marketing email or digest.",
                "notification": "Transactional / automated mail.",
            },
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fixture", "expected_category"),
    [
        ("personal.eml", "personal"),
        ("business.eml", "business"),
        ("newsletter.eml", "newsletter"),
        ("notification.eml", "notification"),
    ],
)
async def test_classifier_assigns_expected_category(
    fixture: str,
    expected_category: str,
) -> None:
    cfg = _cfg()
    async with Classifier(cfg) as c:
        verdict = await c.classify(_to_fetched(_load(fixture)))
    assert verdict.raw_category == expected_category, (
        f"expected {expected_category} for {fixture}, got "
        f"{verdict.raw_category} ({verdict.confidence:.2f})"
    )
    assert verdict.confidence >= 0.5
