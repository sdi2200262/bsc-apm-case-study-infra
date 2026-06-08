# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Score aggregation and the rubric point-budget guard.

``Scorer`` accumulates per-test results and computes the aggregate
scores the report writer consumes. The rubric rows themselves live in
``rubric``; this module imports them, enforces their per-group point
budget at import via ``_assert_rubric_balance`` (the rubric is 90 rows
summing to 100: 30 Python, 70 C; see SCORING.md for the full table),
and turns recorded results into the report payload.

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

from .rubric import (
    ALL_TESTS,
    C_BASELINE_TESTS,
    C_COURSE_TESTS,
    C_GENERAL_TESTS,
    C_INFRA_TESTS,
    C_MULTISTEP_MEMORY_TESTS,
    C_SCENARIO_MEMORY_TESTS,
    C_TESTS,
    PYTHON_BASELINE_TESTS,
    PYTHON_COURSE_TESTS,
    PYTHON_FEATURE_TESTS,
    PYTHON_GENERAL_TESTS,
    PYTHON_TESTS,
    TestDefinition,
)

# Required per-group and per-implementation point budget. The rubric
# is balanced by construction; this table is the single source of
# truth a future edit is checked against so an unintended imbalance
# fails loudly at import rather than silently skewing scores.
_EXPECTED_GROUP_POINTS: tuple[tuple[str, tuple[TestDefinition, ...], int], ...] = (
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
    replica 70, and each group its documented sub-total. A raised
    instance names the group whose sum drifted and the expected and
    actual values so the corrective edit is unambiguous.
    """


def _assert_rubric_balance() -> None:
    """Verify the rubric sums to its documented per-group budget.

    Raises:
        RubricImbalanceError: When any group sub-total, the Python
            total, the C total, or the grand total differs from the
            documented value. The message names the failing group
            and the expected versus actual point counts so the fix
            does not require recomputing the whole table by hand.
    """
    for label, tests, expected in _EXPECTED_GROUP_POINTS:
        actual = sum(t.points for t in tests)
        if actual != expected:
            raise RubricImbalanceError(
                f"rubric group '{label}' sums to {actual}, expected {expected}"
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
        # ``points_earned`` is kept distinct from ``points`` (the row maximum)
        # so a future partial-credit metric can report a value between zero and
        # the maximum; under the current pass/fail rubric it is either zero or
        # the full ``points``.
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
