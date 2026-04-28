#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Baseline protocol assertions: P1, P2, L1-L3, O1-O2, C1-C2, A1.

Each function tests one rubric item against a freshly-spawned
server. Assertions are parameterised by the implementation under
test; the per-implementation aggregator modules call them with the
correct ``impl`` and tag the results with the corresponding test
identifier.
"""

from __future__ import annotations

import json
from pathlib import Path

from .runner import (
    SEED_USERNAME,
    call_tool,
    extract_text,
    initialize_server,
    spawn_server,
)

SERVER_START_FAIL = (False, "Could not start server", "Server failed to start")


def test_initialize(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P1: ``initialize`` response carries the required fields and server name."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        response = server.send_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "grader", "version": "1.0.0"},
            },
        })
        if not response or "result" not in response:
            return False, "Invalid or missing response", json.dumps(response)
        result = response["result"]
        missing = [k for k in ("protocolVersion", "capabilities", "serverInfo") if k not in result]
        if missing:
            return False, f"Missing fields: {missing}", json.dumps(response)
        server_name = result.get("serverInfo", {}).get("name", "")
        if server_name != "eclass-mcp":
            return False, f"serverInfo.name should be 'eclass-mcp', got '{server_name}'", json.dumps(response)
        return True, "Initialize response structure correct", json.dumps(response)


def test_tools_list(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """P2: ``tools/list`` registers the four required baseline tools."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = server.send_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        if not response or "result" not in response:
            return False, "Invalid or missing response", json.dumps(response)
        tools = response["result"].get("tools", [])
        names = {t.get("name") for t in tools}
        required = {"login", "logout", "get_courses", "authstatus"}
        missing = required - names
        if missing:
            return False, f"Missing required tools: {missing}", json.dumps(response)
        has_announcements = "get_course_announcements" in names
        return True, f"Found {len(tools)} tools (announcements: {has_announcements})", json.dumps(response)


def test_login_success(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """L1: ``login`` with seeded credentials reports success and the seeded username."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "login", {})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Login successful" in text and SEED_USERNAME in text:
            return True, f"Login successful: {text[:100]}", text
        return False, f"Unexpected response: {text[:200]}", text


def test_login_already_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """L2: A second ``login`` call surfaces the already-logged-in branch."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        call_tool(server, "login", {})
        response = call_tool(server, "login", {})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Already logged in" in text:
            return True, f"Already logged in detected: {text[:100]}", text
        return False, f"Expected 'Already logged in', got: {text[:200]}", text


def test_login_missing_credentials(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """L3: ``login`` with empty credentials surfaces a credentials error."""
    overrides = {"ECLASS_USERNAME": "", "ECLASS_PASSWORD": ""}
    with spawn_server(impl, eclass_dir, mock_root, debug, env_overrides=overrides) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "login", {})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Error" in text and (
            "must be provided" in text.lower()
            or "credentials" in text.lower()
            or "username" in text.lower()
        ):
            return True, f"Missing credentials error: {text[:100]}", text
        return False, f"Expected credentials error, got: {text[:200]}", text


def test_logout_success(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """O1: ``logout`` after a successful login reports success and the seeded username."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        call_tool(server, "login", {})
        response = call_tool(server, "logout", {})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Successfully logged out" in text and SEED_USERNAME in text:
            return True, f"Logout successful: {text[:100]}", text
        return False, f"Expected logout success, got: {text[:200]}", text


def test_logout_not_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """O2: ``logout`` without a prior login is a no-op with the documented message."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "logout", {})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Not logged in" in text or "nothing to do" in text.lower():
            return True, f"Not logged in response: {text[:100]}", text
        return False, f"Expected 'Not logged in', got: {text[:200]}", text


def test_courses_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """C1: ``get_courses`` after a login returns a non-empty course list."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        call_tool(server, "login", {})
        response = call_tool(server, "get_courses", {})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Found" in text and "course" in text.lower():
            return True, f"Courses found: {text[:150]}", text
        return False, f"Expected courses list, got: {text[:200]}", text


def test_courses_not_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """C2: ``get_courses`` without a login surfaces the not-logged-in error."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "get_courses", {})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Error" in text and ("Not logged in" in text or "log in" in text.lower()):
            return True, f"Not logged in error: {text[:100]}", text
        return False, f"Expected not logged in error, got: {text[:200]}", text


def test_authstatus_not_logged_in(
    impl: str, eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """A1: ``authstatus`` before login reports the not-logged-in state."""
    with spawn_server(impl, eclass_dir, mock_root, debug) as server:
        if server is None:
            return SERVER_START_FAIL
        initialize_server(server)
        response = call_tool(server, "authstatus", {})
        text = extract_text(response)
        if not text:
            return False, "Empty or invalid response", json.dumps(response)
        if "Status:" in text and "Not logged in" in text:
            return True, f"Not logged in status: {text[:100]}", text
        return False, f"Expected 'Not logged in' status, got: {text[:200]}", text
