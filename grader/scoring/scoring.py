#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Test definitions and score aggregation for the grading rubric.

The rubric is 90 atomic rows totalling 100 points: 30 to the Python
implementation and 70 to the C replica. Each row is one behaviour
checked by one exact full-string match; ten rows are promoted to
two points (the date, default-window, union, initialize-frame, and
multi-step memory behaviours) and every other row is one point. The
26 C per-scenario memory rows are sub-assertions keyed
``<scenario>.mem``; each is awarded only when its paired functional
scenario passes, the gating the runner enforces before recording.

Per-tier budgets are declared in ``_EXPECTED_TIER_POINTS`` and
enforced at import by ``_assert_rubric_balance``; see SCORING.md for
the full rubric. ``Scorer`` accumulates per-test results and
computes the aggregate scores the report writer consumes.

The JSON shape returned by ``Scorer.to_dict`` is consumed by
``pipeline.grade``, ``pipeline.combine``, and the ``inspect``
results browser; preserve the top-level keys
``scores.python.baseline``, ``scores.python.feature``,
``scores.python.total``, ``scores.c.total``, and
``scores.grand_total`` when editing. A per-test record may carry an
optional unscored ``diagnostic`` string: the ``matching`` mode the
row was accepted under (``byte-exact`` or ``whitespace-normalized``)
on every string-matched row, ``None`` elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass


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
        group: Either ``"baseline"`` or ``"feature"``; partitions
            the per-implementation totals into the rubric's
            baseline-vs-feature buckets.
    """

    id: str
    points: int
    category: str
    target: str
    description: str
    group: str


PYTHON_BASELINE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("P.1.1", 1, "protocol", "python", "tools/list exposes all six tools with exact name, description, and schema", "baseline"),
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
    TestDefinition("C.2.2", 1, "protocol", "c", "tools/list exposes all six tools with exact name, description, and schema", "baseline"),
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

PYTHON_FEATURE_TESTS: tuple[TestDefinition, ...] = (
    PYTHON_COURSE_TESTS + PYTHON_GENERAL_TESTS
)
PYTHON_TESTS: tuple[TestDefinition, ...] = (
    PYTHON_BASELINE_TESTS + PYTHON_FEATURE_TESTS
)
C_FEATURE_TESTS: tuple[TestDefinition, ...] = (
    C_COURSE_TESTS
    + C_GENERAL_TESTS
    + C_MULTISTEP_MEMORY_TESTS
    + C_SCENARIO_MEMORY_TESTS
)
# Combined alias used by reporting.py for the "C MEMORY" report section.
C_MEMORY_TESTS: tuple[TestDefinition, ...] = (
    C_MULTISTEP_MEMORY_TESTS + C_SCENARIO_MEMORY_TESTS
)

C_TESTS: tuple[TestDefinition, ...] = (
    C_INFRA_TESTS + C_BASELINE_TESTS + C_FEATURE_TESTS
)
ALL_TESTS: tuple[TestDefinition, ...] = PYTHON_TESTS + C_TESTS

# Required per-tier and per-implementation point budget. The rubric
# is balanced by construction; this table is the single source of
# truth a future edit is checked against so an unintended imbalance
# fails loudly at import rather than silently skewing scores.
_EXPECTED_TIER_POINTS: tuple[tuple[str, tuple[TestDefinition, ...], int], ...] = (
    ("python baseline", PYTHON_BASELINE_TESTS, 11),
    ("python course", PYTHON_COURSE_TESTS, 11),
    ("python general", PYTHON_GENERAL_TESTS, 8),
    ("c infra", C_INFRA_TESTS, 6),
    ("c baseline", C_BASELINE_TESTS, 13),
    ("c course", C_COURSE_TESTS, 11),
    ("c general", C_GENERAL_TESTS, 8),
    ("c multi-step memory", C_MULTISTEP_MEMORY_TESTS, 6),
    ("c per-scenario memory", C_SCENARIO_MEMORY_TESTS, 26),
)
_EXPECTED_PYTHON_POINTS = 30
_EXPECTED_C_POINTS = 70
_EXPECTED_GRAND_POINTS = 100


class RubricImbalanceError(AssertionError):
    """Raised at import when the rubric point budget does not balance.

    The grand total must be 100, the Python implementation 30, the C
    replica 70, and each tier its documented sub-total. A raised
    instance names the tier whose sum drifted and the expected and
    actual values so the corrective edit is unambiguous.
    """


def _assert_rubric_balance() -> None:
    """Verify the rubric sums to its documented per-tier budget.

    Raises:
        RubricImbalanceError: When any tier sub-total, the Python
            total, the C total, or the grand total differs from the
            documented value. The message names the failing bucket
            and the expected versus actual point counts so the fix
            does not require recomputing the whole table by hand.
    """
    for label, tests, expected in _EXPECTED_TIER_POINTS:
        actual = sum(t.points for t in tests)
        if actual != expected:
            raise RubricImbalanceError(
                f"rubric tier '{label}' sums to {actual}, expected {expected}"
            )
    python_total = sum(t.points for t in PYTHON_TESTS)
    if python_total != _EXPECTED_PYTHON_POINTS:
        raise RubricImbalanceError(
            f"python total sums to {python_total}, expected {_EXPECTED_PYTHON_POINTS}"
        )
    c_total = sum(t.points for t in C_TESTS)
    if c_total != _EXPECTED_C_POINTS:
        raise RubricImbalanceError(
            f"c total sums to {c_total}, expected {_EXPECTED_C_POINTS}"
        )
    grand_total = sum(t.points for t in ALL_TESTS)
    if grand_total != _EXPECTED_GRAND_POINTS:
        raise RubricImbalanceError(
            f"grand total sums to {grand_total}, expected {_EXPECTED_GRAND_POINTS}"
        )


_assert_rubric_balance()


def all_tests() -> dict[str, TestDefinition]:
    """Return every test definition keyed by its identifier."""
    return {t.id: t for t in ALL_TESTS}


@dataclass(frozen=True)
class TestResult:
    """Result of a single test execution.

    Attributes:
        test_id: The rubric identifier the result is keyed under.
        passed: Whether the test passed.
        message: Short human-readable summary for console output.
        full_output: Complete output captured for the JSON report.
        diagnostic: Optional unscored annotation carried on the
            per-test record: the ``matching`` mode the row was
            accepted under; ``None`` when the test records none.
    """

    test_id: str
    passed: bool
    message: str
    full_output: str
    diagnostic: str | None = None


class Scorer:
    """Accumulates per-test results and computes rubric scores."""

    def __init__(self) -> None:
        """Start with an empty result map."""
        self.results: dict[str, TestResult] = {}

    def record(
        self,
        test_id: str,
        passed: bool,
        message: str,
        full_output: str = "",
        diagnostic: str | None = None,
    ) -> None:
        """Record one test result.

        Args:
            test_id: Rubric identifier (``"P.1.1"``, ``"C.3.7"``,
                ``"C.2.3.mem"``, etc.).
            passed: Whether the test passed.
            message: Short summary for the console output.
            full_output: Complete output for the JSON report;
                falls back to ``message`` when empty.
            diagnostic: Optional unscored annotation (the
                ``matching`` mode the row was accepted under).
        """
        self.results[test_id] = TestResult(
            test_id=test_id,
            passed=passed,
            message=message,
            full_output=full_output or message,
            diagnostic=diagnostic,
        )

    def python_baseline_score(self) -> tuple[int, int]:
        """Return ``(score, max)`` for the Python baseline bucket."""
        return self._sum_for(PYTHON_BASELINE_TESTS)

    def python_feature_score(self) -> tuple[int, int]:
        """Return ``(score, max)`` for the Python feature bucket."""
        return self._sum_for(PYTHON_FEATURE_TESTS)

    def python_total_score(self) -> tuple[int, int]:
        """Return ``(score, max)`` for the Python implementation."""
        return self._sum_for(PYTHON_TESTS)

    def c_score(self) -> tuple[int, int]:
        """Return ``(score, max)`` for the C replica."""
        return self._sum_for(C_TESTS)

    def total_score(self) -> tuple[int, int]:
        """Return ``(score, max)`` for the rubric grand total."""
        return self._sum_for(ALL_TESTS)

    def category_breakdown(self, target: str) -> dict[str, tuple[int, int]]:
        """Return per-category scores for a target implementation.

        Args:
            target: ``"python"`` or ``"c"``.

        Returns:
            Mapping from category label to ``(score, max)``.
        """
        tests = PYTHON_TESTS if target == "python" else C_TESTS
        buckets: dict[str, list[int]] = {}
        for test in tests:
            entry = buckets.setdefault(test.category, [0, 0])
            entry[1] += test.points
            if self._passed(test.id):
                entry[0] += test.points
        return {category: (scores[0], scores[1]) for category, scores in buckets.items()}

    def to_dict(self) -> dict:
        """Return the JSON shape consumed by the pipeline and the inspect tool."""
        defs = all_tests()
        py_baseline = self.python_baseline_score()
        py_feature = self.python_feature_score()
        py_total = self.python_total_score()
        c_total = self.c_score()
        grand = self.total_score()
        return {
            "scores": {
                "python": {
                    "baseline": {"score": py_baseline[0], "max": py_baseline[1]},
                    "feature": {"score": py_feature[0], "max": py_feature[1]},
                    "total": {"score": py_total[0], "max": py_total[1]},
                },
                "c": {
                    "total": {"score": c_total[0], "max": c_total[1]},
                },
                "grand_total": {"score": grand[0], "max": grand[1]},
            },
            "tests": {
                test_id: _test_entry(defs, test_id, result)
                for test_id, result in self.results.items()
            },
            "category_breakdown": {
                "python": self.category_breakdown("python"),
                "c": self.category_breakdown("c"),
            },
        }

    def _sum_for(self, tests: tuple[TestDefinition, ...]) -> tuple[int, int]:
        """Sum earned and maximum points across a tuple of test definitions."""
        score = 0
        max_score = 0
        for test in tests:
            max_score += test.points
            if self._passed(test.id):
                score += test.points
        return score, max_score

    def _passed(self, test_id: str) -> bool:
        """Return ``True`` when the recorded result for ``test_id`` is a pass."""
        result = self.results.get(test_id)
        return result is not None and result.passed


def _test_entry(
    defs: dict[str, TestDefinition],
    test_id: str,
    result: TestResult,
) -> dict:
    """Build the per-test JSON payload preserving the documented field set."""
    definition = defs.get(test_id)
    points = definition.points if definition else 0
    entry = {
        "passed": result.passed,
        "points": points,
        "points_earned": points if (definition and result.passed) else 0,
        "category": definition.category if definition else "unknown",
        "description": definition.description if definition else "",
        "message": result.message,
        "full_output": result.full_output,
    }
    if result.diagnostic is not None:
        entry["diagnostic"] = result.diagnostic
    return entry
