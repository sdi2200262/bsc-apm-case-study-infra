#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Acceptance policy for the announcement-list scenario assertions.

Owns the two-form announcement matcher and the parsing and date
canonicalisation it relies on. :func:`match_announcements` records
``ANNOUNCEMENTS_ORDERED`` (the openeclass-derived order) or
``ANNOUNCEMENTS_UNORDERED`` (the same byte-exact entries compared as
an order-insensitive multiset), routing both forms through
:func:`grader.protocol.matching._try_forms`. The shared dispatch,
the mode constants, and the fixed-string matchers live in
:mod:`grader.protocol.matching`; this module imports from it and
is never imported by it, so the two form an acyclic pair.

PRD §2 leaves the rendered date string as an unspecified
``<Date String>`` placeholder, so each ``Date:`` line is canonicalised
to a calendar date before comparison and any rendering whose parsed
date matches the expected calendar date is a legitimate accept. Every
other field (title, body, source, count, grammar) stays byte-asserted.
The unordered form is a lenient acceptance warned for human review at
end of grading (see :mod:`grader.scoring.reporting`).
"""

from __future__ import annotations

import datetime as _datetime
import re
from collections import Counter

from dateutil import parser as _dateparser

from .expected import announcement_preamble
from .matching import (
    ANNOUNCEMENTS_ORDERED,
    ANNOUNCEMENTS_UNORDERED,
    _try_forms,
    normalize_response,
)

_DATE_LINE_RE = re.compile(r"^( {4}Date: )(.+)$", re.MULTILINE)


def match_announcements(
    text: str,
    expected_ordered: str,
    expected_entries: tuple[str, ...],
    expected_count: int,
    instant: _datetime.datetime,
) -> str | None:
    """Return the accepted announcement form, or ``None``.

    Two forms are accepted; both compare entries with each
    ``Date:`` line canonicalised to a calendar date (PRD §2 leaves
    the rendered date string as an unspecified ``<Date String>``
    placeholder, so any rendering whose parsed date matches the
    expected calendar date is a legitimate accept):

    - ``ANNOUNCEMENTS_ORDERED``: the response equals the
      openeclass-derived ordered string after each side's
      ``Date:`` line is replaced by its parsed calendar date and
      the non-breaking space family is normalised.
    - ``ANNOUNCEMENTS_UNORDERED``: the response parses by the PRD
      grammar into the same multiset of entries (same
      canonicalisation), but the sequence and the per-entry index
      number are not enforced. Every other field (title, body,
      source, count, grammar) is still enforced; a wrong calendar
      date, a missing/extra/duplicated entry, a malformed entry,
      or a ``Date:`` value that does not parse all fail.

    The matched form is the recorded diagnostic; the unordered
    form is lenient and is warned for human review at end of
    grading (see :mod:`grader.scoring.reporting`).

    Args:
        text: The tool's response text.
        expected_ordered: The constructed openeclass-derived ordered
            response.
        expected_entries: The index-free per-entry blocks the
            response must contain as a multiset, single-sourced
            from :mod:`.expected`.
        expected_count: The number of in-window entries the preamble
            must declare and the response must carry.
        instant: The run's seed-apply instant. Resolves the
            openeclass-rendered ``today, h:mm AM/PM`` relative form.

    Returns:
        ``ANNOUNCEMENTS_ORDERED`` or ``ANNOUNCEMENTS_UNORDERED`` for
        the accepted form, ``None`` when neither matches.
    """

    def _accepts_ordered() -> bool:
        # Form 1: parse the response by the PRD grammar (so we can
        # canonicalise the same per-entry date line as Form 2),
        # then check both the entries and their order against
        # expected.
        parsed = _parse_announcement_entries(text, expected_count)
        if parsed is None:
            return False
        canon_parsed = _canonicalise_entries(parsed, instant)
        canon_expected = _canonicalise_entries(
            [normalize_response(e) for e in expected_entries],
            instant,
        )
        if canon_parsed is None or canon_expected is None:
            return False
        return canon_parsed == canon_expected

    def _accepts_unordered() -> bool:
        parsed = _parse_announcement_entries(text, expected_count)
        if parsed is None:
            return False
        canon_parsed = _canonicalise_entries(parsed, instant)
        canon_expected = _canonicalise_entries(
            [normalize_response(e) for e in expected_entries],
            instant,
        )
        if canon_parsed is None or canon_expected is None:
            return False
        return Counter(canon_parsed) == Counter(canon_expected)

    return _try_forms(
        [
            (ANNOUNCEMENTS_ORDERED, _accepts_ordered),
            (ANNOUNCEMENTS_UNORDERED, _accepts_unordered),
        ]
    )


def _parse_announcement_entries(text: str, expected_count: int) -> list[str] | None:
    """Parse a populated announcement response into its index-free entries.

    Inverts the ``preamble + blank line + blank-line-separated
    entries`` construction (see
    :func:`grader.protocol.expected.course_response`). The
    space-family normalisation is applied to the whole response
    first; it touches only the space codepoints, so newlines and
    indentation are unaffected and the blank-line split is exact.
    The leading ``<n>. `` index of each entry is stripped because
    Form 2 does not enforce the sequence number; every other byte is
    preserved for the multiset comparison the caller performs.

    Total by contract: any structural surprise (a wrong preamble or
    count, a block without an index prefix, the wrong number of
    blank-line-separated blocks) returns ``None`` rather than
    raising, so a malformed response is a failed row, not a crash.

    Args:
        text: The tool's response text.
        expected_count: The entry count the preamble must declare and
            the response must carry (always positive: the empty-window
            rows use :func:`match_exact`, never this path).

    Returns:
        The index-free, space-normalised entry blocks, or ``None``
        when the response does not parse as a populated response of
        exactly ``expected_count`` entries.
    """
    normalized = normalize_response(text)
    parts = normalized.split("\n\n")
    if len(parts) != expected_count + 1:
        return None
    if parts[0] != normalize_response(announcement_preamble(expected_count)):
        return None
    entries: list[str] = []
    for block in parts[1:]:
        index_prefix = re.match(r"\d+\. ", block)
        if index_prefix is None:
            return None
        entries.append(block[index_prefix.end() :])
    return entries


def _parse_date_to_calendar(
    value: str,
    instant: _datetime.datetime,
) -> tuple[int, int, int] | None:
    """Parse ``value`` to ``(year, month, day)``, or ``None``.

    PRD §2 leaves the rendered date string unspecified, so accept
    whatever ``dateutil.parser.parse`` accepts (RFC 2822, ISO
    8601, the openeclass absolute form, locale-formatted
    variants, common compact shapes). ``instant`` resolves the
    openeclass-rendered ``today, h:mm AM/PM`` relative form,
    which dateutil treats as a word rather than a date.
    """
    s = value.strip()
    if s.lower().startswith("today"):
        d = instant.date()
        return (d.year, d.month, d.day)
    try:
        d = _dateparser.parse(s).date()
        return (d.year, d.month, d.day)
    except (ValueError, OverflowError, TypeError):
        return None


def _canonicalise_entries(
    entries: list[str],
    instant: _datetime.datetime,
) -> list[str] | None:
    """Return ``entries`` with each ``Date:`` line rewritten to YYYY-MM-DD.

    Returns ``None`` if any entry lacks a parseable ``Date:`` line;
    that fails the match. Every other byte is preserved so title,
    body, source, and indentation are still byte-asserted.
    """
    out: list[str] = []
    for entry in entries:
        match = _DATE_LINE_RE.search(entry)
        if match is None:
            return None
        calendar = _parse_date_to_calendar(match.group(2), instant)
        if calendar is None:
            return None
        year, month, day = calendar
        canonical = f"{match.group(1)}{year:04d}-{month:02d}-{day:02d}"
        out.append(entry[: match.start()] + canonical + entry[match.end() :])
    return out
