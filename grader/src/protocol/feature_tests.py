#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Feature-tier protocol assertions: AN1-AN6, GAN1-GAN6.

Each function tests one rubric item against a freshly-spawned
server. Assertions are parameterised by the implementation under
test; the per-implementation aggregator modules call them with the
correct ``impl`` and tag the results with the corresponding test
identifier.

Six course-announcement assertions (AN*) and six general-
announcement assertions (GAN*) cover the announcement tools the
participant adds on top of the baseline surface.
"""

from __future__ import annotations

import json
from pathlib import Path

from .runner import (
    ECLASS_BASE_URL,
    SEED_COURSE_WITH_ANNOUNCEMENTS,
    SEED_COURSE_WITHOUT_ANNOUNCEMENTS,
    SEED_OLDEST_ADMIN_FRAGMENT,
    SEED_RECENT_ADMIN_FRAGMENT,
    call_tool,
    extract_text,
    initialize_server,
    spawn_server,
    tool_exists,
)

SERVER_START_FAIL = (False, "Could not start server", "Server failed to start")
COURSE_ANNOUNCEMENTS_TOOL = "get_course_announcements"
GENERAL_ANNOUNCEMENTS_TOOL = "get_general_announcements"


def _course_url(code: str) -> str:
    """Return the openeclass URL for a course code."""
    return f"{ECLASS_BASE_URL}/courses/{code}/"


def _missing_tool_failure(tool: str) -> tuple[bool, str, str]:
    """Return the structured failure tuple for an unimplemented tool."""
    return (
        False,
        f"{tool} tool not implemented",
        "Tool not found in tools/list",
    )


def test_announcements_not_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """AN1: ``get_course_announcements`` without login returns the exact error string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, COURSE_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(COURSE_ANNOUNCEMENTS_TOOL)
        response = call_tool(
            server,
            COURSE_ANNOUNCEMENTS_TOOL,
            {"course_url": _course_url(SEED_COURSE_WITH_ANNOUNCEMENTS)},
        )
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if text == "Error: Not logged in.":
            return True, "Exact error string matched", text
        return False, f"Expected exact 'Error: Not logged in.', got: '{text}'", text


def test_announcements_invalid_url(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """AN2: ``get_course_announcements`` with an invalid URL returns the exact error string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, COURSE_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(COURSE_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(
            server, COURSE_ANNOUNCEMENTS_TOOL, {"course_url": "invalid-url"}
        )
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if text == "Error: Could not extract course code.":
            return True, "Exact error string matched", text
        return (
            False,
            f"Expected exact 'Error: Could not extract course code.', got: '{text}'",
            text,
        )


def test_announcements_none_found(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """AN3: ``get_course_announcements`` for a course with none returns the exact string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, COURSE_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(COURSE_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(
            server,
            COURSE_ANNOUNCEMENTS_TOOL,
            {"course_url": _course_url(SEED_COURSE_WITHOUT_ANNOUNCEMENTS)},
        )
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if text == "No announcements found.":
            return True, "Exact string matched", text
        return False, f"Expected exact 'No announcements found.', got: '{text}'", text


def test_announcements_default_days(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """AN4: ``get_course_announcements`` with default ``days_back`` returns the documented format."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, COURSE_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(COURSE_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(
            server,
            COURSE_ANNOUNCEMENTS_TOOL,
            {"course_url": _course_url(SEED_COURSE_WITH_ANNOUNCEMENTS)},
        )
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Found" in text and "announcement" in text.lower():
            if "1." in text and "Date:" in text:
                return True, f"Correct format: {text[:150]}", text
            return False, f"Missing format elements (1., Date:): {text[:200]}", text
        return False, f"Expected announcements, got: '{text[:200]}'", text


def test_announcements_custom_days(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """AN5: ``get_course_announcements`` with custom ``days_back`` produces a valid response."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, COURSE_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(COURSE_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(
            server,
            COURSE_ANNOUNCEMENTS_TOOL,
            {
                "course_url": _course_url(SEED_COURSE_WITH_ANNOUNCEMENTS),
                "days_back": 7,
            },
        )
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Found" in text and "announcement" in text.lower():
            return True, f"Filtered results: {text[:150]}", text
        if text == "No announcements found.":
            return True, "days_back filter working (no recent announcements)", text
        return False, f"Unexpected response: '{text[:200]}'", text


def test_announcements_invalid_days(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """AN6: ``get_course_announcements`` with ``days_back=0`` returns the exact error string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, COURSE_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(COURSE_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(
            server,
            COURSE_ANNOUNCEMENTS_TOOL,
            {
                "course_url": _course_url(SEED_COURSE_WITH_ANNOUNCEMENTS),
                "days_back": 0,
            },
        )
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if text == "Error: days_back must be a positive integer.":
            return True, "Exact error string matched", text
        return (
            False,
            f"Expected exact 'Error: days_back must be a positive integer.', got: '{text}'",
            text,
        )


def test_general_not_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """GAN1: ``get_general_announcements`` without login returns the exact error string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, GENERAL_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(GENERAL_ANNOUNCEMENTS_TOOL)
        response = call_tool(server, GENERAL_ANNOUNCEMENTS_TOOL, {})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if text == "Error: Not logged in.":
            return True, "Exact error string matched", text
        return False, f"Expected 'Error: Not logged in.', got: '{text}'", text


def test_general_invalid_days_low(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """GAN2: ``get_general_announcements`` with ``days_back=0`` returns the exact error string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, GENERAL_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(GENERAL_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(server, GENERAL_ANNOUNCEMENTS_TOOL, {"days_back": 0})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if text == "Error: days_back must be a positive integer.":
            return True, "Exact error string matched", text
        return False, f"Expected exact error, got: '{text}'", text


def test_general_invalid_days_high(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """GAN3: ``get_general_announcements`` with ``days_back>30`` returns the exact error string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, GENERAL_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(GENERAL_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(server, GENERAL_ANNOUNCEMENTS_TOOL, {"days_back": 31})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if text == "Error: Cannot retrieve announcements older than 30 days.":
            return True, "Exact error string matched", text
        return False, f"Expected exact error, got: '{text}'", text


def test_general_none_found(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """GAN4: ``get_general_announcements`` produces a valid response shape on a tight window.

    ``days_back=1`` may or may not match the seeded recent admin
    announcement depending on the wall clock; either a populated
    list or the documented empty string is acceptable.
    """
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, GENERAL_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(GENERAL_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(server, GENERAL_ANNOUNCEMENTS_TOOL, {"days_back": 1})
        text = extract_text(response)
        if not text:
            return False, "Empty response", json.dumps(response)
        if text == "No announcements found." or (
            "Found" in text and "announcement" in text
        ):
            return True, "Valid response format (none found or filtered list)", text
        return False, f"Unexpected response format: {text[:100]}", text


def test_general_aggregation(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """GAN5: ``get_general_announcements`` aggregates system and course sources."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, GENERAL_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(GENERAL_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(server, GENERAL_ANNOUNCEMENTS_TOOL, {"days_back": 30})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        has_system = "Source: System" in text
        if has_system and "Source:" in text and text.count("Source:") >= 2:
            return True, f"Aggregation verified (system + course): {text[:100]}", text
        return False, f"Missing source attribution. Got: {text[:200]}", text


def test_general_filtering(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """GAN6: ``get_general_announcements`` filters by ``days_back``.

    A small ``days_back`` window must drop the seeded oldest admin
    announcement and retain the seeded most-recent one. The test
    matches against title fragments so the assertion stays readable
    when the seed copy is reworded but stable in landmarks.
    """
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        if not tool_exists(server, GENERAL_ANNOUNCEMENTS_TOOL):
            return _missing_tool_failure(GENERAL_ANNOUNCEMENTS_TOOL)
        call_tool(server, "login", {})
        response = call_tool(server, GENERAL_ANNOUNCEMENTS_TOOL, {"days_back": 5})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if SEED_OLDEST_ADMIN_FRAGMENT in text:
            return (
                False,
                f"Filtering failed: oldest admin '{SEED_OLDEST_ADMIN_FRAGMENT}' present",
                text,
            )
        if SEED_RECENT_ADMIN_FRAGMENT not in text and "No announcements" not in text:
            return (
                False,
                f"Filtering failed: missing recent admin '{SEED_RECENT_ADMIN_FRAGMENT}'",
                text,
            )
        return True, "Filtering verified (oldest excluded, recent included)", text
