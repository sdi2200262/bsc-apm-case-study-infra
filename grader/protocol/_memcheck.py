#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Valgrind memcheck helpers for the C replica functional scenarios.

Parses captured valgrind stderr: a per-category byte-count extractor, a
report tailer for per-test detail fields, and the leak-clean classifier.
The classifier is pure so the multi-step scenarios and the per-scenario
``.mem`` sub-assertions share one decision rather than drifting between
two near-copies.
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
    pattern = re.compile(rf"{re.escape(leak_type)}:\s*([\d,]+)\s*bytes", re.IGNORECASE)
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


def classify_leak_verdict(returncode: int, stderr: str) -> tuple[bool, str]:
    """Return ``(clean, reason)`` for a valgrind run from its outputs.

    The shared decision both the multi-step scenarios and the
    per-scenario ``.mem`` sub-assertions apply. A run is clean only
    when valgrind ran to completion and reported a leak summary with
    zero ``definitely lost`` and zero ``indirectly lost`` bytes. The
    branches:

    - ``returncode < 0``: the process was killed by a signal; the
      run never completed and the verdict is FAIL.
    - end-of-report markers absent from ``stderr``: valgrind did not
      finish printing its summary even though it returned, so a
      ``0``-bytes parse would be a false-clean. FAIL.
    - ``returncode == 99``: valgrind's ``--error-exitcode`` sentinel.
      FAIL with the parsed lost counts.
    - parsed lost counts non-zero: FAIL with the leak detail.
    - otherwise: PASS.

    Args:
        returncode: ``subprocess.Popen.returncode`` from the valgrind
            run; can be negative when killed by a signal.
        stderr: Captured valgrind stderr (carries the leak summary).

    Returns:
        ``(clean, reason)`` where ``reason`` is a short phrase
        describing the outcome; the caller is free to prefix
        scenario identifiers or append further detail.
    """
    if returncode < 0:
        return False, f"killed by signal {-returncode}"
    if not _valgrind_report_complete(stderr):
        return (
            False,
            "incomplete valgrind report; no end-of-report lines present",
        )
    definitely_lost = parse_leak_bytes(stderr, "definitely lost")
    indirectly_lost = parse_leak_bytes(stderr, "indirectly lost")
    if returncode == 99:
        return (
            False,
            f"valgrind error exit (exit 99); "
            f"{definitely_lost} bytes definitely lost, "
            f"{indirectly_lost} bytes indirectly lost",
        )
    if definitely_lost != 0 or indirectly_lost != 0:
        return (
            False,
            f"leaks present "
            f"({definitely_lost} bytes definitely lost, "
            f"{indirectly_lost} bytes indirectly lost)",
        )
    return True, "clean run, 0 bytes leaked"


def _valgrind_report_complete(stderr: str) -> bool:
    """Return whether stderr shows valgrind's at-exit emit ran to completion.

    A complete valgrind report ends with at least one of three markers
    that the at-exit handler emits unconditionally:

    - the per-category ``definitely lost`` LEAK SUMMARY line (printed
      when one or more allocations went unfreed at exit);
    - the all-clean summary line ``All heap blocks were freed -- no
      leaks are possible`` (printed when zero allocations went
      unfreed, in place of the per-category breakdown);
    - the trailing ``ERROR SUMMARY:`` line, emitted on every completed
      run regardless of leak content.

    Their joint absence indicates the run never reached its emit step
    (signal kill, hang past timeout, ``_exit`` bypassing the handler),
    so a parsed zero on either lost line would be a false-clean.

    Args:
        stderr: Captured valgrind stderr.

    Returns:
        ``True`` when at least one terminal marker is present,
        ``False`` otherwise.
    """
    lower = stderr.lower()
    return (
        "definitely lost" in lower
        or "all heap blocks were freed -- no leaks are possible" in lower
        or "error summary:" in lower
    )
