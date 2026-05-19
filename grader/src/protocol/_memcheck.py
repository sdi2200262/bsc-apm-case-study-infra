#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Valgrind memcheck helpers for the C replica functional scenarios.

Two functions consumed by :meth:`ServerProcess.leak_verdict`:
``parse_leak_bytes`` extracts the byte count for one leak category
from captured valgrind stderr; ``tail_lines`` returns the trailing
portion of a valgrind report for use in per-test detail fields.
"""

from __future__ import annotations

import re

VALGRIND_STDERR_TAIL_LINES = 80


def parse_leak_bytes(output: str, leak_type: str) -> int:
    """Return the byte count for ``leak_type`` from valgrind stderr.

    Args:
        output: Captured valgrind stderr text.
        leak_type: One of ``"definitely lost"`` or ``"indirectly lost"``.

    Returns:
        The byte count for that leak category, or ``0`` when the
        pattern is absent.
    """
    pattern = re.compile(
        rf"{re.escape(leak_type)}:\s*([\d,]+)\s*bytes", re.IGNORECASE
    )
    found = pattern.search(output)
    if found:
        return int(found.group(1).replace(",", ""))
    return 0


def tail_lines(text: str, n: int) -> str:
    """Return the last ``n`` lines of ``text``.

    Args:
        text: Full text to tail.
        n: Number of lines to keep from the end.

    Returns:
        The trailing lines joined by newlines.
    """
    lines = text.splitlines()
    return "\n".join(lines[-n:])
