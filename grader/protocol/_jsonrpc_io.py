#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Line-level JSON-RPC stdio reads for the protocol runner.

A ``select``-bounded readline and the id-correlating read loop that
skips lines which do not parse or do not answer the outstanding
request. Split from ``runner`` to keep it within the module-size
budget.
"""

from __future__ import annotations

import json
import select
import time
from typing import IO

from .. import log

__all__ = ["read_line_with_timeout", "read_correlated_response"]


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
