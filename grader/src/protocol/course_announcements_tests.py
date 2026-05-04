#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Course-announcements protocol assertions.

Each function tests one P.2 / C.3 row from the rubric against a
freshly-spawned MCP server. The functions take ``impl`` as the
first parameter so the Python and C aggregators drive the same
body through either implementation.

Strict-tier assertions check exact equality against the documented
error and empty-result strings. Implementation-tier and anchor-
tier assertions exercise the per-course endpoint at varying
``days_back`` values, asserting the seed-derived count preamble
and the verbatim body of every in-scope announcement.

The seeded test course is ``CS101`` (announcements at ``days_ago``
0, 15, 30, 60); the empty course is ``MATH201`` (no
announcements).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..seed import SEED, course_announcements_in_window
from ._announcements_assertions import (
    assert_count_and_bodies,
    course_url,
)
from .runner import (
    call_tool,
    extract_text,
    initialize_server,
    spawn_server,
    tool_exists,
)

TOOL_NAME = "get_course_announcements"
TEST_COURSE = "CS101"
EMPTY_COURSE = "MATH201"
DEFAULT_DAYS_BACK = 30

ERR_NOT_LOGGED_IN = "Error: Not logged in. Please log in first using the login tool."
ERR_BAD_URL = "Error: Could not extract course code."
ERR_BAD_DAYS = "Error: days_back must be a non-negative integer."
EMPTY_RESULT = "No announcements found."

SERVER_START_FAIL = (False, "Could not start server", "Server failed to start")


def test_course_not_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.2.1 / C.3.1: tool without a prior login returns the not-logged-in error."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, TOOL_NAME):
            return _missing_tool_failure()
        response = call_tool(server, TOOL_NAME, {"course_url": course_url(TEST_COURSE)})
        text = extract_text(response)
        if text == ERR_NOT_LOGGED_IN:
            return True, "exact not-logged-in error matched", text
        return False, f"expected exact '{ERR_NOT_LOGGED_IN}', got: '{text}'", text


def test_course_invalid_url(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.2.2 / C.3.2: an unparseable ``course_url`` returns the extract-code error."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, TOOL_NAME):
            return _missing_tool_failure()
        call_tool(server, "login", {})
        response = call_tool(server, TOOL_NAME, {"course_url": "invalid-url"})
        text = extract_text(response)
        if text == ERR_BAD_URL:
            return True, "exact extract-code error matched", text
        return False, f"expected exact '{ERR_BAD_URL}', got: '{text}'", text


def test_course_negative_days(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.2.3 / C.3.3: a negative ``days_back`` returns the positive-integer error."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, TOOL_NAME):
            return _missing_tool_failure()
        call_tool(server, "login", {})
        response = call_tool(
            server,
            TOOL_NAME,
            {"course_url": course_url(TEST_COURSE), "days_back": -5},
        )
        text = extract_text(response)
        if text == ERR_BAD_DAYS:
            return True, "exact positive-integer error matched", text
        return False, f"expected exact '{ERR_BAD_DAYS}', got: '{text}'", text


def test_course_empty_course(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.2.4 / C.3.4: a course with no announcements returns the empty-result string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, TOOL_NAME):
            return _missing_tool_failure()
        call_tool(server, "login", {})
        response = call_tool(server, TOOL_NAME, {"course_url": course_url(EMPTY_COURSE)})
        text = extract_text(response)
        if text == EMPTY_RESULT:
            return True, "exact empty-result string matched", text
        return False, f"expected exact '{EMPTY_RESULT}', got: '{text}'", text


def test_course_days_zero(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.2.5 / C.3.5: ``days_back=0`` returns the day-zero announcement only."""
    return _impl_window_test(impl, eclass_dir, mock_root, debug, days_back=0)


def test_course_days_15(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.2.6 / C.3.6: ``days_back=15`` returns the two in-scope announcements."""
    return _impl_window_test(impl, eclass_dir, mock_root, debug, days_back=15)


def test_course_default(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.2.7 / C.3.7: default ``days_back`` returns the three in-scope announcements."""
    return _impl_window_test(
        impl, eclass_dir, mock_root, debug, days_back=DEFAULT_DAYS_BACK
    )


def test_course_days_60(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.2.8 / C.3.8: ``days_back=60`` returns all four announcements."""
    return _impl_window_test(impl, eclass_dir, mock_root, debug, days_back=60)


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
        args: dict = {"course_url": course_url(TEST_COURSE)}
        if days_back != DEFAULT_DAYS_BACK:
            args["days_back"] = days_back
        response = call_tool(server, TOOL_NAME, args)
        text = extract_text(response)
        if not text:
            return False, "empty or invalid response", json.dumps(response)
        expected = course_announcements_in_window(SEED, TEST_COURSE, days_back)
        ok, message = assert_count_and_bodies(text, expected)
        return ok, message, text


def _missing_tool_failure() -> tuple[bool, str, str]:
    """Return the structured failure tuple for an unimplemented tool."""
    return False, f"{TOOL_NAME} tool not implemented", "Tool not found in tools/list"
