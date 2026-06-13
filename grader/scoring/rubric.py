# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""The grading rubric: the test definitions and their groupings.

The rubric is 90 atomic rows totalling 100 points: 30 to the Python
implementation and 70 to the C replica. Each row is one behaviour
checked by one exact full-string match; ten rows are promoted to
two points (the date, default-window, union, initialize-frame, and
multi-step memory behaviours) and every other row is one point. The
26 C per-scenario memory rows are sub-assertions keyed
``<scenario>.mem``; each is awarded only when its paired functional
scenario passes, the gating the runner enforces before recording.

This module owns the rubric data: the ``TestDefinition`` row type, the
per-group row tuples, and the derived per-implementation and reporting
groupings. ``scoring`` imports them to build the scorer.
``schema_document`` serializes the
static per-row metadata to the ``grader_schema.json`` body, the
authority the results artifact's per-row outcomes are read against. See
SCORING.md for the full table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TestDefinition:
    """One row in the rubric.

    Attributes:
        id: Test identifier used as the key in the result mapping
            (``"P.1.1"``, ``"C.3.7"``, ``"C.2.3.mem"``, etc.).
        points: Points awarded when the test passes (1, or 2 for a
            promoted row).
        category: Category label for breakdown reports
            (``"protocol"``, ``"course"``, ``"general"``,
            ``"build"``, ``"stack"``, ``"config"``, ``"memory"``).
        target: Implementation under test, ``"python"`` or ``"c"``.
        description: Short human-readable description for the
            report writer.
        bucket: Either ``"baseline"`` or ``"feature"``; partitions
            the per-implementation totals into the rubric's
            baseline-vs-feature buckets.
    """

    id: str
    points: int
    category: str
    target: str
    description: str
    bucket: str


# Keep each rubric row on one line so the table stays scannable; without
# this fence ``ruff format`` wraps every row across six lines and buries it.
# fmt: off
PYTHON_BASELINE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("P.1.1", 1, "protocol", "python", "tools/list exposes all six tools with exact name and schema, descriptions byte-exact for the four baseline tools and presence-checked for the two announcement tools", "baseline"),
    TestDefinition("P.1.2", 1, "protocol", "python", "authstatus before login reports not-logged-in", "baseline"),
    TestDefinition("P.1.3", 1, "protocol", "python", "login with valid credentials succeeds", "baseline"),
    TestDefinition("P.1.4", 1, "protocol", "python", "authstatus on the live session reports the logged-in user", "baseline"),
    TestDefinition("P.1.5", 1, "protocol", "python", "second login while authenticated reports already-logged-in", "baseline"),
    TestDefinition("P.1.6", 1, "protocol", "python", "login with every credential surface deprived reports missing-credentials", "baseline"),
    TestDefinition("P.1.7", 1, "protocol", "python", "get_courses while logged in returns the faithful course list", "baseline"),
    TestDefinition("P.1.8", 1, "protocol", "python", "logout while authenticated succeeds", "baseline"),
    TestDefinition("P.1.9", 1, "protocol", "python", "authstatus after logout reports not-logged-in", "baseline"),
    TestDefinition("P.1.10", 1, "protocol", "python", "get_courses without authentication reports not-logged-in", "baseline"),
    TestDefinition("P.1.11", 1, "protocol", "python", "logout without a prior login is a no-op", "baseline"),
)

PYTHON_COURSE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("P.2.1", 1, "course", "python", "course tool without login returns the not-logged-in error", "feature"),
    TestDefinition("P.2.2", 1, "course", "python", "unparseable course_url returns the extract-code error", "feature"),
    TestDefinition("P.2.3", 1, "course", "python", "negative days_back returns the non-negative-integer error", "feature"),
    TestDefinition("P.2.4", 1, "course", "python", "out-of-window course returns the empty-window string", "feature"),
    TestDefinition("P.2.5", 2, "course", "python", "days_back=0 returns the single relative-date announcement", "feature"),
    TestDefinition("P.2.6", 1, "course", "python", "days_back=0 on an absolute-only course returns the empty-window string", "feature"),
    TestDefinition("P.2.7", 2, "course", "python", "default window returns the three in-scope announcements newest first", "feature"),
    TestDefinition("P.2.8", 1, "course", "python", "days_back=10 slices the explicit non-default window", "feature"),
    TestDefinition("P.2.9", 1, "course", "python", "days_back=40 widens past the default with no upper cap", "feature"),
)

PYTHON_GENERAL_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("P.3.1", 1, "general", "python", "general tool without login returns the not-logged-in error", "feature"),
    TestDefinition("P.3.2", 1, "general", "python", "negative days_back returns the non-negative-integer error", "feature"),
    TestDefinition("P.3.3", 1, "general", "python", "days_back=31 returns the older-than-30-days error", "feature"),
    TestDefinition("P.3.4", 1, "general", "python", "days_back=0 returns the empty-window string", "feature"),
    TestDefinition("P.3.5", 1, "general", "python", "days_back=5 returns the lone in-scope course entry with its source", "feature"),
    TestDefinition("P.3.6", 2, "general", "python", "days_back=8 returns the system and course union with both source forms", "feature"),
    TestDefinition("P.3.7", 1, "general", "python", "default window returns the full union ordered across sources", "feature"),
)

C_INFRA_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.1.1", 1, "build", "c", "make c-server exits 0 and produces the server binary", "baseline"),
    TestDefinition("C.1.2", 1, "stack", "c", "dynamic dependencies include libcurl", "baseline"),
    TestDefinition("C.1.3", 1, "stack", "c", "dynamic dependencies include libxml2", "baseline"),
    TestDefinition("C.1.4", 1, "stack", "c", "dynamic dependencies exclude any JSON-parsing library", "baseline"),
    TestDefinition("C.1.5", 1, "config", "c", "serves a tool configured by environment variables only", "baseline"),
    TestDefinition("C.1.6", 1, "config", "c", "serves a tool configured by the package-root .env only", "baseline"),
)

C_BASELINE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.2.1", 2, "protocol", "c", "the hand-written initialize frame (protocolVersion, capabilities, serverInfo)", "baseline"),
    TestDefinition("C.2.2", 1, "protocol", "c", "tools/list exposes all six tools with exact name and schema, descriptions byte-exact for the four baseline tools and presence-checked for the two announcement tools", "baseline"),
    TestDefinition("C.2.3", 1, "protocol", "c", "authstatus before login reports not-logged-in", "baseline"),
    TestDefinition("C.2.4", 1, "protocol", "c", "login with valid credentials succeeds", "baseline"),
    TestDefinition("C.2.5", 1, "protocol", "c", "authstatus on the live session reports the logged-in user", "baseline"),
    TestDefinition("C.2.6", 1, "protocol", "c", "second login while authenticated reports already-logged-in", "baseline"),
    TestDefinition("C.2.7", 1, "protocol", "c", "login with every credential surface deprived reports missing-credentials", "baseline"),
    TestDefinition("C.2.8", 1, "protocol", "c", "get_courses while logged in returns an accepted course-list form", "baseline"),
    TestDefinition("C.2.9", 1, "protocol", "c", "logout while authenticated succeeds", "baseline"),
    TestDefinition("C.2.10", 1, "protocol", "c", "authstatus after logout reports not-logged-in", "baseline"),
    TestDefinition("C.2.11", 1, "protocol", "c", "get_courses without authentication reports not-logged-in", "baseline"),
    TestDefinition("C.2.12", 1, "protocol", "c", "logout without a prior login is a no-op", "baseline"),
)

C_COURSE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.3.1", 1, "course", "c", "course tool without login returns the not-logged-in error", "feature"),
    TestDefinition("C.3.2", 1, "course", "c", "unparseable course_url returns the extract-code error", "feature"),
    TestDefinition("C.3.3", 1, "course", "c", "negative days_back returns the non-negative-integer error", "feature"),
    TestDefinition("C.3.4", 1, "course", "c", "out-of-window course returns the empty-window string", "feature"),
    TestDefinition("C.3.5", 2, "course", "c", "days_back=0 returns the single relative-date announcement", "feature"),
    TestDefinition("C.3.6", 1, "course", "c", "days_back=0 on an absolute-only course returns the empty-window string", "feature"),
    TestDefinition("C.3.7", 2, "course", "c", "default window returns the three in-scope announcements newest first", "feature"),
    TestDefinition("C.3.8", 1, "course", "c", "days_back=10 slices the explicit non-default window", "feature"),
    TestDefinition("C.3.9", 1, "course", "c", "days_back=40 widens past the default with no upper cap", "feature"),
)

C_GENERAL_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.4.1", 1, "general", "c", "general tool without login returns the not-logged-in error", "feature"),
    TestDefinition("C.4.2", 1, "general", "c", "negative days_back returns the non-negative-integer error", "feature"),
    TestDefinition("C.4.3", 1, "general", "c", "days_back=31 returns the older-than-30-days error", "feature"),
    TestDefinition("C.4.4", 1, "general", "c", "days_back=0 returns the empty-window string", "feature"),
    TestDefinition("C.4.5", 1, "general", "c", "days_back=5 returns the lone in-scope course entry with its source", "feature"),
    TestDefinition("C.4.6", 2, "general", "c", "days_back=8 returns the system and course union with both source forms", "feature"),
    TestDefinition("C.4.7", 1, "general", "c", "default window returns the full union ordered across sources", "feature"),
)

C_MULTISTEP_MEMORY_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.5.1", 2, "memory", "c", "session-spanning allocation and free across the full tool surface", "feature"),
    TestDefinition("C.5.2", 2, "memory", "c", "session-state replacement on re-login and idempotent teardown", "feature"),
    TestDefinition("C.5.3", 2, "memory", "c", "leak and responsiveness on the pure baseline regression surface", "feature"),
)
# fmt: on

# The 26 C functional scenarios observed under valgrind on their own
# execution. Each is a one-point sub-assertion keyed
# ``<scenario>.mem`` and is awarded only when its paired functional
# scenario passes (the runner records the pair atomically). C.2.1 and
# C.2.2 (protocol) and the C.1.* infra rows carry no memory
# sub-assertion, matching the rubric's 10 + 9 + 7 split.
_MEMORY_PAIRED_IDS: tuple[str, ...] = (
    tuple(f"C.2.{n}" for n in range(3, 13))
    + tuple(f"C.3.{n}" for n in range(1, 10))
    + tuple(f"C.4.{n}" for n in range(1, 8))
)

C_SCENARIO_MEMORY_TESTS: tuple[TestDefinition, ...] = tuple(
    TestDefinition(
        f"{base}.mem",
        1,
        "memory",
        "c",
        f"valgrind-clean execution of {base} (scored only if {base} passes)",
        "feature",
    )
    for base in _MEMORY_PAIRED_IDS
)

PYTHON_FEATURE_TESTS: tuple[TestDefinition, ...] = PYTHON_COURSE_TESTS + PYTHON_GENERAL_TESTS
PYTHON_TESTS: tuple[TestDefinition, ...] = PYTHON_BASELINE_TESTS + PYTHON_FEATURE_TESTS
C_FEATURE_TESTS: tuple[TestDefinition, ...] = (
    C_COURSE_TESTS + C_GENERAL_TESTS + C_MULTISTEP_MEMORY_TESTS + C_SCENARIO_MEMORY_TESTS
)
# Combined alias used by report.render for the "C MEMORY" report section.
C_MEMORY_TESTS: tuple[TestDefinition, ...] = C_MULTISTEP_MEMORY_TESTS + C_SCENARIO_MEMORY_TESTS

C_TESTS: tuple[TestDefinition, ...] = C_INFRA_TESTS + C_BASELINE_TESTS + C_FEATURE_TESTS
ALL_TESTS: tuple[TestDefinition, ...] = PYTHON_TESTS + C_TESTS


def schema_document() -> dict[str, dict[str, Any]]:
    """Serialize the rubric to the schema-artifact mapping.

    Each test id maps to its static rubric metadata: the point value,
    category, target implementation, description, and baseline-versus-
    feature bucket. The results artifact carries only the per-row
    outcomes; this static description lives here and is emitted once by
    ``--schema`` into ``grader_schema.json``, the authority a reader
    joins to interpret an opaque row id.

    Returns:
        The ``grader_schema.json`` body: a dict from test id to its
        rubric specification dict.
    """
    return {
        test.id: {
            "points": test.points,
            "category": test.category,
            "target": test.target,
            "description": test.description,
            "bucket": test.bucket,
        }
        for test in ALL_TESTS
    }
