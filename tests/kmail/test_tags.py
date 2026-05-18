# SPDX-License-Identifier: MIT
import pytest

from lares.kmail.tags import (
    LARES_ERROR,
    LARES_PENDING,
    LARES_TAG_PREFIX,
    LARES_UNCLASSIFIED,
    is_lares_tag,
)


def test_namespace_prefix_is_consistent():
    assert LARES_PENDING.startswith(LARES_TAG_PREFIX)
    assert LARES_UNCLASSIFIED.startswith(LARES_TAG_PREFIX)
    assert LARES_ERROR.startswith(LARES_TAG_PREFIX)


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("lares-pending", True),
        ("lares-unclassified", True),
        ("lares-error", True),
        ("lares-personal", True),
        ("personal", False),
        ("Personal", False),
        ("", False),
        ("LARES-PENDING", False),  # case-sensitive
        ("lares_pending", False),  # underscore, not dash
    ],
)
def test_is_lares_tag(tag: str, expected: bool) -> None:
    assert is_lares_tag(tag) is expected
