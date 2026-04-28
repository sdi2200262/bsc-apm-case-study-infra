#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Valgrind memory-leak verification for the C replica.

The grader spawns the c-replica server under Valgrind, drives a
full session sequence over stdin (``initialize`` plus ``tools/list``
plus four ``tools/call`` requests for the baseline tools), then
parses the leak summary. The pass criterion is zero bytes on both
``definitely lost`` and ``indirectly lost``; any positive count
fails the test with the captured Valgrind output.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .protocol.runner import mcp_server_env

VALGRIND_TIMEOUT_SECONDS = 60

JSONRPC_SEQUENCE: tuple[str, ...] = (
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
    '{"protocolVersion":"2025-03-26","capabilities":{},'
    '"clientInfo":{"name":"grader","version":"1.0.0"}}}',
    '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}',
    '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":'
    '{"name":"login","arguments":{"random_string":"test"}}}',
    '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":'
    '{"name":"get_courses","arguments":{"random_string":"test"}}}',
    '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":'
    '{"name":"authstatus","arguments":{"random_string":"test"}}}',
    '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":'
    '{"name":"logout","arguments":{"random_string":"test"}}}',
)


def valgrind(eclass_root: Path, mock_root: Path) -> tuple[bool, str, str]:
    """Run Valgrind against the C replica's session flow.

    Args:
        eclass_root: Resolved path to the eclass-mcp-server checkout.
        mock_root: Resolved path to the testing environment install,
            used to derive the env vars the c-replica server needs.

    Returns:
        Tuple of ``(ok, summary, detail)``. ``ok`` is ``True`` only
        when both ``definitely lost`` and ``indirectly lost`` are
        zero bytes; ``detail`` carries the Valgrind stderr in full.
    """
    eclass_root = Path(eclass_root).resolve()
    mock_root = Path(mock_root).resolve()
    c_replica = eclass_root / "c-replica"
    server_binary = c_replica / "server"

    if not server_binary.exists():
        return False, "server binary not found", "server binary not found at c-replica/server"

    try:
        subprocess.run(
            ["valgrind", "--version"], capture_output=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False, "valgrind not available", "valgrind not installed or not in PATH"

    env = os.environ.copy()
    env.update(mcp_server_env(mock_root))

    sequence = "\n".join(JSONRPC_SEQUENCE) + "\n"
    try:
        result = subprocess.run(
            [
                "valgrind",
                "--leak-check=full",
                "--show-leak-kinds=all",
                "--track-origins=yes",
                "--error-exitcode=1",
                str(server_binary),
            ],
            input=sequence,
            capture_output=True,
            text=True,
            timeout=VALGRIND_TIMEOUT_SECONDS,
            env=env,
            cwd=c_replica,
        )
    except subprocess.TimeoutExpired:
        return False, f"valgrind timed out ({VALGRIND_TIMEOUT_SECONDS}s)", \
            f"valgrind timed out after {VALGRIND_TIMEOUT_SECONDS} seconds"

    output = result.stderr
    definitely_lost = _parse_leak(output, "definitely lost")
    indirectly_lost = _parse_leak(output, "indirectly lost")

    if definitely_lost == 0 and indirectly_lost == 0:
        return True, "memory clean: 0 bytes definitely lost, 0 bytes indirectly lost", output
    return (
        False,
        f"memory leaks: {definitely_lost} bytes definitely lost, "
        f"{indirectly_lost} bytes indirectly lost",
        output,
    )


def _parse_leak(output: str, leak_type: str) -> int:
    """Return the byte count for ``leak_type`` from Valgrind output.

    Args:
        output: Captured Valgrind stderr.
        leak_type: One of ``"definitely lost"``, ``"indirectly lost"``,
            ``"possibly lost"``, ``"still reachable"``.

    Returns:
        The byte count for that leak category, or ``0`` when the
        line is absent.
    """
    pattern = rf"{leak_type}:\s*([\d,]+)\s*bytes"
    match = re.search(pattern, output, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))
    return 0
