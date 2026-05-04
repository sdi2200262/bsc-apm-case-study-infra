#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Shared assertion helpers for course and general announcement tests.

The course-announcements and general-announcements assertions
follow the same shape: assert the ``Found <N> announcement(s):``
preamble with a seed-derived ``N``, then assert that every in-
scope announcement's body string is present verbatim in the
response. The helpers here implement that pattern in one place
so the two assertion modules read as straight tabular tests.

The general-announcement anchor additionally checks that source
attribution is rendered (``Source: System`` for admin entries,
``Source: <code>`` for course entries); the helper for that lives
here so the regex used to count distinct course-source
attributions is shared.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..seed import SEED, Announcement

ECLASS_BASE_URL = "http://localhost"
SOURCE_SYSTEM = "Source: System"

_COURSE_SOURCE_PATTERN = re.compile(
    r"Source: (" + "|".join(re.escape(c) for c in SEED.enrolled_course_codes) + r")"
)


def course_url(code: str) -> str:
    """Return the openeclass URL for a course code."""
    return f"{ECLASS_BASE_URL}/courses/{code}/"


def expected_preamble(count: int) -> str:
    """Return the verbatim preamble for a populated announcements response."""
    return f"Found {count} announcement(s):"


def assert_count_and_bodies(
    text: str, expected: Iterable[Announcement]
) -> tuple[bool, str]:
    """Assert the preamble count and every expected body verbatim.

    Args:
        text: Response text returned by the announcement tool.
        expected: Announcements that should appear in the response,
            in any order.

    Returns:
        Tuple of ``(ok, message)``. ``message`` names the first
        failed sub-assertion when ``ok`` is ``False`` and a short
        success summary otherwise.
    """
    expected_list = list(expected)
    preamble = expected_preamble(len(expected_list))
    if preamble not in text:
        return False, f"missing preamble '{preamble}'"
    missing = [a for a in expected_list if a.body not in text]
    if missing:
        first = missing[0]
        marker = f"days_ago={first.days_ago}"
        if first.course_code is not None:
            marker = f"{first.course_code} {marker}"
        return False, f"missing body for {marker} ('{first.body[:60]}...')"
    return True, f"preamble and {len(expected_list)} bodies present"


def distinct_course_sources(text: str) -> set[str]:
    """Return the set of enrolled course codes attributed via ``Source:``."""
    return {match.group(1) for match in _COURSE_SOURCE_PATTERN.finditer(text)}
