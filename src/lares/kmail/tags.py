# SPDX-License-Identifier: MIT
"""Tag namespace constants and predicate.

All Lares-managed Akonadi tags share the `lares-` prefix. The control tags
(`lares-pending`, `lares-unclassified`, `lares-error`) are reserved; user
taxonomy tags from `[kmail.tags]` are prefixed with `lares-` when applied
to items so the mutate helper's namespace-scoped replace semantics work
uniformly.
"""

LARES_TAG_PREFIX = "lares-"

LARES_PENDING = "lares-pending"
LARES_UNCLASSIFIED = "lares-unclassified"
LARES_ERROR = "lares-error"


def is_lares_tag(tag: str) -> bool:
    return tag.startswith(LARES_TAG_PREFIX)
