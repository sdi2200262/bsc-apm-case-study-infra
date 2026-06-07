# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Shared scaffolding and result helpers for the scenario assertion suites.

Every ``*_tests.py`` module returns the same five-tuple result shape and
the same step-failure sentinels, and the C aggregators all record ``.mem``
sub-assertions with one outcome wording. Centralising them here removes the
copy-pasted scaffolding from the scenario modules and keeps the sentinel
text and the ``.mem`` recording wording from drifting between suites.
"""

from __future__ import annotations

LeakTuple = tuple[bool, str]
Result5 = tuple[bool, str, str, LeakTuple | None, str | None]

SERVER_START_FAIL: tuple[bool, str, str] = (
    False,
    "Could not start server",
    "Server failed to start",
)

HANDSHAKE_FAIL: tuple[bool, str, str] = (
    False,
    "server did not complete the MCP handshake",
    "initialize returned no response",
)

LOGIN_FAIL: tuple[bool, str, str] = (
    False,
    "server did not respond to login",
    "login tool call returned no response",
)

TOOL_FAIL: tuple[bool, str, str] = (
    False,
    "server did not respond to the tool call",
    "scoring tool call returned no response",
)


def leak_after(server: object, memcheck: bool) -> LeakTuple | None:
    """Return the valgrind leak verdict when one was requested.

    Args:
        server: The ``ServerProcess`` returned from ``spawn_server``,
            or ``None`` when the server failed to start.
        memcheck: Whether the spawn projected a valgrind wrapper.

    Returns:
        ``server.leak_verdict()`` when both ``memcheck`` is ``True``
        and ``server`` is not ``None``; ``None`` otherwise.
    """
    if memcheck and server is not None:
        return server.leak_verdict()  # type: ignore[attr-defined]
    return None


def record_mem(
    results: dict[str, tuple[bool, str, str, str | None]],
    test_id: str,
    ok: bool,
    leak: LeakTuple | None,
    no_verdict_msg: str | None = None,
) -> None:
    """Record the ``<id>.mem`` sub-assertion for one C functional scenario.

    The ``.mem`` row passes only when the functional row passed AND
    the valgrind run was leak-clean. The four outcomes are recorded
    with one consistent wording so the three C aggregators emit the
    same diagnostic strings:

    - clean leak verdict and functional passed -> ``<id>.mem: clean (0 bytes lost)``;
    - leak verdict reports a leak (functional passed) -> ``<id>.mem: leaks detected``;
    - functional failed (any leak verdict present) -> ``skipped: <id> functional did not pass``;
    - no leak verdict because the server did not start under valgrind
      -> the caller's verbatim ``no_verdict_msg`` (so the C baseline,
      C course, and C general aggregators all converge on the same
      phrasing).

    Args:
        results: The aggregator's running result mapping; the
            ``<id>.mem`` key is written in place.
        test_id: The functional rubric identifier; the ``.mem`` row
            is keyed ``"<test_id>.mem"``.
        ok: Whether the functional assertion passed.
        leak: The leak verdict from ``leak_after``, or ``None``
            when the spawn returned no server.
        no_verdict_msg: The message recorded when ``leak`` is
            ``None``. Defaults to the standard
            ``skipped: <id> produced no leak verdict (server did not
            start)`` wording shared by every C functional phase.
    """
    if no_verdict_msg is None:
        no_verdict_msg = (
            f"skipped: {test_id} produced no leak verdict (server did not start)"
        )
    if leak is not None:
        leak_clean, leak_detail = leak
        mem_ok = ok and leak_clean
        if mem_ok:
            mem_msg = f"{test_id}.mem: clean (0 bytes lost)"
        elif not ok:
            mem_msg = f"skipped: {test_id} functional did not pass"
        else:
            mem_msg = f"{test_id}.mem: leaks detected"
        results[f"{test_id}.mem"] = (mem_ok, mem_msg, leak_detail, None)
    else:
        results[f"{test_id}.mem"] = (False, no_verdict_msg, no_verdict_msg, None)
