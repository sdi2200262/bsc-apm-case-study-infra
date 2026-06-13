#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Line-level JSON-RPC stdio reads and outgoing-frame serialization.

A ``select``-bounded readline and the id-correlating read loop, plus the
shared outgoing-frame serializer. The read side parses with ``json.loads``
(whitespace-insensitive), so the process-wide outgoing-spacing policy
(``set_compact_emission``, applied by ``dump_message``) changes only how
frames are emitted, never how a reply is read; its default reproduces the
``json.dumps`` defaults.
"""

from __future__ import annotations

import json
import select
import time
from typing import IO

from .. import log

__all__ = [  # noqa: RUF022 (grouped by role: serialization, then read flow)
    "set_compact_emission",
    "dump_message",
    "read_line_with_timeout",
    "read_correlated_response",
]

# Process-wide outgoing-serialization policy: ``False`` is the
# ``json.dumps`` default (spaced), ``True`` is compact.
_compact_emission = False


def set_compact_emission(enabled: bool) -> None:
    """Select compact (``True``) or default-spaced (``False``) outgoing frames.

    Set once from the ``--compact-json`` flag before any server spawns.

    Args:
        enabled: ``True`` to emit compact frames, ``False`` for the
            ``json.dumps`` default spacing.
    """
    global _compact_emission
    _compact_emission = enabled


def dump_message(message: dict) -> str:
    """Serialize one outgoing JSON-RPC frame to a single line, no newline.

    Shared by every emit site so the ``--compact-json`` policy applies
    uniformly.

    Args:
        message: The JSON-RPC frame to serialize.

    Returns:
        One JSON line: compact when compact emission is set, else the
        ``json.dumps`` default spacing.
    """
    if _compact_emission:
        return json.dumps(message, separators=(",", ":"))
    return json.dumps(message)


def read_line_with_timeout(stream: IO[str], timeout: float, debug: bool) -> str:
    """Read one line from ``stream``, or ``""`` if it stays unreadable for ``timeout`` seconds."""
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        if debug:
            log.debug(f"timeout: no response after {timeout}s")
        return ""
    return stream.readline()


def read_correlated_response(
    stream: IO[str], request_id: object, timeout: float, debug: bool
) -> dict | None:
    """Read forward until the response whose ``id`` equals ``request_id``.

    A response is tied to its request by ``id``, so a stray line (an
    illegal reply to a notification, a stale or malformed frame) is
    not this request's answer. Lines that fail to parse or carry a
    different ``id`` are skipped, bounded by one ``timeout`` budget
    shared across the reads.

    Args:
        stream: The participant server's stdout text stream.
        request_id: The ``id`` of the outstanding request.
        timeout: Total seconds to wait for the matching response.
        debug: Echo received and skipped lines when ``True``.

    Returns:
        The matching response, or ``None`` when the budget elapses
        with no match (the genuine unresponsive signal).
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        line = read_line_with_timeout(stream, remaining, debug)
        if not line:
            return None
        if debug:
            log.debug(f"recv: {line.strip()}")
        try:
            message = json.loads(line.strip())
        except json.JSONDecodeError:
            if debug:
                log.debug("skip: line did not parse as JSON")
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
        if debug:
            seen = message.get("id") if isinstance(message, dict) else "<non-object>"
            log.debug(f"skip: id {seen!r} does not match {request_id!r}")
