#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Test definitions and score aggregation for the grading rubric.

The rubric assigns 100 points across two implementations: 41 to
the Python implementation (baseline plus per-tool announcement
features) and 59 to the C replica (build and tech-stack
verification, baseline mirror, the same announcement features,
and four memory scenarios). The test-definition tuples encode
the per-test point values, the category each test falls under,
and a short human-readable description; the ``Scorer`` class
accumulates per-test results and computes the aggregate scores
the report writer consumes.

The JSON shape returned by ``Scorer.to_dict`` is consumed by
``pipeline.grade``, ``pipeline.combine``, and the ``inspect``
results browser; preserve the top-level keys
``scores.python.baseline``, ``scores.python.feature``,
``scores.python.total``, ``scores.c.total``, and
``scores.grand_total`` when editing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TestDefinition:
    """One row in the rubric.

    Attributes:
        id: Test identifier used as the key in the result mapping
            (``"P.1.1"``, ``"C.5.4"``, etc.).
        points: Points awarded when the test passes.
        category: Category label for breakdown reports
            (``"protocol"``, ``"course"``, ``"general"``,
            ``"build"``, ``"stack"``, ``"memory"``).
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
    TestDefinition("P.1.1", 1, "protocol", "python", "initialize and tools/list expose all six tools", "baseline"),
    TestDefinition("P.1.2", 1, "protocol", "python", "login with valid credentials succeeds", "baseline"),
    TestDefinition("P.1.3", 1, "protocol", "python", "second login reports already-logged-in", "baseline"),
    TestDefinition("P.1.4", 1, "protocol", "python", "login with empty credentials reports missing-credentials", "baseline"),
    TestDefinition("P.1.5", 1, "protocol", "python", "logout while authenticated succeeds", "baseline"),
    TestDefinition("P.1.6", 1, "protocol", "python", "logout without prior login is a no-op", "baseline"),
    TestDefinition("P.1.7", 1, "protocol", "python", "get_courses returns the enrolled courses", "baseline"),
    TestDefinition("P.1.8", 1, "protocol", "python", "get_courses without authentication reports not-logged-in", "baseline"),
    TestDefinition("P.1.9", 1, "protocol", "python", "authstatus while authenticated reports logged-in", "baseline"),
    TestDefinition("P.1.10", 1, "protocol", "python", "authstatus without authentication reports not-logged-in", "baseline"),
)

PYTHON_COURSE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("P.2.1", 1, "course", "python", "course tool without login returns not-logged-in", "feature"),
    TestDefinition("P.2.2", 1, "course", "python", "unparseable course_url returns extract-code error", "feature"),
    TestDefinition("P.2.3", 1, "course", "python", "negative days_back returns positive-integer error", "feature"),
    TestDefinition("P.2.4", 1, "course", "python", "empty course returns no-announcements message", "feature"),
    TestDefinition("P.2.5", 3, "course", "python", "days_back=0 returns the day-zero announcement", "feature"),
    TestDefinition("P.2.6", 3, "course", "python", "days_back=15 returns the two in-scope announcements", "feature"),
    TestDefinition("P.2.7", 4, "course", "python", "default days_back returns the three in-scope announcements", "feature"),
    TestDefinition("P.2.8", 3, "course", "python", "days_back=60 returns all four announcements", "feature"),
)

PYTHON_GENERAL_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("P.3.1", 1, "general", "python", "general tool without login returns not-logged-in", "feature"),
    TestDefinition("P.3.2", 1, "general", "python", "negative days_back returns positive-integer error", "feature"),
    TestDefinition("P.3.3", 1, "general", "python", "days_back=31 returns older-than-30-days error", "feature"),
    TestDefinition("P.3.4", 3, "general", "python", "days_back=0 returns the three day-zero announcements", "feature"),
    TestDefinition("P.3.5", 3, "general", "python", "days_back=15 returns the six in-scope announcements", "feature"),
    TestDefinition("P.3.6", 5, "general", "python", "default returns nine announcements with multi-source attribution", "feature"),
)

C_INFRA_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.1.1", 3, "build", "c", "make c-server compiles the server binary", "baseline"),
    TestDefinition("C.1.2", 2, "stack", "c", "ldd reports libcurl, libxml2, and no JSON-parser library", "baseline"),
)

C_BASELINE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.2.1", 1, "protocol", "c", "initialize and tools/list expose all six tools", "baseline"),
    TestDefinition("C.2.2", 1, "protocol", "c", "login with valid credentials succeeds", "baseline"),
    TestDefinition("C.2.3", 1, "protocol", "c", "second login reports already-logged-in", "baseline"),
    TestDefinition("C.2.4", 1, "protocol", "c", "login with empty credentials reports missing-credentials", "baseline"),
    TestDefinition("C.2.5", 1, "protocol", "c", "logout while authenticated succeeds", "baseline"),
    TestDefinition("C.2.6", 1, "protocol", "c", "logout without prior login is a no-op", "baseline"),
    TestDefinition("C.2.7", 1, "protocol", "c", "get_courses returns the enrolled courses", "baseline"),
    TestDefinition("C.2.8", 1, "protocol", "c", "get_courses without authentication reports not-logged-in", "baseline"),
    TestDefinition("C.2.9", 1, "protocol", "c", "authstatus while authenticated reports logged-in", "baseline"),
    TestDefinition("C.2.10", 1, "protocol", "c", "authstatus without authentication reports not-logged-in", "baseline"),
)

C_COURSE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.3.1", 1, "course", "c", "course tool without login returns not-logged-in", "feature"),
    TestDefinition("C.3.2", 1, "course", "c", "unparseable course_url returns extract-code error", "feature"),
    TestDefinition("C.3.3", 1, "course", "c", "negative days_back returns positive-integer error", "feature"),
    TestDefinition("C.3.4", 1, "course", "c", "empty course returns no-announcements message", "feature"),
    TestDefinition("C.3.5", 3, "course", "c", "days_back=0 returns the day-zero announcement", "feature"),
    TestDefinition("C.3.6", 3, "course", "c", "days_back=15 returns the two in-scope announcements", "feature"),
    TestDefinition("C.3.7", 4, "course", "c", "default days_back returns the three in-scope announcements", "feature"),
    TestDefinition("C.3.8", 3, "course", "c", "days_back=60 returns all four announcements", "feature"),
)

C_GENERAL_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.4.1", 1, "general", "c", "general tool without login returns not-logged-in", "feature"),
    TestDefinition("C.4.2", 1, "general", "c", "negative days_back returns positive-integer error", "feature"),
    TestDefinition("C.4.3", 1, "general", "c", "days_back=31 returns older-than-30-days error", "feature"),
    TestDefinition("C.4.4", 3, "general", "c", "days_back=0 returns the three day-zero announcements", "feature"),
    TestDefinition("C.4.5", 3, "general", "c", "days_back=15 returns the six in-scope announcements", "feature"),
    TestDefinition("C.4.6", 5, "general", "c", "default returns nine announcements with multi-source attribution", "feature"),
)

C_MEMORY_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("C.5.1", 3, "memory", "c", "login lifecycle leaves no leaked memory", "feature"),
    TestDefinition("C.5.2", 3, "memory", "c", "course-announcement variations leave no leaked memory", "feature"),
    TestDefinition("C.5.3", 3, "memory", "c", "general-announcement variations leave no leaked memory", "feature"),
    TestDefinition("C.5.4", 4, "memory", "c", "full lifecycle integration leaves no leaked memory", "feature"),
)

PYTHON_FEATURE_TESTS: tuple[TestDefinition, ...] = (
    PYTHON_COURSE_TESTS + PYTHON_GENERAL_TESTS
)
PYTHON_TESTS: tuple[TestDefinition, ...] = (
    PYTHON_BASELINE_TESTS + PYTHON_FEATURE_TESTS
)
C_FEATURE_TESTS: tuple[TestDefinition, ...] = (
    C_COURSE_TESTS + C_GENERAL_TESTS + C_MEMORY_TESTS
)
C_TESTS: tuple[TestDefinition, ...] = (
    C_INFRA_TESTS + C_BASELINE_TESTS + C_FEATURE_TESTS
)
ALL_TESTS: tuple[TestDefinition, ...] = PYTHON_TESTS + C_TESTS


def all_tests() -> dict[str, TestDefinition]:
    """Return every test definition keyed by its identifier."""
    return {t.id: t for t in ALL_TESTS}


def max_scores() -> dict[str, int]:
    """Return the maximum points for each rubric bucket and the grand total."""
    return {
        "python_baseline": sum(t.points for t in PYTHON_BASELINE_TESTS),
        "python_features": sum(t.points for t in PYTHON_FEATURE_TESTS),
        "python_total": sum(t.points for t in PYTHON_TESTS),
        "c_total": sum(t.points for t in C_TESTS),
        "total": sum(t.points for t in ALL_TESTS),
    }


@dataclass(frozen=True)
class TestResult:
    """Result of a single test execution.

    Attributes:
        test_id: The rubric identifier the result is keyed under.
        passed: Whether the test passed.
        message: Short human-readable summary for console output.
        full_output: Complete output captured for the JSON report.
    """

    test_id: str
    passed: bool
    message: str
    full_output: str


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
    ) -> None:
        """Record one test result.

        Args:
            test_id: Rubric identifier (``"P.1.1"``, ``"C.5.4"``, etc.).
            passed: Whether the test passed.
            message: Short summary for the console output.
            full_output: Complete output for the JSON report;
                falls back to ``message`` when empty.
        """
        self.results[test_id] = TestResult(
            test_id=test_id,
            passed=passed,
            message=message,
            full_output=full_output or message,
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
    return {
        "passed": result.passed,
        "points": points,
        "points_earned": points if (definition and result.passed) else 0,
        "category": definition.category if definition else "unknown",
        "description": definition.description if definition else "",
        "message": result.message,
        "full_output": result.full_output,
    }
