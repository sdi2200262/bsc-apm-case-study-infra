#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Baseline-tier protocol assertions (P.1.x / C.2.x).

Each function tests one rubric row against a freshly-spawned MCP server.
Principal: ``student_courses``. All return a 5-tuple
``(ok, msg, detail, leak_tuple|None, mode|None)`` where
``leak_tuple`` is ``(clean, detail)`` from
``ServerProcess.leak_verdict``, or ``None`` when ``memcheck=False``,
and ``mode`` is the ``matching`` mode the row was accepted under
(``None`` for a failed match or a non-string-matched row).

Leak-verdict pattern: functional result is saved inside the ``with``
block; ``leak_after()`` is called after the block exits so
``stop()`` has set ``_proc_exit_code`` before ``leak_verdict`` reads it.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..provision import blank_dotenv_credentials, write_dotenv
from ..seed import SEED, enrolled_courses, user

from ._assertion_support import (
    Result5,
    SERVER_START_FAIL,
    leak_after,
)
from .expected import ERR_NOT_LOGGED_IN, login_success
from .matching import (
    match_exact,
    match_get_courses,
    match_initialize,
    match_tools_list,
)
from .runner import (
    CLIENT_NAME,
    CLIENT_VERSION,
    PROTOCOL_VERSION,
    ServerProcess,
    call_tool,
    extract_text,
    initialize_server,
    spawn_server,
)

# Two-principal seed; baseline suite runs as student_courses.
_PRINCIPAL = user(SEED, "student_courses")
_COURSES = enrolled_courses(SEED, "student_courses")

LOGIN_SUCCESS = login_success(_PRINCIPAL.username)
LOGIN_ALREADY = f"Already logged in as {_PRINCIPAL.username}"
LOGIN_MISSING_CREDS = (
    "Error: Username and password must be provided in the .env file. "
    "Please set ECLASS_USERNAME and ECLASS_PASSWORD in your .env file."
)
LOGOUT_SUCCESS = f"Successfully logged out user {_PRINCIPAL.username}."
LOGOUT_NO_OP = "Not logged in, nothing to do."
AUTHSTATUS_LOGGED_IN = f"Status: Logged in as {_PRINCIPAL.username}"
AUTHSTATUS_NOT_LOGGED_IN = "Status: Not logged in"

def _creds() -> dict[str, str]:
    """Return credential env_overrides for the student_courses principal."""
    return {"ECLASS_USERNAME": _PRINCIPAL.username,
            "ECLASS_PASSWORD": _PRINCIPAL.password}


def test_tools_list(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.1 / C.2.2: tools/list matches the constructed expected tool list.

    Both implementations are held to the same byte-exact six-object
    contract (``name``, ``description``, ``inputSchema``) against the
    constructed expected values, so a server whose tool schemas
    serialise differently fails this row. This row records no string
    mode.
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
            initialize_server(server)
            raw = server.send_request({
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
            })
            detail = json.dumps(raw)
            result = raw.get("result") if raw else None
            tools = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(tools, list):
                ok = False
                msg = "tools/list: invalid or missing tools array"
            else:
                ok, msg = match_tools_list(tools)
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_authstatus_pre_login(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.2 / C.2.3: authstatus before any login returns the not-logged-in string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            initialize_server(server)
            text = extract_text(call_tool(server, "authstatus", {}))
            mode = match_exact(text, AUTHSTATUS_NOT_LOGGED_IN)
            ok = mode is not None
            msg = "exact not-logged-in status matched" if ok else (
                f"expected {AUTHSTATUS_NOT_LOGGED_IN!r}, got {text!r}"
            )
            detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_login_success(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.3 / C.2.4: login with valid credentials returns the success string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            initialize_server(server)
            text = extract_text(call_tool(server, "login", {}))
            mode = match_exact(text, LOGIN_SUCCESS)
            ok = mode is not None
            msg = "exact login success string matched" if ok else (
                f"expected {LOGIN_SUCCESS!r}, got {text!r}"
            )
            detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_authstatus_post_login(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.4 / C.2.5: authstatus after login returns the logged-in string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            initialize_server(server)
            call_tool(server, "login", {})
            text = extract_text(call_tool(server, "authstatus", {}))
            mode = match_exact(text, AUTHSTATUS_LOGGED_IN)
            ok = mode is not None
            msg = "exact logged-in status matched" if ok else (
                f"expected {AUTHSTATUS_LOGGED_IN!r}, got {text!r}"
            )
            detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_login_already(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.5 / C.2.6: second login while authenticated returns the already string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            initialize_server(server)
            call_tool(server, "login", {})
            text = extract_text(call_tool(server, "login", {}))
            mode = match_exact(text, LOGIN_ALREADY)
            ok = mode is not None
            msg = "exact already-logged-in string matched" if ok else (
                f"expected {LOGIN_ALREADY!r}, got {text!r}"
            )
            detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_missing_credentials(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.6 / C.2.7: login with both credential surfaces deprived.

    Blanks both the env-var surface (empty ``ECLASS_USERNAME`` /
    ``ECLASS_PASSWORD``) and the on-disk ``.env``; restores the
    verbatim ``.env`` in ``finally``.
    """
    blank_dotenv_credentials(eclass_dir)
    overrides = {"ECLASS_USERNAME": "", "ECLASS_PASSWORD": ""}
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    try:
        with spawn_server(
            impl, eclass_dir, mock_root, debug,
            env_overrides=overrides, memcheck=memcheck,
        ) as server:
            srv = server
            if server is not None:
                initialize_server(server)
                text = extract_text(call_tool(server, "login", {}))
                mode = match_exact(text, LOGIN_MISSING_CREDS)
                ok = mode is not None
                msg = "exact missing-credentials string matched" if ok else (
                    f"expected missing-credentials error, got {text!r}"
                )
                detail = text
    finally:
        write_dotenv(eclass_dir, mock_root)
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_get_courses_logged_in(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.7 / C.2.8: get_courses while logged in returns an accepted form.

    The Python reference must emit the openeclass-formatted course list;
    the C replica may emit that or the documented-clean layout. The
    accept-set is the matcher's concern; this row records which
    accepted layout matched as its diagnostic.
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
            initialize_server(server)
            call_tool(server, "login", {})
            text = extract_text(call_tool(server, "get_courses", {}))
            mode = match_get_courses(
                text, _COURSES, allow_documented_clean=(impl == "c"),
            )
            ok = mode is not None
            msg = "get_courses response accepted" if ok else (
                f"get_courses did not match an accepted form; "
                f"got {text[:200]!r}"
            )
            detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_logout_success(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.8 / C.2.9: logout while authenticated returns the success string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            initialize_server(server)
            call_tool(server, "login", {})
            text = extract_text(call_tool(server, "logout", {}))
            mode = match_exact(text, LOGOUT_SUCCESS)
            ok = mode is not None
            msg = "exact logout success string matched" if ok else (
                f"expected {LOGOUT_SUCCESS!r}, got {text!r}"
            )
            detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_authstatus_post_logout(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.9 / C.2.10: authstatus after logout returns the not-logged-in string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            initialize_server(server)
            call_tool(server, "login", {})
            call_tool(server, "logout", {})
            text = extract_text(call_tool(server, "authstatus", {}))
            mode = match_exact(text, AUTHSTATUS_NOT_LOGGED_IN)
            ok = mode is not None
            msg = "exact not-logged-in status after logout matched" if ok else (
                f"expected {AUTHSTATUS_NOT_LOGGED_IN!r}, got {text!r}"
            )
            detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_get_courses_not_logged_in(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.10 / C.2.11: get_courses without login returns the not-logged-in error."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            initialize_server(server)
            text = extract_text(call_tool(server, "get_courses", {}))
            mode = match_exact(text, ERR_NOT_LOGGED_IN)
            ok = mode is not None
            msg = "exact not-logged-in error matched" if ok else (
                f"expected {ERR_NOT_LOGGED_IN!r}, got {text!r}"
            )
            detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_logout_no_op(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.11 / C.2.12: logout without a prior login returns the no-op string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            initialize_server(server)
            text = extract_text(call_tool(server, "logout", {}))
            mode = match_exact(text, LOGOUT_NO_OP)
            ok = mode is not None
            msg = "exact logout no-op string matched" if ok else (
                f"expected {LOGOUT_NO_OP!r}, got {text!r}"
            )
            detail = text
    return ok, msg, detail, leak_after(srv, memcheck), mode


def test_initialize_frame(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """C.2.1 only: the hand-written initialize frame against the expected response.

    Asserts the C replica's ``protocolVersion`` and ``serverInfo``
    equal the invariant constructed constants and its
    ``capabilities`` object is one of the two accepted constructed
    forms (see :mod:`.expected`). The matched form, recorded as the
    row's diagnostic, is ``capabilities-library`` or
    ``capabilities-doc``. The expected response is constructed, never captured
    from the submission. C-only: a non-C implementation does not
    apply.
    """
    if impl != "c":
        reason = "C.2.1 applies to the C replica only"
        return False, reason, reason, None, None
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    with spawn_server(
        impl, eclass_dir, mock_root, debug,
        env_overrides=_creds(), memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            raw = server.send_request({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": CLIENT_NAME, "version": CLIENT_VERSION,
                    },
                },
            })
            result = raw.get("result") if raw else None
            detail = json.dumps(raw)
            if result is None:
                ok, msg = False, "initialize: no result field"
            else:
                mode = match_initialize(result)
                ok = mode is not None
                msg = (
                    f"initialize frame accepted ({mode})"
                ) if ok else (
                    "initialize frame matched neither accepted "
                    f"capability form: got {result!r}"
                )
    return ok, msg, detail, leak_after(srv, memcheck), mode
