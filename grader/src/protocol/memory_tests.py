#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Memory-leak scenarios for the C replica.

The C replica is exercised under
``valgrind --leak-check=full --error-exitcode=99`` driven by a
scripted JSON-RPC sequence. Each scenario is a tuple of tool
calls; the runner assembles the JSON-RPC frames, pipes them on
stdin, parses the leak summary on stderr, and asserts that
``definitely lost`` and ``indirectly lost`` are both zero bytes
and that valgrind exits cleanly.

The four scenarios cover, in order, the login lifecycle, the
course-announcement tool across argument variations, the general-
announcement tool across argument variations, and a full-session
integration that exercises both feature tools across two login
sessions.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .runner import (
    BASELINE_TOOL_NAMES,
    CLIENT_NAME,
    CLIENT_VERSION,
    PROTOCOL_VERSION,
    mcp_server_env,
)
from ._announcements_assertions import course_url

VALGRIND_TIMEOUT_SECONDS = 120
VALGRIND_LEAK_OK_EXIT = 0


ToolCall = tuple[str, dict]


@dataclass(frozen=True)
class MemoryScenario:
    """One C.5 scenario.

    Attributes:
        scenario_id: Rubric identifier (``"C.5.1"``, etc.) the
            scenario records its result under.
        description: Short description for the report writer.
        calls: Ordered tool-call sequence the scenario drives,
            after the initialize and initialized handshake.
    """

    scenario_id: str
    description: str
    calls: tuple[ToolCall, ...]


SCENARIOS: tuple[MemoryScenario, ...] = (
    MemoryScenario(
        scenario_id="C.5.1",
        description="login lifecycle",
        calls=(
            ("login", {}),
            ("login", {}),
            ("logout", {}),
            ("logout", {}),
            ("login", {}),
            ("logout", {}),
        ),
    ),
    MemoryScenario(
        scenario_id="C.5.2",
        description="course-announcement variations",
        calls=(
            ("login", {}),
            ("get_courses", {}),
            ("get_course_announcements", {"course_url": course_url("CS101")}),
            ("get_course_announcements", {"course_url": course_url("MATH201")}),
            ("get_course_announcements", {"course_url": course_url("CS101"), "days_back": 0}),
            ("get_course_announcements", {"course_url": course_url("CS101"), "days_back": 60}),
            ("logout", {}),
        ),
    ),
    MemoryScenario(
        scenario_id="C.5.3",
        description="general-announcement variations",
        calls=(
            ("login", {}),
            ("get_courses", {}),
            ("get_general_announcements", {}),
            ("get_general_announcements", {"days_back": 0}),
            ("get_general_announcements", {"days_back": 15}),
            ("logout", {}),
        ),
    ),
    MemoryScenario(
        scenario_id="C.5.4",
        description="full lifecycle integration with both features",
        calls=(
            ("login", {}),
            ("get_courses", {}),
            ("get_course_announcements", {"course_url": course_url("CS101")}),
            ("get_course_announcements", {"course_url": course_url("CS101"), "days_back": 60}),
            ("get_course_announcements", {"course_url": course_url("MATH201")}),
            ("get_general_announcements", {}),
            ("get_general_announcements", {"days_back": 15}),
            ("get_general_announcements", {"days_back": 0}),
            ("authstatus", {}),
            ("logout", {}),
            ("login", {}),
            ("get_course_announcements", {"course_url": course_url("CS101"), "days_back": 0}),
            ("get_general_announcements", {"days_back": 15}),
            ("logout", {}),
        ),
    ),
)


def run_scenario(
    scenario: MemoryScenario, eclass_root: Path, mock_root: Path
) -> tuple[bool, str, str]:
    """Run a memory scenario under valgrind and return the verdict.

    Args:
        scenario: Scenario to drive.
        eclass_root: Resolved path to the eclass-mcp-server checkout
            (the C replica lives at ``c-replica/`` beneath it).
        mock_root: Resolved path to the testing environment install
            whose env vars the C binary reads.

    Returns:
        Tuple of ``(ok, summary, detail)``. ``ok`` is ``True`` only
        when valgrind exits cleanly and both ``definitely lost`` and
        ``indirectly lost`` report zero bytes; ``detail`` carries
        the captured valgrind stderr on failure.
    """
    eclass_root = Path(eclass_root).resolve()
    mock_root = Path(mock_root).resolve()
    c_replica = eclass_root / "c-replica"
    server_binary = c_replica / "server"

    if not server_binary.exists():
        return (
            False,
            f"{scenario.scenario_id}: server binary not found",
            f"server binary not found at {server_binary}",
        )

    try:
        subprocess.run(["valgrind", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return (
            False,
            f"{scenario.scenario_id}: valgrind not on PATH",
            "valgrind not on PATH",
        )

    sequence = _build_sequence(scenario.calls)
    env = os.environ.copy()
    env.update(mcp_server_env(mock_root))

    try:
        result = subprocess.run(
            [
                "valgrind",
                "--leak-check=full",
                "--show-leak-kinds=all",
                "--track-origins=yes",
                "--error-exitcode=99",
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
        return (
            False,
            f"{scenario.scenario_id}: valgrind timed out ({VALGRIND_TIMEOUT_SECONDS}s)",
            f"valgrind timed out after {VALGRIND_TIMEOUT_SECONDS} seconds",
        )

    output = result.stderr
    definitely_lost = _parse_leak(output, "definitely lost")
    indirectly_lost = _parse_leak(output, "indirectly lost")

    if result.returncode != VALGRIND_LEAK_OK_EXIT:
        return (
            False,
            f"{scenario.scenario_id}: valgrind exit {result.returncode} "
            f"({definitely_lost} bytes definitely lost, "
            f"{indirectly_lost} bytes indirectly lost)",
            output,
        )
    if definitely_lost != 0 or indirectly_lost != 0:
        return (
            False,
            f"{scenario.scenario_id}: leaks present "
            f"({definitely_lost} bytes definitely lost, "
            f"{indirectly_lost} bytes indirectly lost)",
            output,
        )
    return (
        True,
        f"{scenario.scenario_id}: clean run, 0 bytes leaked",
        output,
    )


def _build_sequence(calls: tuple[ToolCall, ...]) -> str:
    """Return the newline-framed JSON-RPC sequence for a scenario.

    The sequence opens with ``initialize`` and the
    ``notifications/initialized`` notification, then issues one
    ``tools/call`` request per entry in ``calls``. Baseline tools
    receive the ``random_string`` parameter the upstream reference
    declares so the C replica's input contract matches Python's.
    """
    frames: list[str] = []
    frames.append(json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        },
    }))
    frames.append(json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }))
    for index, (tool, args) in enumerate(calls, start=2):
        merged = dict(args)
        if tool in BASELINE_TOOL_NAMES and "random_string" not in merged:
            merged["random_string"] = "test"
        frames.append(json.dumps({
            "jsonrpc": "2.0",
            "id": index,
            "method": "tools/call",
            "params": {"name": tool, "arguments": merged},
        }))
    return "\n".join(frames) + "\n"


def _parse_leak(output: str, leak_type: str) -> int:
    """Return the byte count for ``leak_type`` from valgrind stderr.

    Args:
        output: Captured valgrind stderr.
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
