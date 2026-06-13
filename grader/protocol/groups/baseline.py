# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Baseline protocol assertions (P.1.x / C.2.x).

Each function tests one rubric row against a freshly-spawned MCP server
as the ``student_courses`` user and returns the shared ``RowResult``
six-tuple (see ``._support`` for the tuple contract and the leak-verdict
call ordering ``leak_after`` documents).
"""

from __future__ import annotations

from pathlib import Path

from ...environment.provision import blank_dotenv_credentials, write_dotenv
from ..expected import ERR_NOT_LOGGED_IN, get_courses_forms, login_success
from ..matching import (
    match_exact,
    match_get_courses,
    match_missing_credentials,
)
from ..runner import (
    ServerProcess,
    call_tool,
    extract_text,
    initialize_server,
    spawn_server,
)
from ..seed import SEED, enrolled_courses, user
from ..similarity import similarity_ratio
from ._support import (
    HANDSHAKE_FAIL,
    LOGIN_FAIL,
    SERVER_START_FAIL,
    TOOL_FAIL,
    RowResult,
    leak_after,
)

# Two-user seed; baseline suite runs as student_courses.
_USER = user(SEED, "student_courses")
_COURSES = enrolled_courses(SEED, "student_courses")

LOGIN_SUCCESS = login_success(_USER.username)
LOGIN_ALREADY = f"Already logged in as {_USER.username}"
LOGIN_MISSING_CREDS = (
    "Error: Username and password must be provided in the .env file. "
    "Please set ECLASS_USERNAME and ECLASS_PASSWORD in your .env file."
)
LOGIN_MISSING_CREDS_DOCUMENTED = "Error: Username and password must be provided in the .env file"
LOGOUT_SUCCESS = f"Successfully logged out user {_USER.username}."
LOGOUT_NO_OP = "Not logged in, nothing to do."
AUTHSTATUS_LOGGED_IN = f"Status: Logged in as {_USER.username}"
AUTHSTATUS_NOT_LOGGED_IN = "Status: Not logged in"


def check_authstatus_pre_login(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.2 / C.2.3: authstatus before any login returns the not-logged-in string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    with spawn_server(
        impl,
        eclass_dir,
        mock_root,
        debug,
        env_overrides=_creds(),
        memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                tool_resp = call_tool(server, "authstatus", {})
                if tool_resp is None:
                    ok, msg, detail = TOOL_FAIL
                else:
                    text = extract_text(tool_resp)
                    mode = match_exact(text, AUTHSTATUS_NOT_LOGGED_IN)
                    ok = mode is not None
                    msg = (
                        "exact not-logged-in status matched"
                        if ok
                        else (f"expected {AUTHSTATUS_NOT_LOGGED_IN!r}, got {text!r}")
                    )
                    detail = text
                    similarity = similarity_ratio(text, [AUTHSTATUS_NOT_LOGGED_IN])
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def check_login_success(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.3 / C.2.4: login with valid credentials returns the success string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    with spawn_server(
        impl,
        eclass_dir,
        mock_root,
        debug,
        env_overrides=_creds(),
        memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                tool_resp = call_tool(server, "login", {})
                if tool_resp is None:
                    ok, msg, detail = TOOL_FAIL
                else:
                    text = extract_text(tool_resp)
                    mode = match_exact(text, LOGIN_SUCCESS)
                    ok = mode is not None
                    msg = (
                        "exact login success string matched"
                        if ok
                        else (f"expected {LOGIN_SUCCESS!r}, got {text!r}")
                    )
                    detail = text
                    similarity = similarity_ratio(text, [LOGIN_SUCCESS])
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def check_authstatus_post_login(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.4 / C.2.5: authstatus after login returns the logged-in string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    with spawn_server(
        impl,
        eclass_dir,
        mock_root,
        debug,
        env_overrides=_creds(),
        memcheck=memcheck,
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
                    tool_resp = call_tool(server, "authstatus", {})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_exact(text, AUTHSTATUS_LOGGED_IN)
                        ok = mode is not None
                        msg = (
                            "exact logged-in status matched"
                            if ok
                            else (f"expected {AUTHSTATUS_LOGGED_IN!r}, got {text!r}")
                        )
                        detail = text
                        similarity = similarity_ratio(text, [AUTHSTATUS_LOGGED_IN])
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def check_login_already(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.5 / C.2.6: second login while authenticated returns the already string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    with spawn_server(
        impl,
        eclass_dir,
        mock_root,
        debug,
        env_overrides=_creds(),
        memcheck=memcheck,
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
                    tool_resp = call_tool(server, "login", {})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_exact(text, LOGIN_ALREADY)
                        ok = mode is not None
                        msg = (
                            "exact already-logged-in string matched"
                            if ok
                            else (f"expected {LOGIN_ALREADY!r}, got {text!r}")
                        )
                        detail = text
                        similarity = similarity_ratio(text, [LOGIN_ALREADY])
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def check_missing_credentials(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.6 / C.2.7: login with both credential surfaces deprived.

    Blanks both the env-var surface (empty ``ECLASS_USERNAME`` /
    ``ECLASS_PASSWORD``) and the on-disk ``.env``; restores the
    verbatim ``.env`` in ``finally``. The two accepted error forms are
    ``matching.match_missing_credentials``'s contract; the documented
    one-sentence form is allowed only for the C replica
    (``allow_documented=(impl == "c")``), because the Python reference
    emits the two-sentence form verbatim and has no excuse for the
    shorter one.
    """
    blank_dotenv_credentials(eclass_dir)
    overrides = {"ECLASS_USERNAME": "", "ECLASS_PASSWORD": ""}
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    try:
        with spawn_server(
            impl,
            eclass_dir,
            mock_root,
            debug,
            env_overrides=overrides,
            memcheck=memcheck,
        ) as server:
            srv = server
            if server is not None:
                if not initialize_server(server):
                    ok, msg, detail = HANDSHAKE_FAIL
                else:
                    tool_resp = call_tool(server, "login", {})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_missing_credentials(
                            text,
                            LOGIN_MISSING_CREDS,
                            LOGIN_MISSING_CREDS_DOCUMENTED,
                            allow_documented=(impl == "c"),
                        )
                        ok = mode is not None
                        msg = (
                            "missing-credentials response accepted"
                            if ok
                            else (f"expected missing-credentials error, got {text!r}")
                        )
                        detail = text
                        similarity = similarity_ratio(
                            text, [LOGIN_MISSING_CREDS, LOGIN_MISSING_CREDS_DOCUMENTED]
                        )
    finally:
        write_dotenv(eclass_dir, mock_root)
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def check_get_courses_logged_in(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.7 / C.2.8: get_courses while logged in returns an accepted form.

    The Python reference must emit the openeclass-formatted course list;
    the C replica may emit that or the documented-clean layout. The
    accept-set is the matcher's concern; this row records which
    accepted layout matched as its diagnostic.
    """
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    with spawn_server(
        impl,
        eclass_dir,
        mock_root,
        debug,
        env_overrides=_creds(),
        memcheck=memcheck,
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
                    tool_resp = call_tool(server, "get_courses", {})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_get_courses(
                            text,
                            _COURSES,
                            allow_documented_clean=(impl == "c"),
                        )
                        ok = mode is not None
                        msg = (
                            "get_courses response accepted"
                            if ok
                            else (f"get_courses did not match an accepted form; got {text[:200]!r}")
                        )
                        detail = text
                        # Gate the similarity candidates to the row's accepted
                        # forms, mirroring the matcher's
                        # allow_documented_clean=(impl == "c") above: the C
                        # replica accepts both forms, the Python reference only
                        # the faithful one, so a failing Python row must not draw
                        # similarity from the documented-clean form it cannot pass.
                        accepted_forms = get_courses_forms(_COURSES)
                        if impl != "c":
                            accepted_forms = accepted_forms[:1]
                        similarity = similarity_ratio(text, accepted_forms)
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def check_logout_success(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.8 / C.2.9: logout while authenticated returns the success string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    with spawn_server(
        impl,
        eclass_dir,
        mock_root,
        debug,
        env_overrides=_creds(),
        memcheck=memcheck,
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
                    tool_resp = call_tool(server, "logout", {})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_exact(text, LOGOUT_SUCCESS)
                        ok = mode is not None
                        msg = (
                            "exact logout success string matched"
                            if ok
                            else (f"expected {LOGOUT_SUCCESS!r}, got {text!r}")
                        )
                        detail = text
                        similarity = similarity_ratio(text, [LOGOUT_SUCCESS])
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def check_authstatus_post_logout(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.9 / C.2.10: authstatus after logout returns the not-logged-in string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    with spawn_server(
        impl,
        eclass_dir,
        mock_root,
        debug,
        env_overrides=_creds(),
        memcheck=memcheck,
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
                    call_tool(server, "logout", {})
                    tool_resp = call_tool(server, "authstatus", {})
                    if tool_resp is None:
                        ok, msg, detail = TOOL_FAIL
                    else:
                        text = extract_text(tool_resp)
                        mode = match_exact(text, AUTHSTATUS_NOT_LOGGED_IN)
                        ok = mode is not None
                        msg = (
                            "exact not-logged-in status after logout matched"
                            if ok
                            else (f"expected {AUTHSTATUS_NOT_LOGGED_IN!r}, got {text!r}")
                        )
                        detail = text
                        similarity = similarity_ratio(text, [AUTHSTATUS_NOT_LOGGED_IN])
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def check_get_courses_not_logged_in(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.10 / C.2.11: get_courses without login returns the not-logged-in error."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    with spawn_server(
        impl,
        eclass_dir,
        mock_root,
        debug,
        env_overrides=_creds(),
        memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                tool_resp = call_tool(server, "get_courses", {})
                if tool_resp is None:
                    ok, msg, detail = TOOL_FAIL
                else:
                    text = extract_text(tool_resp)
                    mode = match_exact(text, ERR_NOT_LOGGED_IN)
                    ok = mode is not None
                    msg = (
                        "exact not-logged-in error matched"
                        if ok
                        else (f"expected {ERR_NOT_LOGGED_IN!r}, got {text!r}")
                    )
                    detail = text
                    similarity = similarity_ratio(text, [ERR_NOT_LOGGED_IN])
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def check_logout_no_op(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> RowResult:
    """P.1.11 / C.2.12: logout without a prior login returns the no-op string."""
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
    similarity: float | None = None
    with spawn_server(
        impl,
        eclass_dir,
        mock_root,
        debug,
        env_overrides=_creds(),
        memcheck=memcheck,
    ) as server:
        srv = server
        if server is not None:
            if not initialize_server(server):
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                tool_resp = call_tool(server, "logout", {})
                if tool_resp is None:
                    ok, msg, detail = TOOL_FAIL
                else:
                    text = extract_text(tool_resp)
                    mode = match_exact(text, LOGOUT_NO_OP)
                    ok = mode is not None
                    msg = (
                        "exact logout no-op string matched"
                        if ok
                        else (f"expected {LOGOUT_NO_OP!r}, got {text!r}")
                    )
                    detail = text
                    similarity = similarity_ratio(text, [LOGOUT_NO_OP])
    return ok, msg, detail, leak_after(srv, memcheck), mode, similarity


def _creds() -> dict[str, str]:
    """Return credential env_overrides for the student_courses user."""
    return {"ECLASS_USERNAME": _USER.username, "ECLASS_PASSWORD": _USER.password}
