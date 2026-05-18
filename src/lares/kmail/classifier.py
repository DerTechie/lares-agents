# SPDX-License-Identifier: MIT
"""Ollama-backed mail classifier.

Builds the prompt and the JSON Schema from the config-driven tag taxonomy,
calls Ollama's /api/generate with structured-output enforcement and
temperature=0, validates the response with pydantic, and returns a Verdict
whose `tag` is already prefixed with `lares-` (or `lares-unclassified` if
confidence is below the configured threshold).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lares.kmail.tags import LARES_TAG_PREFIX, LARES_UNCLASSIFIED

if TYPE_CHECKING:
    from types import TracebackType

    from lares.kmail.config import LaresConfig

logger = logging.getLogger(__name__)


class ClassifierError(Exception):
    """Recoverable error during classification (transport, parse, or schema)."""


@dataclass(slots=True, frozen=True)
class FetchedItem:
    item_id: int
    headers: dict[str, str]
    body_text: str


@dataclass(slots=True, frozen=True)
class Verdict:
    tag: str
    raw_category: str
    confidence: float


class _OllamaResponseEnvelope(BaseModel):
    response: str
    # Ollama emits other fields (model, created_at, done, ...); we ignore them.

    model_config = ConfigDict(extra="ignore")


class _RawVerdict(BaseModel):
    """Decoded LLM response. `category` is validated against the allowed
    set explicitly in `Classifier.classify` — pydantic only enforces the
    type and the confidence range here. Keeping the allowed-set check out
    of the schema avoids a pyright-strict struggle with dynamic Literal
    construction."""

    category: str
    confidence: float = Field(ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")


class Classifier:
    def __init__(self, config: LaresConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._categories = sorted(config.kmail.tags.keys())
        self._allowed_categories = set(self._categories)
        self._json_schema = self._build_schema()
        self._prompt_prefix = self._build_prompt_prefix()

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            base_url=self._config.lares.ollama.endpoint,
            timeout=self._config.kmail.classify_timeout_s,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def classify(self, item: FetchedItem) -> Verdict:
        if self._client is None:
            raise RuntimeError("Classifier used outside async context manager")
        payload = self._build_payload(item)
        try:
            resp = await self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClassifierError(f"ollama transport error: {exc}") from exc

        try:
            envelope = _OllamaResponseEnvelope.model_validate(resp.json())
            parsed = json.loads(envelope.response)
            verdict = _RawVerdict.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError, KeyError) as exc:
            raise ClassifierError(f"ollama response parse failure: {exc}") from exc

        if verdict.category not in self._allowed_categories:
            raise ClassifierError(
                f"model returned unknown category {verdict.category!r}; "
                f"allowed={sorted(self._allowed_categories)}"
            )
        category = verdict.category
        confidence = verdict.confidence
        if confidence < self._config.kmail.min_confidence:
            tag = LARES_UNCLASSIFIED
        else:
            tag = f"{LARES_TAG_PREFIX}{category}"
        logger.info(
            "classified item_id=%d category=%s confidence=%.2f -> tag=%s",
            item.item_id,
            category,
            confidence,
            tag,
        )
        return Verdict(tag=tag, raw_category=category, confidence=confidence)

    def _build_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": self._categories},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["category", "confidence"],
            "additionalProperties": False,
        }

    def _build_prompt_prefix(self) -> str:
        lines = ["You classify incoming email into exactly one of these categories:", ""]
        for name in self._categories:
            lines.append(f"- {name}: {self._config.kmail.tags[name]}")
        lines.extend(
            [
                "",
                "Respond with JSON only, no prose:",
                '{"category": "<one of the above>", "confidence": <0.0 to 1.0>}',
                "",
            ]
        )
        return "\n".join(lines)

    def _build_payload(self, item: FetchedItem) -> dict[str, Any]:
        h = item.headers
        prompt = (
            f"{self._prompt_prefix}"
            f"Email:\n"
            f"From: {h.get('From', '')}\n"
            f"To: {h.get('To', '')}\n"
            f"Subject: {h.get('Subject', '')}\n"
            f"List-Id: {h.get('List-Id', '')}\n"
            f"Date: {h.get('Date', '')}\n\n"
            f"{item.body_text}"
        )
        return {
            "model": self._config.lares.ollama.model,
            "prompt": prompt,
            "format": self._json_schema,
            "options": {"temperature": self._config.lares.ollama.temperature},
            "stream": False,
        }
