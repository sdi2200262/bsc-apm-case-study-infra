#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Baseline-tier protocol assertions.

Each function tests one P.1 / C.2 row from the rubric against a
freshly-spawned MCP server. The functions are implementation-
agnostic: each takes ``impl`` as the first parameter and the
runner's ``spawn_server`` decides whether to start the Python
reference or the C replica. The Python and C aggregators tag the
same function with the test id appropriate to the implementation.

Strict equality is asserted wherever the response text is
deterministic against the seeded environment. The seeded
``get_courses`` preamble carries the count of enrolled courses
read from the loaded seed.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..seed import SEED
from .runner import (
    call_tool,
    extract_text,
    initialize_server,
    spawn_server,
)

ALL_TOOL_NAMES: frozenset[str] = frozenset({
    "login",
    "logout",
    "get_courses",
    "authstatus",
    "get_course_announcements",
    "get_general_announcements",
})

GET_COURSES_PREAMBLE = f"Found {len(SEED.enrolled_course_codes)} courses:"

LOGIN_SUCCESS = f"Login successful! You are now logged in as {SEED.username}."
LOGIN_ALREADY = f"Already logged in as {SEED.username}"
LOGIN_MISSING_CREDS = (
    "Error: Username and password must be provided in the .env file. "
    "Please set ECLASS_USERNAME and ECLASS_PASSWORD in your .env file."
)
LOGOUT_SUCCESS = f"Successfully logged out user {SEED.username}."
LOGOUT_NO_OP = "Not logged in, nothing to do."
COURSES_NOT_LOGGED_IN = "Error: Not logged in. Please log in first using the login tool."
AUTHSTATUS_LOGGED_IN = f"Status: Logged in as {SEED.username}"
AUTHSTATUS_NOT_LOGGED_IN = "Status: Not logged in"

SERVER_START_FAIL = (False, "Could not start server", "Server failed to start")


def test_initialize_and_tools_list(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.1 / C.2.1: ``initialize`` shape and ``tools/list`` carry all six tools."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        init_response = server.send_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "grader", "version": "1.0.0"},
            },
        })
        if not init_response or "result" not in init_response:
            return False, "initialize: invalid or missing response", json.dumps(init_response)
        result = init_response["result"]
        for field in ("protocolVersion", "capabilities", "serverInfo"):
            if field not in result:
                return False, f"initialize: missing field '{field}'", json.dumps(init_response)
        server.send_notification({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        list_response = server.send_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        if not list_response or "result" not in list_response:
            return False, "tools/list: invalid or missing response", json.dumps(list_response)
        tools = list_response["result"].get("tools", [])
        names = {t.get("name") for t in tools}
        missing = ALL_TOOL_NAMES - names
        if missing:
            return False, f"tools/list: missing tools {sorted(missing)}", json.dumps(list_response)
        return True, f"initialize and tools/list expose all {len(ALL_TOOL_NAMES)} tools", json.dumps(list_response)


def test_login_success(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.2 / C.2.2: ``login`` with valid credentials returns the success string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "login", {})
        text = extract_text(response)
        if text == LOGIN_SUCCESS:
            return True, "exact login success string matched", text
        return False, f"expected exact '{LOGIN_SUCCESS}', got: '{text}'", text


def test_login_already_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.3 / C.2.3: a second ``login`` call surfaces the already-logged-in state."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        call_tool(server, "login", {})
        response = call_tool(server, "login", {})
        text = extract_text(response)
        if text == LOGIN_ALREADY:
            return True, "exact already-logged-in string matched", text
        return False, f"expected exact '{LOGIN_ALREADY}', got: '{text}'", text


def test_login_missing_credentials(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.4 / C.2.4: ``login`` with empty credentials returns the missing-creds error."""
    overrides = {"ECLASS_USERNAME": "", "ECLASS_PASSWORD": ""}
    with spawn_server(impl, eclass_dir, mock_root, debug, env_overrides=overrides) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "login", {})
        text = extract_text(response)
        if text == LOGIN_MISSING_CREDS:
            return True, "exact missing-credentials string matched", text
        return False, f"expected exact missing-credentials error, got: '{text}'", text


def test_logout_success(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.5 / C.2.5: ``logout`` after a successful login returns the success string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        call_tool(server, "login", {})
        response = call_tool(server, "logout", {})
        text = extract_text(response)
        if text == LOGOUT_SUCCESS:
            return True, "exact logout success string matched", text
        return False, f"expected exact '{LOGOUT_SUCCESS}', got: '{text}'", text


def test_logout_no_op(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.6 / C.2.6: ``logout`` without a prior login returns the no-op string."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "logout", {})
        text = extract_text(response)
        if text == LOGOUT_NO_OP:
            return True, "exact logout no-op string matched", text
        return False, f"expected exact '{LOGOUT_NO_OP}', got: '{text}'", text


def test_get_courses_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.7 / C.2.7: ``get_courses`` after login lists every enrolled course."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        call_tool(server, "login", {})
        response = call_tool(server, "get_courses", {})
        text = extract_text(response)
        if not text:
            return False, "empty or invalid response", json.dumps(response)
        if GET_COURSES_PREAMBLE not in text:
            return False, f"missing preamble '{GET_COURSES_PREAMBLE}', got: '{text[:200]}'", text
        missing = [code for code in SEED.enrolled_course_codes if code not in text]
        if missing:
            return False, f"missing enrolled course codes: {missing}", text
        return True, f"preamble and {len(SEED.enrolled_course_codes)} enrolled codes present", text


def test_get_courses_not_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.8 / C.2.8: ``get_courses`` without authentication returns the not-logged-in error."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "get_courses", {})
        text = extract_text(response)
        if text == COURSES_NOT_LOGGED_IN:
            return True, "exact not-logged-in string matched", text
        return False, f"expected exact '{COURSES_NOT_LOGGED_IN}', got: '{text}'", text


def test_authstatus_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.9 / C.2.9: ``authstatus`` after login reports the logged-in state."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        call_tool(server, "login", {})
        response = call_tool(server, "authstatus", {})
        text = extract_text(response)
        if text == AUTHSTATUS_LOGGED_IN:
            return True, "exact logged-in status matched", text
        return False, f"expected exact '{AUTHSTATUS_LOGGED_IN}', got: '{text}'", text


def test_authstatus_not_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P.1.10 / C.2.10: ``authstatus`` before login reports the not-logged-in state."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "authstatus", {})
        text = extract_text(response)
        if text == AUTHSTATUS_NOT_LOGGED_IN:
            return True, "exact not-logged-in status matched", text
        return False, f"expected exact '{AUTHSTATUS_NOT_LOGGED_IN}', got: '{text}'", text
