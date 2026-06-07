# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Protocol-frame baseline assertions (P.1.1 / C.2.1, C.2.2).

Owns the two rows that assert a raw protocol frame rather than a tool
response: the ``tools/list`` advertisement and the C-replica
hand-written ``initialize`` frame. Both run against a freshly-spawned
MCP server as the ``student_courses`` principal and return the same
5-tuple as the other baseline rows
(``(ok, msg, detail, leak_tuple|None, mode|None)``; see
``grader.protocol.baseline_tests`` for the tuple contract). The
form-acceptance policy lives in ``.matching``; this module owns only
the frame exchange and the result wiring.
"""

from __future__ import annotations

import json
from pathlib import Path

from ._assertion_support import (
    HANDSHAKE_FAIL,
    SERVER_START_FAIL,
    TOOL_FAIL,
    Result5,
    leak_after,
)
from .matching import match_initialize, match_tools_list
from .runner import (
    CLIENT_NAME,
    CLIENT_VERSION,
    PROTOCOL_VERSION,
    ServerProcess,
    initialize_server,
    spawn_server,
)
from .seed import SEED, user

# Two-principal seed; baseline suite runs as student_courses.
_PRINCIPAL = user(SEED, "student_courses")


def test_tools_list(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    memcheck: bool = False,
) -> Result5:
    """P.1.1 / C.2.2: tools/list matches the constructed expected tool list.

    The contract split lives in
    ``grader.protocol.matching.match_tools_list``; this row
    propagates its ``mode`` so a presence-only acceptance surfaces
    in the WARNINGS block.
    """
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
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
                raw = server.send_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    }
                )
                if raw is None:
                    ok, msg, detail = TOOL_FAIL
                else:
                    detail = json.dumps(raw)
                    result = raw.get("result")
                    tools = result.get("tools") if isinstance(result, dict) else None
                    if not isinstance(tools, list):
                        ok = False
                        msg = "tools/list: invalid or missing tools array"
                    else:
                        ok, msg, mode = match_tools_list(tools)
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
    forms (see ``.expected``). The matched form, recorded as the
    row's diagnostic, is ``capabilities-faithful`` or
    ``capabilities-documented``. The expected response is constructed, never
    captured from the submission. C-only: a non-C implementation does not
    apply.
    """
    if impl != "c":
        reason = "C.2.1 applies to the C replica only"
        return False, reason, reason, None, None
    srv: ServerProcess | None = None
    ok, msg, detail = SERVER_START_FAIL
    mode: str | None = None
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
            raw = server.send_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {
                            "name": CLIENT_NAME,
                            "version": CLIENT_VERSION,
                        },
                    },
                }
            )
            if raw is None:
                ok, msg, detail = HANDSHAKE_FAIL
            else:
                result = raw.get("result")
                detail = json.dumps(raw)
                if result is None:
                    ok, msg = False, "initialize: no result field"
                else:
                    mode = match_initialize(result)
                    ok = mode is not None
                    msg = (
                        (f"initialize frame accepted ({mode})")
                        if ok
                        else (
                            "initialize frame matched neither accepted "
                            f"capability form: got {result!r}"
                        )
                    )
    return ok, msg, detail, leak_after(srv, memcheck), mode


def _creds() -> dict[str, str]:
    """Return credential env_overrides for the student_courses principal."""
    return {"ECLASS_USERNAME": _PRINCIPAL.username, "ECLASS_PASSWORD": _PRINCIPAL.password}
