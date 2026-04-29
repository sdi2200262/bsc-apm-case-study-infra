#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
General-announcements protocol assertions.

Each function tests one P.3 / C.4 row from the rubric against a
freshly-spawned MCP server. The functions take ``impl`` as the
first parameter so the Python and C aggregators drive the same
body through either implementation.

Strict-tier assertions check exact equality against the documented
error strings. Implementation-tier assertions exercise the general
endpoint at varying ``days_back`` values, asserting the seed-
derived count preamble and the verbatim body of every in-scope
announcement (admin entries plus enrolled-course entries within
the 30-day backend floor).

The anchor (P.3.6 / C.4.6) additionally asserts that the response
renders system attribution with ``Source: System`` and that at
least two distinct enrolled-course attributions appear, confirming
the implementation aggregates rather than serving a single source.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..seed import SEED, general_announcements_in_window
from ._announcements_assertions import (
    SOURCE_SYSTEM,
    assert_count_and_bodies,
    distinct_course_sources,
)
from .runner import (
    call_tool,
    extract_text,
    initialize_server,
    spawn_server,
    tool_exists,
)

TOOL_NAME = "get_general_announcements"
DEFAULT_DAYS_BACK = 30
MIN_DISTINCT_COURSE_SOURCES = 2

ERR_NOT_LOGGED_IN = "Error: Not logged in. Please log in first using the login tool."
ERR_BAD_DAYS = "Error: days_back must be a positive integer."
ERR_OVER_THIRTY = "Error: Cannot retrieve announcements older than 30 days."

SERVER_START_FAIL = (False, "Could not start server", "Server failed to start")


def test_general_not_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.3.1 / C.4.1: tool without a prior login returns the not-logged-in error."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, TOOL_NAME):
            return _missing_tool_failure()
        response = call_tool(server, TOOL_NAME, {})
        text = extract_text(response)
        if text == ERR_NOT_LOGGED_IN:
            return True, "exact not-logged-in error matched", text
        return False, f"expected exact '{ERR_NOT_LOGGED_IN}', got: '{text}'", text


def test_general_negative_days(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.3.2 / C.4.2: a negative ``days_back`` returns the positive-integer error."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, TOOL_NAME):
            return _missing_tool_failure()
        call_tool(server, "login", {})
        response = call_tool(server, TOOL_NAME, {"days_back": -5})
        text = extract_text(response)
        if text == ERR_BAD_DAYS:
            return True, "exact positive-integer error matched", text
        return False, f"expected exact '{ERR_BAD_DAYS}', got: '{text}'", text


def test_general_over_thirty(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.3.3 / C.4.3: ``days_back=31`` returns the older-than-thirty error."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, TOOL_NAME):
            return _missing_tool_failure()
        call_tool(server, "login", {})
        response = call_tool(server, TOOL_NAME, {"days_back": 31})
        text = extract_text(response)
        if text == ERR_OVER_THIRTY:
            return True, "exact older-than-thirty error matched", text
        return False, f"expected exact '{ERR_OVER_THIRTY}', got: '{text}'", text


def test_general_days_zero(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.3.4 / C.4.4: ``days_back=0`` returns the three day-zero announcements."""
    return _impl_window_test(impl, eclass_dir, mock_root, debug, days_back=0)


def test_general_days_15(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.3.5 / C.4.5: ``days_back=15`` returns the six in-scope announcements."""
    return _impl_window_test(impl, eclass_dir, mock_root, debug, days_back=15)


def test_general_default_aggregation(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.3.6 / C.4.6: default returns nine announcements with multi-source attribution."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, TOOL_NAME):
            return _missing_tool_failure()
        call_tool(server, "login", {})
        response = call_tool(server, TOOL_NAME, {})
        text = extract_text(response)
        if not text:
            return False, "empty or invalid response", json.dumps(response)
        expected = general_announcements_in_window(SEED, DEFAULT_DAYS_BACK)
        ok, message = assert_count_and_bodies(text, expected)
        if not ok:
            return False, message, text
        if SOURCE_SYSTEM not in text:
            return False, f"missing '{SOURCE_SYSTEM}' attribution", text
        course_sources = distinct_course_sources(text)
        if len(course_sources) < MIN_DISTINCT_COURSE_SOURCES:
            return (
                False,
                f"only {len(course_sources)} distinct course-source attribution(s); "
                f"expected at least {MIN_DISTINCT_COURSE_SOURCES}",
                text,
            )
        return (
            True,
            f"preamble, nine bodies, system source, "
            f"{len(course_sources)} distinct course sources",
            text,
        )


def _impl_window_test(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    days_back: int,
) -> tuple[bool, str, str]:
    """Drive the implementation-tier window assertion at one ``days_back`` value."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, TOOL_NAME):
            return _missing_tool_failure()
        call_tool(server, "login", {})
        args: dict = {} if days_back == DEFAULT_DAYS_BACK else {"days_back": days_back}
        response = call_tool(server, TOOL_NAME, args)
        text = extract_text(response)
        if not text:
            return False, "empty or invalid response", json.dumps(response)
        expected = general_announcements_in_window(SEED, days_back)
        ok, message = assert_count_and_bodies(text, expected)
        return ok, message, text


def _missing_tool_failure() -> tuple[bool, str, str]:
    """Return the structured failure tuple for an unimplemented tool."""
    return False, f"{TOOL_NAME} tool not implemented", "Tool not found in tools/list"
