# SPDX-License-Identifier: MIT
from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING

import pytest

from lares.kmail.classifier import Classifier, ClassifierError, FetchedItem
from lares.kmail.config import KMailConfig, LaresConfig, LaresShared, OllamaConfig
from lares.kmail.tags import LARES_UNCLASSIFIED

if TYPE_CHECKING:
    from pytest_httpx import HTTPXMock


def _cfg(min_confidence: float = 0.5) -> LaresConfig:
    return LaresConfig(
        lares=LaresShared(
            log_level="INFO",
            ollama=OllamaConfig(model="qwen3:4b-instruct-2507-q4_K_M"),
        ),
        kmail=KMailConfig(
            tags={
                "personal": "A human writing.",
                "business": "Business inquiry.",
                "newsletter": "Marketing/digest.",
                "notification": "Transactional.",
            },
            min_confidence=min_confidence,
        ),
    )


def _item() -> FetchedItem:
    return FetchedItem(
        item_id=1,
        headers={
            "From": "alice@example.com",
            "To": "me@example.com",
            "Subject": "Lunch on Friday?",
            "List-Id": "",
            "Date": "Tue, 18 May 2026 09:00:00 +0200",
        },
        body_text="Hey, are you free for lunch on Friday?",
    )


@pytest.mark.asyncio
async def test_classify_high_confidence_returns_prefixed_tag(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": '{"category":"personal","confidence":0.93}'},
    )
    async with Classifier(_cfg()) as c:
        verdict = await c.classify(_item())
    assert verdict.tag == "lares-personal"
    assert abs(verdict.confidence - 0.93) < 1e-9
    assert verdict.raw_category == "personal"


@pytest.mark.asyncio
async def test_classify_low_confidence_returns_unclassified(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": '{"category":"newsletter","confidence":0.31}'},
    )
    async with Classifier(_cfg(min_confidence=0.5)) as c:
        verdict = await c.classify(_item())
    assert verdict.tag == LARES_UNCLASSIFIED
    assert abs(verdict.confidence - 0.31) < 1e-9
    assert verdict.raw_category == "newsletter"


@pytest.mark.asyncio
async def test_classify_unknown_category_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": '{"category":"sports","confidence":0.9}'},
    )
    async with Classifier(_cfg()) as c:
        with pytest.raises(ClassifierError):
            await c.classify(_item())


@pytest.mark.asyncio
async def test_classify_malformed_json_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": "not json at all"},
    )
    async with Classifier(_cfg()) as c:
        with pytest.raises(ClassifierError):
            await c.classify(_item())


@pytest.mark.asyncio
async def test_classify_request_payload_uses_json_schema(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": '{"category":"personal","confidence":0.9}'},
    )
    async with Classifier(_cfg()) as c:
        await c.classify(_item())
    req = httpx_mock.get_request()
    assert req is not None
    body = req.read()
    payload = _json.loads(body)
    assert payload["model"] == "qwen3:4b-instruct-2507-q4_K_M"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.0
    fmt = payload["format"]
    assert fmt["type"] == "object"
    assert set(fmt["properties"]["category"]["enum"]) == {
        "personal",
        "business",
        "newsletter",
        "notification",
    }
    assert "personal" in payload["prompt"]
    assert "alice@example.com" in payload["prompt"]


@pytest.mark.asyncio
async def test_classify_http_error_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        status_code=503,
    )
    async with Classifier(_cfg()) as c:
        with pytest.raises(ClassifierError):
            await c.classify(_item())
