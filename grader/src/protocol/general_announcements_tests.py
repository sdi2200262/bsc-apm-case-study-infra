#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
General-announcements protocol assertions (P.3.x / C.4.x).

Principal: ``student_general`` (enrolled in BIO110 only). Each
function accepts an optional ``instant`` (per-run seed-apply
timestamp) and ``memcheck``. Return shape is a 5-tuple
``(ok, msg, detail, leak_tuple|None, mode|None)`` following the
same convention as ``course_announcements_tests``.

Leak-verdict pattern: functional result is saved inside the ``with``
block; :func:`leak_after` is called after the block exits so
``stop()`` has set ``_proc_exit_code`` before ``leak_verdict`` reads it.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from ..seed import SEED, general_announcements_in_window, user
from ._assertion_support import (
    HANDSHAKE_FAIL,
    LOGIN_FAIL,
    Result5,
    SERVER_START_FAIL,
    TOOL_FAIL,
    leak_after,
)
from .expected import (
    ERR_GENERAL_UPPER_BOUND,
    ERR_NEGATIVE_DAYS_BACK,
    ERR_NOT_LOGGED_IN,
    NO_ANNOUNCEMENTS,
    general_entries,
    general_response,
)
from .matching import match_announcements, match_exact
from .runner import ServerProcess, call_tool, extract_text, initialize_server, spawn_server

_PRINCIPAL = user(SEED, "student_general")
TOOL_NAME = "get_general_announcements"


def _creds() -> dict[str, str]:
    """Return credential env_overrides for the student_general principal."""
    return {"ECLASS_USERNAME": _PRINCIPAL.username,
            "ECLASS_PASSWORD": _PRINCIPAL.password}


def test_general_not_logged_in(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.3.1 / C.4.1: tool without login returns the not-logged-in error."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(impl, eclass_dir, mock_root, debug, memcheck=memcheck) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                tool_resp = call_tool(server, TOOL_NAME, {})
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


def test_general_negative_days(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.3.2 / C.4.2: days_back=-1 returns the non-negative-integer error."""
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
                    tool_resp = call_tool(server, TOOL_NAME, {"days_back": -1})
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


def test_general_over_thirty(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.3.3 / C.4.3: days_back=31 returns the upper-bound error."""
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
                    tool_resp = call_tool(server, TOOL_NAME, {"days_back": 31})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_exact(text, ERR_GENERAL_UPPER_BOUND)
                        ok = mode is not None
                        msg = "exact upper-bound error matched" if ok else (
                            f"expected {ERR_GENERAL_UPPER_BOUND!r}, got {text!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_general_days_zero(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.3.4 / C.4.4: days_back=0 returns the empty-window string."""
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
                    tool_resp = call_tool(server, TOOL_NAME, {"days_back": 0})
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


def test_general_days_5(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.3.5 / C.4.5: days_back=5 returns 1 item (BIO110 a1 at 3d)."""
    assert instant is not None, "instant is required for this row"
    anns = general_announcements_in_window(SEED, "student_general", 5)
    expected = general_response(instant, anns)
    expected_entries = general_entries(instant, anns)
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
                    tool_resp = call_tool(server, TOOL_NAME, {"days_back": 5})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_announcements(text, expected, expected_entries, len(anns), instant)
                        ok = mode is not None
                        msg = "days_back=5 announcement response accepted (1 item)" if ok else (
                            f"expected constructed response, got {text[:200]!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_general_days_8(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.3.6 / C.4.6: days_back=8 returns 2 items (BIO110 a1, SYS1).

    Exercises the union of enrolled-course and system announcements
    with both Source forms in one response.
    """
    assert instant is not None, "instant is required for this row"
    anns = general_announcements_in_window(SEED, "student_general", 8)
    expected = general_response(instant, anns)
    expected_entries = general_entries(instant, anns)
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
                    tool_resp = call_tool(server, TOOL_NAME, {"days_back": 8})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_announcements(text, expected, expected_entries, len(anns), instant)
                        ok = mode is not None
                        msg = "days_back=8 union announcement response accepted (2 items)" if ok else (
                            f"expected constructed response, got {text[:200]!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_general_default(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    instant: datetime.datetime | None = None,
    memcheck: bool = False,
) -> Result5:
    """P.3.7 / C.4.7: days_back omitted returns the default-window response.

    Default = 30; student_general sees BIO110 a1 (3d), SYS1 (7d),
    BIO110 a2 (10d), SYS2 (20d): 4 items alternating source.
    """
    assert instant is not None, "instant is required for this row"
    anns = general_announcements_in_window(SEED, "student_general", 30)
    expected = general_response(instant, anns)
    expected_entries = general_entries(instant, anns)
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
                    tool_resp = call_tool(server, TOOL_NAME, {})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_announcements(text, expected, expected_entries, len(anns), instant)
                        ok = mode is not None
                        msg = "default-window announcement response accepted (4 items)" if ok else (
                            f"expected constructed response, got {text[:200]!r}"
                        )
                        detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode
