#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Course-announcements protocol assertions (P.2.x / C.3.x).

Each function tests one rubric row against a freshly-spawned MCP server.
Principal: ``student_courses``. Return shape is always a 5-tuple
``(ok, msg, detail, leak_tuple|None, mode|None)``; ``leak_tuple`` is
``None`` when ``memcheck=False`` and ``mode`` is the ``matching``
mode the row was accepted under (``None`` for a failed match).

Leak-verdict pattern: functional result is saved inside the ``with``
block; :func:`leak_after` is called after the block exits so
``stop()`` has set ``_proc_exit_code`` before ``leak_verdict`` reads it.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from ..seed import SEED, course_announcements_in_window, user
from ._assertion_support import (
    HANDSHAKE_FAIL,
    LOGIN_FAIL,
    Result5,
    SERVER_START_FAIL,
    TOOL_FAIL,
    leak_after,
)
from .expected import (
    ERR_BAD_COURSE_URL,
    ERR_NEGATIVE_DAYS_BACK,
    ERR_NOT_LOGGED_IN,
    NO_ANNOUNCEMENTS,
    course_entries,
    course_response,
    course_url,
)
from .announcement_matching import match_announcements
from .matching import match_exact
from .runner import (
    ServerProcess,
    call_tool,
    extract_text,
    initialize_server,
    spawn_server,
)

_PRINCIPAL = user(SEED, "student_courses")
TOOL_NAME = "get_course_announcements"


def _creds() -> dict[str, str]:
    """Return credential env_overrides for the student_courses principal."""
    return {"ECLASS_USERNAME": _PRINCIPAL.username,
            "ECLASS_PASSWORD": _PRINCIPAL.password}


def test_course_not_logged_in(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.2.1 / C.3.1: tool without login returns the not-logged-in error."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(impl, eclass_dir, mock_root, debug, memcheck=memcheck) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                tool_resp = call_tool(server, TOOL_NAME,
                                      {"course_url": course_url("CS101")})
                if tool_resp is None:
                    ok, msg, detail = TOOL_FAIL
                else:
                    text = extract_text(tool_resp)
                    mode = match_exact(text, ERR_NOT_LOGGED_IN)
                    ok = mode is not None
                    msg = "exact not-logged-in error matched" if ok else (
                        f"expected {ERR_NOT_LOGGED_IN!r}, got {text!r}"
                    )
                    detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_course_bad_url(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.2.2 / C.3.2: unparseable course_url returns the extract-code error."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                login_resp = call_tool(server, "login", {})
                if login_resp is None:
                    ok, msg, detail = LOGIN_FAIL
                else:
                    tool_resp = call_tool(server, TOOL_NAME,
                                          {"course_url": "not-a-valid-url"})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_exact(text, ERR_BAD_COURSE_URL)
                        ok = mode is not None
                        msg = "exact extract-code error matched" if ok else (
                            f"expected {ERR_BAD_COURSE_URL!r}, got {text!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_course_negative_days(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.2.3 / C.3.3: days_back=-1 returns the non-negative-integer error."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                login_resp = call_tool(server, "login", {})
                if login_resp is None:
                    ok, msg, detail = LOGIN_FAIL
                else:
                    tool_resp = call_tool(server, TOOL_NAME, {
                        "course_url": course_url("PHYS150"), "days_back": -1,
                    })
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_exact(text, ERR_NEGATIVE_DAYS_BACK)
                        ok = mode is not None
                        msg = "exact negative-days error matched" if ok else (
                            f"expected {ERR_NEGATIVE_DAYS_BACK!r}, got {text!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_course_empty_window(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.2.4 / C.3.4: MATH201 at default window returns the empty-window string.

    MATH201's only announcement is at 45 days; the default 30-day
    window excludes it, exercising the window filter rather than a
    zero-announcement course.
    """
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                login_resp = call_tool(server, "login", {})
                if login_resp is None:
                    ok, msg, detail = LOGIN_FAIL
                else:
                    tool_resp = call_tool(server, TOOL_NAME,
                                          {"course_url": course_url("MATH201")})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_exact(text, NO_ANNOUNCEMENTS)
                        ok = mode is not None
                        msg = "exact empty-window string matched" if ok else (
                            f"expected {NO_ANNOUNCEMENTS!r}, got {text!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_course_days_zero(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.2.5 / C.3.5: CS101 with days_back=0 returns the single relative-date item."""
    assert instant is not None, "instant is required for this row"
    anns = course_announcements_in_window(SEED, "CS101", 0)
    expected = course_response(instant, anns)
    expected_entries = course_entries(instant, anns)
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                login_resp = call_tool(server, "login", {})
                if login_resp is None:
                    ok, msg, detail = LOGIN_FAIL
                else:
                    tool_resp = call_tool(server, TOOL_NAME, {
                        "course_url": course_url("CS101"), "days_back": 0,
                    })
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_announcements(text, expected, expected_entries, len(anns), instant)
                        ok = mode is not None
                        msg = "relative-date announcement response accepted" if ok else (
                            f"expected constructed response, got {text[:200]!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_course_zero_absolute(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.2.6 / C.3.6: PHYS150 with days_back=0 returns the empty-window string.

    Distinguishes ``days_back=0`` honoured as a true zero window from
    the window-filter case (P.2.4/C.3.4). PHYS150 has absolute items
    at 2/8/30/31 days; none are within the zero window.
    """
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                login_resp = call_tool(server, "login", {})
                if login_resp is None:
                    ok, msg, detail = LOGIN_FAIL
                else:
                    tool_resp = call_tool(server, TOOL_NAME, {
                        "course_url": course_url("PHYS150"), "days_back": 0,
                    })
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_exact(text, NO_ANNOUNCEMENTS)
                        ok = mode is not None
                        msg = "exact empty-window string matched (days_back=0 honoured)" if ok else (
                            f"expected {NO_ANNOUNCEMENTS!r}, got {text!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_course_default(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.2.7 / C.3.7: PHYS150 with days_back omitted returns the default-window response.

    Default window = 30; PHYS150 has items at 2, 8, 30 (in), 31 (out).
    Returns 3 items newest-first with absolute date strings.
    """
    assert instant is not None, "instant is required for this row"
    anns = course_announcements_in_window(SEED, "PHYS150", 30)
    expected = course_response(instant, anns)
    expected_entries = course_entries(instant, anns)
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                login_resp = call_tool(server, "login", {})
                if login_resp is None:
                    ok, msg, detail = LOGIN_FAIL
                else:
                    tool_resp = call_tool(server, TOOL_NAME,
                                          {"course_url": course_url("PHYS150")})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_announcements(text, expected, expected_entries, len(anns), instant)
                        ok = mode is not None
                        msg = "default-window announcement response accepted (3 items)" if ok else (
                            f"expected constructed response, got {text[:200]!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_course_days_10(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.2.8 / C.3.8: PHYS150 with days_back=10 returns 2 in-scope items."""
    assert instant is not None, "instant is required for this row"
    anns = course_announcements_in_window(SEED, "PHYS150", 10)
    expected = course_response(instant, anns)
    expected_entries = course_entries(instant, anns)
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                login_resp = call_tool(server, "login", {})
                if login_resp is None:
                    ok, msg, detail = LOGIN_FAIL
                else:
                    tool_resp = call_tool(server, TOOL_NAME, {
                        "course_url": course_url("PHYS150"), "days_back": 10,
                    })
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_announcements(text, expected, expected_entries, len(anns), instant)
                        ok = mode is not None
                        msg = "days_back=10 announcement response accepted (2 items)" if ok else (
                            f"expected constructed response, got {text[:200]!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_course_days_40(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.2.9 / C.3.9: PHYS150 with days_back=40 returns all 4 items.

    Verifies that ``days_back`` above 30 is accepted and widens the
    window without a ``[0,30]`` cap (unlike the general tool).
    """
    assert instant is not None, "instant is required for this row"
    anns = course_announcements_in_window(SEED, "PHYS150", 40)
    expected = course_response(instant, anns)
    expected_entries = course_entries(instant, anns)
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                login_resp = call_tool(server, "login", {})
                if login_resp is None:
                    ok, msg, detail = LOGIN_FAIL
                else:
                    tool_resp = call_tool(server, TOOL_NAME, {
                        "course_url": course_url("PHYS150"), "days_back": 40,
                    })
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_announcements(text, expected, expected_entries, len(anns), instant)
                        ok = mode is not None
                        msg = "days_back=40 announcement response accepted (4 items)" if ok else (
                            f"expected constructed response, got {text[:200]!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode
