# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""The single five-category extraction of a ``message.usage`` block.

A ``message.usage`` block reports tokens in several fields; the cost and
token layers price them in five categories (input, output, cache-read, and
the two cache-creation TTLs). This leaf module owns that extraction so the
main-call path, the delegated-dispatch path, and the subagent-transcript
summation all read a usage block the same way, with no re-derivation. It
depends only on the rate-table category constants, so every population's
token accounting shares one definition without an import cycle.
"""

from __future__ import annotations

from typing import Any

from ..rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
)


def token_sums_dict_from_usage(usage: dict[str, Any]) -> dict[str, int]:
    """Extract the five-category token bag from a ``message.usage`` block.

    Returns a dict keyed by ``rates.CATEGORY_*`` constants; missing fields
    contribute zero. The two cache-creation TTLs are read from the nested
    ``cache_creation`` object when present.
    """
    cache_creation = usage.get("cache_creation")
    if isinstance(cache_creation, dict):
        cache_5m = _int_or_zero(cache_creation.get("ephemeral_5m_input_tokens"))
        cache_1h = _int_or_zero(cache_creation.get("ephemeral_1h_input_tokens"))
    else:
        cache_5m = 0
        cache_1h = 0
    return {
        CATEGORY_INPUT: _int_or_zero(usage.get("input_tokens")),
        CATEGORY_OUTPUT: _int_or_zero(usage.get("output_tokens")),
        CATEGORY_CACHE_READ: _int_or_zero(usage.get("cache_read_input_tokens")),
        CATEGORY_CACHE_5M: cache_5m,
        CATEGORY_CACHE_1H: cache_1h,
    }


def _int_or_zero(value: Any) -> int:
    """Return ``value`` when it is an int, otherwise ``0``."""
    return value if isinstance(value, int) else 0
