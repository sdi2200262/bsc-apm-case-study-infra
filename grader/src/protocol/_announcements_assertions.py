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

The general-announcement assertions additionally check source
attribution. PRD §2.2 requires every entry in the response to
carry a ``Source: <attribution>`` line: admin entries are
attributed to ``System`` and course entries are attributed to
the course code as exposed by ``get_courses``. The helpers
below extract those attribution values and tabulate the
expected per-source counts for a given announcement set so the
assertion module can compare actual against expected as a
single equality check.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..seed import Announcement

ECLASS_BASE_URL = "http://localhost"

_SOURCE_LINE_PATTERN = re.compile(r"Source: (\S+)")


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


def source_attributions(text: str) -> tuple[str, ...]:
    """Return the captured value of every ``Source: <value>`` line.

    Each match captures the first whitespace-delimited token after
    the ``Source: `` prefix, in the order the lines appear in
    ``text``. The PRD's response template indents these lines with
    four spaces, but the helper matches the prefix anywhere in the
    text so a participant's exact whitespace handling is not
    over-constrained.
    """
    return tuple(match.group(1) for match in _SOURCE_LINE_PATTERN.finditer(text))


def expected_attribution_counts(
    announcements: Iterable[Announcement],
) -> dict[str, int]:
    """Return the expected per-attribution count for an announcement set.

    Admin entries (``course_code`` is ``None``) are attributed to
    ``System``; course entries are attributed to their course
    code. The result is the count of entries per attribution value.
    """
    counts: dict[str, int] = {}
    for announcement in announcements:
        key = (
            announcement.course_code
            if announcement.course_code is not None
            else "System"
        )
        counts[key] = counts.get(key, 0) + 1
    return counts


def attribution_counts(values: Iterable[str]) -> dict[str, int]:
    """Return the count of each value in ``values``."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
