#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Test definitions and score aggregation for the grading rubric.

The rubric assigns 100 points across two implementations: 48 to
the Python implementation (baseline plus feature tools) and 52 to
the C replica (infrastructure plus baseline plus feature tools).
The test-definition tuples encode the per-test point values, the
category each test falls under, and a short human-readable
description; the ``Scorer`` class accumulates per-test results
and computes the aggregate scores the report writer consumes.

The JSON shape returned by ``Scorer.to_dict`` is consumed by
``pipeline.grade``, ``pipeline.combine``, and the ``inspect``
results browser; changing the shape cascades into those modules
and is out of scope for routine rubric edits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TestDefinition:
    """One row in the rubric.

    Attributes:
        id: Test identifier used as the key in the result mapping
            (``"P1"``, ``"AN1_c"``, etc.).
        points: Points awarded when the test passes.
        category: Category label for breakdown reports
            (``"build"``, ``"protocol"``, ``"announcements"``,
            etc.).
        target: Implementation under test, ``"python"`` or ``"c"``.
        description: Short human-readable description for the
            report writer.
        group: Either ``"baseline"`` or ``"feature"``; used to
            partition the Python score into baseline and feature
            buckets.
    """

    id: str
    points: int
    category: str
    target: str
    description: str
    group: str


PYTHON_BASELINE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("B1", 2, "build", "python", "Python dependency installation", "baseline"),
    TestDefinition("P1", 1, "protocol", "python", "initialize response structure", "baseline"),
    TestDefinition("P2", 1, "protocol", "python", "tools/list response structure", "baseline"),
    TestDefinition("L1", 1, "login", "python", "Successful login", "baseline"),
    TestDefinition("L2", 1, "login", "python", "Already logged in handling", "baseline"),
    TestDefinition("L3", 1, "login", "python", "Missing credentials error", "baseline"),
    TestDefinition("O1", 1, "logout", "python", "Successful logout", "baseline"),
    TestDefinition("O2", 1, "logout", "python", "Logout when not logged in", "baseline"),
    TestDefinition("C1", 1, "courses", "python", "Get courses when logged in", "baseline"),
    TestDefinition("C2", 1, "courses", "python", "Get courses when not logged in", "baseline"),
    TestDefinition("A1", 1, "authstatus", "python", "Authstatus when not logged in", "baseline"),
)

PYTHON_COURSE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("AN1", 3, "announcements", "python", "Not logged in error (exact string)", "feature"),
    TestDefinition("AN2", 3, "announcements", "python", "Invalid course URL error (exact string)", "feature"),
    TestDefinition("AN3", 3, "announcements", "python", "No announcements found (exact string)", "feature"),
    TestDefinition("AN4", 3, "announcements", "python", "Valid announcements with default days_back", "feature"),
    TestDefinition("AN5", 3, "announcements", "python", "Valid announcements with custom days_back", "feature"),
    TestDefinition("AN6", 3, "announcements", "python", "Invalid days_back (<=0) error", "feature"),
)

PYTHON_GENERAL_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("GAN1", 3, "general_announcements", "python", "Not logged in error", "feature"),
    TestDefinition("GAN2", 3, "general_announcements", "python", "Invalid days_back (<=0) error", "feature"),
    TestDefinition("GAN3", 3, "general_announcements", "python", "Invalid days_back (>30) error", "feature"),
    TestDefinition("GAN4", 3, "general_announcements", "python", "No announcements found", "feature"),
    TestDefinition("GAN5", 3, "general_announcements", "python", "Valid Aggregation (System + Course)", "feature"),
    TestDefinition("GAN6", 3, "general_announcements", "python", "Valid Filtering (Respects days_back)", "feature"),
)

C_INFRA_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("B2", 3, "build", "c", "C compilation (make c-server)", "baseline"),
    TestDefinition("M1", 3, "memory", "c", "Valgrind memory clean", "baseline"),
)

C_BASELINE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("P1_c", 1, "protocol", "c", "initialize response structure", "baseline"),
    TestDefinition("P2_c", 1, "protocol", "c", "tools/list response structure", "baseline"),
    TestDefinition("L1_c", 1, "login", "c", "Successful login", "baseline"),
    TestDefinition("L2_c", 1, "login", "c", "Already logged in handling", "baseline"),
    TestDefinition("L3_c", 1, "login", "c", "Missing credentials error", "baseline"),
    TestDefinition("O1_c", 1, "logout", "c", "Successful logout", "baseline"),
    TestDefinition("O2_c", 1, "logout", "c", "Logout when not logged in", "baseline"),
    TestDefinition("C1_c", 1, "courses", "c", "Get courses when logged in", "baseline"),
    TestDefinition("C2_c", 1, "courses", "c", "Get courses when not logged in", "baseline"),
    TestDefinition("A1_c", 1, "authstatus", "c", "Authstatus when not logged in", "baseline"),
)

C_COURSE_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("AN1_c", 3, "announcements", "c", "Not logged in error", "feature"),
    TestDefinition("AN2_c", 3, "announcements", "c", "Invalid course URL error", "feature"),
    TestDefinition("AN3_c", 3, "announcements", "c", "No announcements found", "feature"),
    TestDefinition("AN4_c", 3, "announcements", "c", "Valid announcements with default days_back", "feature"),
    TestDefinition("AN5_c", 3, "announcements", "c", "Valid announcements with custom days_back", "feature"),
    TestDefinition("AN6_c", 3, "announcements", "c", "Invalid days_back (<=0) error", "feature"),
)

C_GENERAL_TESTS: tuple[TestDefinition, ...] = (
    TestDefinition("GAN1_c", 3, "general_announcements", "c", "Not logged in error", "feature"),
    TestDefinition("GAN2_c", 3, "general_announcements", "c", "Invalid days_back (<=0) error", "feature"),
    TestDefinition("GAN3_c", 3, "general_announcements", "c", "Invalid days_back (>30) error", "feature"),
    TestDefinition("GAN4_c", 3, "general_announcements", "c", "No announcements found", "feature"),
    TestDefinition("GAN5_c", 3, "general_announcements", "c", "Valid Aggregation (System + Course)", "feature"),
    TestDefinition("GAN6_c", 3, "general_announcements", "c", "Valid Filtering (Respects days_back)", "feature"),
)

PYTHON_FEATURE_TESTS: tuple[TestDefinition, ...] = PYTHON_COURSE_TESTS + PYTHON_GENERAL_TESTS
PYTHON_TESTS: tuple[TestDefinition, ...] = PYTHON_BASELINE_TESTS + PYTHON_FEATURE_TESTS
C_TESTS: tuple[TestDefinition, ...] = (
    C_INFRA_TESTS + C_BASELINE_TESTS + C_COURSE_TESTS + C_GENERAL_TESTS
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
            test_id: Rubric identifier (``"P1"``, ``"AN1_c"``, etc.).
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
