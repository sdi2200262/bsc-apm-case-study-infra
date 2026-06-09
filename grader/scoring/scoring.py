# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Score aggregation and the rubric point-budget guard.

``Scorer`` accumulates per-test results and computes the aggregate
scores the report writer consumes. The rubric rows themselves live in
``rubric``; this module imports them, enforces their per-group point
budget at import via ``_assert_rubric_balance`` (the rubric is 90 rows
summing to 100: 30 Python, 70 C; see SCORING.md for the full table),
and turns recorded results into the report payload.

The JSON shape returned by ``Scorer.to_dict`` is consumed by the
``inspect`` results browser and the pipeline's grade and combine
stages. Every score node carries the same four fields inline,
``{total, total_strict, total_partial, max}``, and nests its child
nodes as extra keys: ``scores`` is the whole-submission node and
nests ``python`` and ``c``; ``python`` nests ``baseline`` and
``feature``. ``total`` sums every row's ``points_earned``;
``total_strict`` sums ``points`` over the rows whose ``verdict`` is
``"passed"``; ``total_partial`` is their difference (zero until a
later partial-credit metric lands). Each per-test record reports a
three-state ``verdict`` (``"passed"`` or ``"failed"`` under the
current pass/fail rubric) and may carry an optional unscored
``diagnostic`` string: the ``matching`` mode the row was accepted
under (``byte-exact`` or ``whitespace-normalized``) on every
string-matched row, ``None`` elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
        raise RubricImbalanceError(f"c total sums to {c_total}, expected {_EXPECTED_C_POINTS}")
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

    def python_total_score(self) -> tuple[int, int]:
        """Return ``(score, max)`` for the Python implementation."""
        return self._sum_for(PYTHON_TESTS)

    def c_score(self) -> tuple[int, int]:
        """Return ``(score, max)`` for the C replica."""
        return self._sum_for(C_TESTS)

    def total_score(self) -> tuple[int, int]:
        """Return ``(score, max)`` for the rubric grand total."""
        return self._sum_for(ALL_TESTS)

    def to_dict(self) -> dict:
        """Return the JSON shape consumed by the inspect tool and the pipeline.

        Every score node carries ``{total, total_strict, total_partial,
        max}`` inline and nests its children as extra keys: ``scores``
        is the whole-submission node nesting ``python`` and ``c``, and
        ``python`` nests ``baseline`` and ``feature``. The by-category
        view is no longer persisted; ``inspect`` recomputes it from the
        per-row ``category`` under ``tests``.
        """
        defs = all_tests()
        scores = self._node(ALL_TESTS)
        python = self._node(PYTHON_TESTS)
        python["baseline"] = self._node(PYTHON_BASELINE_TESTS)
        python["feature"] = self._node(PYTHON_FEATURE_TESTS)
        scores["python"] = python
        scores["c"] = self._node(C_TESTS)
        return {
            "scores": scores,
            "tests": {
                test_id: _test_entry(defs, test_id, result)
                for test_id, result in self.results.items()
            },
        }

    def _node(self, tests: tuple[TestDefinition, ...]) -> dict[str, Any]:
        """Return one score node's ``{total, total_strict, total_partial, max}``.

        ``total`` sums each row's credited points (``points`` on a pass,
        zero on a fail; a later metric adds a fractional partial value),
        ``total_strict`` sums ``points`` over the passed rows only, and
        ``total_partial`` is their difference. ``max`` is the node's
        rubric maximum. With no partial rows present ``total`` equals
        ``total_strict`` and ``total_partial`` is zero.

        Args:
            tests: The rubric rows the node aggregates over.

        Returns:
            The four-field score node for ``tests``.
        """
        total: float = 0
        total_strict = 0
        max_score = 0
        for test in tests:
            max_score += test.points
            passed = self._passed(test.id)
            total += _earned(test.points, passed)
            if passed:
                total_strict += test.points
        return {
            "total": total,
            "total_strict": total_strict,
            "total_partial": total - total_strict,
            "max": max_score,
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


def _earned(points: int, passed: bool) -> float:
    """Return the points credited for one row.

    Full ``points`` on a pass, zero on a fail. A later partial-credit
    metric reports a fractional value between zero and ``points``;
    under the current pass/fail rubric the result is either ``points``
    or ``0``.

    Args:
        points: The row's rubric maximum.
        passed: Whether the row passed.

    Returns:
        The credited points for the row.
    """
    return points if passed else 0


def _test_entry(
    defs: dict[str, TestDefinition],
    test_id: str,
    result: TestResult,
) -> dict:
    """Build the per-test JSON payload preserving the documented field set."""
    definition = defs.get(test_id)
    points = definition.points if definition else 0
    entry = {
        # ``verdict`` is three-state by design (``"passed"`` | ``"partial"`` |
        # ``"failed"``); under the current pass/fail rubric only ``"passed"``
        # and ``"failed"`` occur, wired straight from the recorded boolean. A
        # later partial-credit metric introduces ``"partial"`` and a companion
        # ``similarity`` field, which never appear here.
        "verdict": "passed" if result.passed else "failed",
        # ``points_earned`` is kept distinct from ``points`` (the row maximum)
        # so the partial-credit metric can report a value between zero and the
        # maximum; under the current rubric it is either zero or full ``points``.
        "points": points,
        "points_earned": _earned(points, result.passed) if definition else 0,
        "category": definition.category if definition else "unknown",
        "description": definition.description if definition else "",
        "message": result.message,
        "full_output": result.full_output,
    }
    if result.diagnostic is not None:
        entry["diagnostic"] = result.diagnostic
    return entry
