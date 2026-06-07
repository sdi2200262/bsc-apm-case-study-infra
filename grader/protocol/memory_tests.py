# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Multi-step memory-leak scenarios for the C replica (C.5.1 through C.5.3).

Each scenario drives the C binary once under valgrind
``--leak-check=full --show-leak-kinds=all --track-origins=yes
--error-exitcode=99`` with a scripted JSON-RPC sequence piped on
stdin. The runner parses the valgrind leak summary on stderr and
asserts that ``definitely lost`` and ``indirectly lost`` are both
zero bytes and that valgrind exits cleanly (exit code != 99).

All three scenarios authenticate as ``student_courses``; content of
announcement responses is not asserted in these multi-step runs
(leak hygiene and responsiveness only).

Scenario gate logic: a scenario whose ``gates_on`` are not all in
the caller-supplied ``passed_tests`` set is skipped (recorded as a
zero-point fail) because valgrind on a feature path the participant
did not implement correctly verifies leaks on a short-circuited
error path, not the path the rubric awards points for.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._memcheck import (
    VALGRIND_STDERR_TAIL_LINES,
    classify_leak_verdict,
    tail_lines,
)
from .expected import course_url
from .runner import (
    BASELINE_TOOL_NAMES,
    CLIENT_NAME,
    CLIENT_VERSION,
    PROTOCOL_VERSION,
    mcp_server_env,
)
from .seed import SEED, user

VALGRIND_TIMEOUT_SECONDS = 120

_PRINCIPAL = user(SEED, "student_courses")

ToolCall = tuple[str, dict[str, Any]]

# Sentinel used in a scenario's call sequence to issue a bare
# ``tools/list`` request rather than a ``tools/call``. The handshake
# already emits ``initialize``; this lets a scenario list the tool
# surface as an explicit step.
TOOLS_LIST_METHOD = "tools/list"


@dataclass(frozen=True)
class MemoryScenario:
    """One C.5 multi-step scenario.

    Attributes:
        scenario_id: Rubric identifier (``"C.5.1"``, etc.).
        description: Short description for the report writer.
        calls: Ordered request sequence after the initialize and
            initialized handshake; the ``TOOLS_LIST_METHOD``
            sentinel issues a ``tools/list``, every other entry a
            ``tools/call``.
        gates_on: Rubric identifiers whose call shapes the scenario
            exercises; all must have passed for the scenario to run.
    """

    scenario_id: str
    description: str
    calls: tuple[ToolCall, ...]
    gates_on: tuple[str, ...]


SCENARIOS: tuple[MemoryScenario, ...] = (
    MemoryScenario(
        scenario_id="C.5.1",
        description="full tool surface across one session",
        calls=(
            (TOOLS_LIST_METHOD, {}),
            ("login", {}),
            ("authstatus", {}),
            ("get_courses", {}),
            ("get_course_announcements", {"course_url": course_url("PHYS150")}),
            ("get_general_announcements", {}),
            ("logout", {}),
            ("authstatus", {}),
        ),
        gates_on=(
            "C.2.4",
            "C.2.5",
            "C.2.8",
            "C.3.7",
            "C.4.7",
            "C.2.9",
            "C.2.10",
        ),
    ),
    MemoryScenario(
        scenario_id="C.5.2",
        description="session-state replacement and idempotent teardown",
        calls=(
            ("login", {}),
            ("login", {}),
            ("logout", {}),
            ("logout", {}),
            ("authstatus", {}),
        ),
        gates_on=(
            "C.2.4",
            "C.2.6",
            "C.2.9",
            "C.2.12",
            "C.2.3",
        ),
    ),
    MemoryScenario(
        scenario_id="C.5.3",
        description="baseline tool surface only, decoupled from announcement tools",
        calls=(
            ("login", {}),
            ("authstatus", {}),
            ("get_courses", {}),
            ("logout", {}),
            ("authstatus", {}),
        ),
        gates_on=(
            "C.2.4",
            "C.2.5",
            "C.2.8",
            "C.2.9",
            "C.2.10",
        ),
    ),
)


def run_scenario(
    scenario: MemoryScenario, eclass_root: Path, mock_root: Path
) -> tuple[bool, str, str]:
    """Run a memory scenario under valgrind and return the verdict.

    Args:
        scenario: Scenario to drive.
        eclass_root: Resolved path to the eclass-mcp-server checkout.
        mock_root: Resolved testing environment install path.

    Returns:
        Tuple of ``(ok, summary, detail)``. ``ok`` is ``True`` only
        when valgrind exits cleanly and both lost counts are zero;
        ``detail`` carries the captured valgrind stderr.
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
    except FileNotFoundError:
        return (
            False,
            f"{scenario.scenario_id}: valgrind not found on PATH",
            "valgrind not found on PATH",
        )
    except subprocess.CalledProcessError as error:
        return (
            False,
            f"{scenario.scenario_id}: valgrind --version returned non-zero",
            f"valgrind --version returned exit {error.returncode}",
        )

    sequence = _build_sequence(scenario.calls)
    env = os.environ.copy()
    env.update(mcp_server_env(mock_root))
    env["ECLASS_USERNAME"] = _PRINCIPAL.username
    env["ECLASS_PASSWORD"] = _PRINCIPAL.password

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
            encoding="utf-8",
            errors="replace",
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

    return classify_valgrind_run(
        scenario.scenario_id, result.returncode, result.stderr, result.stdout
    )


def classify_valgrind_run(
    scenario_id: str,
    returncode: int,
    stderr: str,
    stdout: str = "",
) -> tuple[bool, str, str]:
    """Classify one valgrind run's verdict from its exit code and streams.

    Thin wrapper around ``._memcheck.classify_leak_verdict``: the
    shared classifier decides clean-or-not from ``(returncode,
    stderr)``; this function prefixes the scenario identifier onto
    the reason and assembles the ``detail`` field with the bounded
    stderr and stdout tails the multi-step report writer prints.

    Args:
        scenario_id: Rubric identifier prefixed onto the summary and
            detail lines.
        returncode: ``result.returncode`` from the valgrind run; can
            be negative when the run was killed by a signal.
        stderr: Captured valgrind stderr (carries the leak summary).
        stdout: Captured server stdout; included as a bounded tail in
            the detail field for diagnostic context.

    Returns:
        ``(ok, summary, detail)`` where ``detail`` carries the
        bounded valgrind stderr tail and, when non-empty, the bounded
        server stdout tail.
    """
    detail = tail_lines(stderr, VALGRIND_STDERR_TAIL_LINES)
    if stdout:
        stdout_tail = tail_lines(stdout, VALGRIND_STDERR_TAIL_LINES)
        detail = f"{detail}\n--- stdout tail ---\n{stdout_tail}".strip()
    clean, reason = classify_leak_verdict(returncode, stderr)
    return clean, f"{scenario_id}: {reason}", detail


def _build_sequence(calls: tuple[ToolCall, ...]) -> str:
    """Return the newline-framed JSON-RPC sequence for a scenario.

    Opens with ``initialize`` and the ``notifications/initialized``
    notification, then issues one request per entry in ``calls``: a
    ``tools/list`` request for the ``TOOLS_LIST_METHOD``
    sentinel, otherwise a ``tools/call``. Baseline tools receive the
    ``random_string`` parameter.
    """
    frames: list[str] = [
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
                },
            }
        ),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
        ),
    ]
    for index, (tool, args) in enumerate(calls, start=2):
        if tool == TOOLS_LIST_METHOD:
            frames.append(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": index,
                        "method": "tools/list",
                        "params": {},
                    }
                )
            )
            continue
        merged = dict(args)
        if tool in BASELINE_TOOL_NAMES and "random_string" not in merged:
            merged["random_string"] = "test"
        frames.append(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": index,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": merged},
                }
            )
        )
    return "\n".join(frames) + "\n"
