#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Expected response strings for the exact-string scenario assertions.

Each announcement row asserts one exact full-string match against
an expected response built here. The date forms and the
``get_courses`` layout constant are openeclass-version-specific;
they are derived from the grading environment and the seed data,
not captured from a live run.

Date forms (English locale on the grading environment):

- Relative, day-0 items only: ``today, <h>:<mm> <AM|PM>`` with a
  lowercase ``today``, a comma then one ASCII space, a 12-hour
  clock, and a U+202F narrow no-break space before the meridiem.
- Absolute, every older item: ``<EEEE>, <MMMM> <D>, <YYYY>,
  <h>:<mm> <AM|PM>`` with the full English weekday and month, a
  no-leading-zero day, a 4-digit year, and the same U+202F before
  the meridiem.

The seed loader anchors every row to ``NOW() - days_ago days`` at
seed time, so every announcement shares the run's time component
and only the day shifts. The caller supplies that instant; this
module formats it; the faithful U+202F before the meridiem is
constructed here verbatim as the platform renders it.

This module only constructs the faithful output. Whether a
response is accepted (byte for byte, after whitespace
normalisation, or as one of the two ``get_courses`` forms) is the
``matching`` module's single responsibility.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..seed import Announcement, Course

# Narrow no-break space (U+202F) the platform renders before the
# meridiem; a plain ASCII space here breaks the exact-string match.
NARROW_NBSP = " "

# Four-space indent on the Source/Date/Content lines of an entry.
ENTRY_INDENT = "    "

# The get_courses course-link list lives under a three-space URL indent.
URL_INDENT = "   "

ECLASS_BASE_URL = "http://localhost"

# openeclass 4.3.3 renders each course link as
# `<title><GLUE>(<code>)`; the reference parser's `.lesson-title`
# selector keeps the run between the title and `(code)` verbatim
# after `link.text.strip()`. GLUE is exactly U+00A0, CR, LF, then
# 164 ASCII spaces: an openeclass-version-specific layout constant.
GET_COURSES_GLUE = " \r\n" + " " * 164

# English names; locale is English on the grading environment.
_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# Exact error and empty-window strings (PRD; not substrings).
ERR_NOT_LOGGED_IN = (
    "Error: Not logged in. Please log in first using the login tool."
)
ERR_BAD_COURSE_URL = "Error: Could not extract course code."
ERR_NEGATIVE_DAYS_BACK = "Error: days_back must be a non-negative integer."
ERR_GENERAL_UPPER_BOUND = (
    "Error: Cannot retrieve announcements older than 30 days."
)
NO_ANNOUNCEMENTS = "No announcements found."

SYSTEM_SOURCE = "System"

# Constructed handshake contract: the expected ``initialize`` and
# ``tools/list`` responses the baseline rows (C.2.1, C.2.2, P.1.1)
# are judged against. These are fixed constants built from the
# published wire contract, never captured from a graded submission
# and never obtained by spawning a server at grade time. The
# eclass-mcp-server dependency floor (``mcp>=1.24.0``, Python >=3.10)
# admits a finite set of ``mcp`` releases (the Python MCP SDK), and
# the low-level ``initialize``/``tools/list`` wire serialisation is
# byte-identical across that entire set, so a single constructed
# contract is exact; ``preflight.assert_mcp_release_verified`` fails
# the run loudly if the resolved ``mcp`` is outside the verified set.

# Every baseline tool advertises this one no-argument input schema.
BASELINE_TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "random_string": {
            "type": "string",
            "description": "Dummy parameter for no-parameter tools",
        }
    },
    "required": ["random_string"],
}

# The four baseline tools, verbatim from the wire-protocol reference,
# in its declared order.
BASELINE_TOOLS: tuple[dict, ...] = (
    {
        "name": "login",
        "description": "Log in to eClass using username/password from your .env file through UoA's SSO. Configure ECLASS_USERNAME and ECLASS_PASSWORD in your .env file.",
        "inputSchema": BASELINE_TOOL_INPUT_SCHEMA,
    },
    {
        "name": "get_courses",
        "description": "Get list of enrolled courses from eClass",
        "inputSchema": BASELINE_TOOL_INPUT_SCHEMA,
    },
    {
        "name": "logout",
        "description": "Log out from eClass",
        "inputSchema": BASELINE_TOOL_INPUT_SCHEMA,
    },
    {
        "name": "authstatus",
        "description": "Check authentication status with eClass",
        "inputSchema": BASELINE_TOOL_INPUT_SCHEMA,
    },
)

# The two announcement tools the task adds. The wire-protocol and
# tools reference documents cover only the four baseline tools, so
# the sole source for these two is the task PRD section 2; their
# name, description, and input schema are transcribed from it.
ANNOUNCEMENT_TOOLS: tuple[dict, ...] = (
    {
        "name": "get_course_announcements",
        "description": "Fetches announcements for a single course, optionally filtered by recency.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "course_url": {
                    "type": "string",
                    "description": "The course URL as exposed by get_courses.",
                },
                "days_back": {
                    "type": "integer",
                    "description": "Number of days back to include. Zero is valid and returns today's announcements only. Default is 30.",
                },
            },
            "required": ["course_url"],
        },
    },
    {
        "name": "get_general_announcements",
        "description": "Returns a unified view of the platform's system-wide announcements together with announcements from the authenticated user's enrolled courses, with source attribution on each entry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days back to include. Zero is valid and returns today's announcements only. Default is 30.",
                },
            },
        },
    },
)

# The full advertised tool set, baseline first, in declared order.
ALL_TOOL_OBJECTS: tuple[dict, ...] = BASELINE_TOOLS + ANNOUNCEMENT_TOOLS

INITIALIZE_PROTOCOL_VERSION = "2025-03-26"
INITIALIZE_SERVER_INFO = {"name": "eclass-mcp", "version": "0.1.0"}

# Two accepted `initialize.capabilities` objects. CAPABILITIES_LIBRARY
# is what the MCP SDK actually serialises for a tools-only low-level
# server across the entire supported `mcp` range. CAPABILITIES_DOC is
# the object the project's own wire-protocol reference (section 1)
# documents. The two differ, and no `mcp` release in the supported
# range emits the documented object: the wire-protocol reference is
# inaccurate on this point. Because that reference is published task
# material, building the handshake to it is a legitimate reading, so
# both objects are accepted and the matched one is recorded as the
# row's diagnostic. Neither is captured from a submission.
CAPABILITIES_LIBRARY = {"experimental": {}, "tools": {"listChanged": False}}
CAPABILITIES_DOC = {
    "tools": {"listChanged": False},
    "prompts": {},
    "resources": {},
}


def expected_tools_list() -> tuple[dict, ...]:
    """Return the expected ``tools/list`` tool objects.

    Returns:
        The six tool objects (four baseline, two announcement) in
        declared order, each carrying ``name``, ``description``, and
        ``inputSchema``.
    """
    return ALL_TOOL_OBJECTS


def _clock_token(instant: datetime) -> str:
    """Return the 12-hour ``<h>:<mm><U+202F><AM|PM>`` clock token.

    Args:
        instant: The datetime whose time component to render. Every
            announcement in a run shares this component.

    Returns:
        The clock token: a no-leading-zero 12-hour hour, a
        colon-separated zero-padded minute, the U+202F narrow
        no-break space, then ``AM`` or ``PM``.
    """
    period = "AM" if instant.hour < 12 else "PM"
    hour12 = instant.hour % 12 or 12
    return f"{hour12}:{instant.minute:02d}{NARROW_NBSP}{period}"


def announcement_date(instant: datetime, days_ago: int) -> str:
    """Return the rendered date string for one announcement.

    A ``days_ago`` of 0 is the run instant itself and renders in
    the relative form; every older entry renders in the absolute
    form at ``instant - days_ago days`` (the seed shifts whole days
    only, so the time component is unchanged).

    Args:
        instant: The run's seed-apply instant.
        days_ago: The announcement's seeded age in whole days.

    Returns:
        The exact date string for the entry's ``Date:`` line.
    """
    clock = _clock_token(instant)
    if days_ago == 0:
        return f"today, {clock}"
    moment = instant - timedelta(days=days_ago)
    weekday = _WEEKDAYS[moment.weekday()]
    month = _MONTHS[moment.month - 1]
    return f"{weekday}, {month} {moment.day}, {moment.year}, {clock}"


def _preamble(count: int) -> str:
    """Return the populated-response preamble for ``count`` entries."""
    return f"Found {count} announcement(s):"


def announcement_preamble(count: int) -> str:
    """Return the populated-announcement-response preamble for ``count`` entries.

    The single source for the ``Found <N> announcement(s):`` grammar.
    The matcher's order-insensitive form reconstructs the expected
    preamble through this rather than transcribing the format, so
    there is no duplicate that can drift from :func:`course_response`
    / :func:`general_response`.

    Args:
        count: Number of in-window announcements.

    Returns:
        The exact preamble line for a populated response.
    """
    return _preamble(count)


def course_entries(
    instant: datetime, announcements: tuple[Announcement, ...]
) -> tuple[str, ...]:
    """Return the per-entry blocks of a course response, without the index.

    Each element is one announcement's ``<Title>`` /
    ``    Date: <Date>`` / ``    Content: <Body>`` block as the tool
    must emit it, but without the leading ``<n>. `` sequence number;
    :func:`course_response` re-applies the index. The order-insensitive
    acceptance form compares this index-free set as a multiset, so
    the per-entry construction is single-sourced here.

    Args:
        instant: The run's seed-apply instant.
        announcements: In-window announcements, newest first.

    Returns:
        One index-free entry block per announcement, in input order.
    """
    return tuple(
        f"{a.title}\n"
        f"{ENTRY_INDENT}Date: {announcement_date(instant, a.days_ago)}\n"
        f"{ENTRY_INDENT}Content: {a.body}"
        for a in announcements
    )


def general_entries(
    instant: datetime, announcements: tuple[Announcement, ...]
) -> tuple[str, ...]:
    """Return the per-entry blocks of a general response, without the index.

    Same as :func:`course_entries` plus a ``    Source: <attribution>``
    line after the title: ``System`` for a system-wide announcement,
    the course code for a course announcement. The leading ``<n>. ``
    sequence number is omitted; :func:`general_response` re-applies
    it.

    Args:
        instant: The run's seed-apply instant.
        announcements: In-window announcements, newest first across
            the system-wide and enrolled-course union.

    Returns:
        One index-free entry block per announcement, in input order.
    """
    blocks: list[str] = []
    for a in announcements:
        source = a.course_code if a.course_code is not None else SYSTEM_SOURCE
        blocks.append(
            f"{a.title}\n"
            f"{ENTRY_INDENT}Source: {source}\n"
            f"{ENTRY_INDENT}Date: {announcement_date(instant, a.days_ago)}\n"
            f"{ENTRY_INDENT}Content: {a.body}"
        )
    return tuple(blocks)


def _number(entries: tuple[str, ...]) -> str:
    """Return ``entries`` re-numbered and joined into the populated body.

    Re-applies the ``<n>. `` sequence prefix at the join site so the
    ordered string is built from the same single-source per-entry
    blocks the multiset form compares.
    """
    numbered = [
        f"{index}. {entry}" for index, entry in enumerate(entries, start=1)
    ]
    return _preamble(len(entries)) + "\n\n" + "\n\n".join(numbered)


def course_response(
    instant: datetime, announcements: tuple[Announcement, ...]
) -> str:
    """Return the exact expected ``get_course_announcements`` success response.

    Empty input returns the empty-window string rather than a
    zero-count preamble; that path is asserted by the empty-window
    scenarios.

    Args:
        instant: The run's seed-apply instant.
        announcements: In-window announcements, newest first.

    Returns:
        The exact response text the tool must emit.
    """
    if not announcements:
        return NO_ANNOUNCEMENTS
    return _number(course_entries(instant, announcements))


def general_response(
    instant: datetime, announcements: tuple[Announcement, ...]
) -> str:
    """Return the exact expected ``get_general_announcements`` success response.

    Same layout as :func:`course_response` plus a ``Source:`` line per
    entry: ``System`` for a system-wide announcement, the course
    code for a course announcement.

    Args:
        instant: The run's seed-apply instant.
        announcements: In-window announcements, newest first across
            the system-wide and enrolled-course union.

    Returns:
        The exact response text the tool must emit.
    """
    if not announcements:
        return NO_ANNOUNCEMENTS
    return _number(general_entries(instant, announcements))


def course_url(code: str) -> str:
    """Return the openeclass course URL for a course code.

    Args:
        code: Course code (``"CS101"``).

    Returns:
        ``http://localhost/courses/<code>/``; the single source the
        scenario modules and the ``get_courses`` form constructor
        both use, so the URL the rubric expects cannot drift between
        a scenario and the response form.
    """
    return f"{ECLASS_BASE_URL}/courses/{code}/"


def _get_courses_form(courses: tuple[Course, ...], name_glued: bool) -> str:
    """Return one ``get_courses`` form for the enrolled-course list.

    Args:
        courses: The user's courses in title-alphabetical order
            (the openeclass portfolio link order).
        name_glued: When ``True`` the entry name is the
            openeclass-formatted ``<title><GLUE>(<code>)``; when
            ``False`` it is the documented-clean ``<title>``.

    Returns:
        The exact response text for that form.
    """
    entries = []
    for index, course in enumerate(courses, start=1):
        if name_glued:
            name = f"{course.title}{GET_COURSES_GLUE}({course.code})"
        else:
            name = course.title
        entries.append(
            f"{index}. {name}\n{URL_INDENT}URL: {course_url(course.code)}"
        )
    return f"Found {len(courses)} courses:\n\n" + "\n".join(entries)


def get_courses_forms(courses: tuple[Course, ...]) -> tuple[str, str]:
    """Return the ``(faithful, documented_clean)`` ``get_courses`` forms.

    ``tools-reference.md`` documents a clean format while the Python
    reference server reproduces the openeclass layout glue; both are
    legitimate readings of the task materials, so the accept-set is
    exactly these two byte-exact strings. The count grammar always
    pluralises ``courses``.

    Args:
        courses: The user's courses in title-alphabetical order.

    Returns:
        Form 1 (the openeclass-formatted string the Python reference
        emits) and Form 2 (documented-clean per
        ``tools-reference.md``).
    """
    return (
        _get_courses_form(courses, name_glued=True),
        _get_courses_form(courses, name_glued=False),
    )
