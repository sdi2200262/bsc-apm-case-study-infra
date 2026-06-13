# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Score aggregation over the rubric rows.

``Scorer`` accumulates per-test results and computes the aggregate
scores the report writer consumes. The rubric rows themselves live in
``rubric`` (90 rows summing to 100: 30 Python, 70 C; see SCORING.md
for the full table); this module imports them and turns recorded
results into the report payload.

The JSON shape returned by ``Scorer.to_dict`` is consumed by the
``inspect`` results browser and the pipeline's grade and combine
stages. Every score node carries the same four fields inline,
``{total, total_strict, total_partial, max}``, and nests its child
nodes as extra keys: ``scores`` is the whole-submission node and
nests ``python`` and ``c``; ``python`` nests ``baseline`` and
``feature``. ``total`` sums every row's ``points_earned``;
``total_strict`` sums ``points`` over the ``"passed"`` rows;
``total_partial`` is their difference (the fractional credit from
partial rows, zero when none are present). Each per-test record reports
a three-state ``verdict``: ``"passed"`` (full points), ``"partial"`` (a
near-miss credited ``points * similarity``, with its ratio recorded), or
``"failed"`` (zero). The verdict is resolved at ``record`` time against
the ``Scorer``'s floor; a matcher pass is always ``"passed"``, so strict
grades are untouched. A record may also carry an optional unscored
``diagnostic`` string: the ``matching`` mode the row was accepted under
(``byte-exact`` or ``whitespace-normalized``), ``None`` elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rubric import (
    ALL_TESTS,
    C_TESTS,
    PYTHON_BASELINE_TESTS,
    PYTHON_FEATURE_TESTS,
    PYTHON_TESTS,
    TestDefinition,
)


def all_tests() -> dict[str, TestDefinition]:
    """Return every test definition keyed by its identifier."""
    return {t.id: t for t in ALL_TESTS}


@dataclass(frozen=True)
class TestResult:
    """Result of a single test execution.

    Attributes:
        test_id: The rubric identifier the result is keyed under.
        verdict: ``"passed"`` (full strict pass), ``"partial"``
            (a near-miss credited fractionally), or ``"failed"``
            (zero).
        message: Short human-readable summary for console output.
        full_output: Complete output captured for the JSON report.
        diagnostic: Optional unscored annotation carried on the
            per-test record: the ``matching`` mode the row was
            accepted under; ``None`` when the test records none.
        similarity: The edit-distance similarity ratio in ``[0, 1]``
            recorded on any string row that ran the partial check
            (``"partial"`` or ``"failed"``); ``None`` otherwise.
    """

    test_id: str
    verdict: str
    message: str
    full_output: str
    diagnostic: str | None = None
    similarity: float | None = None

    @property
    def passed(self) -> bool:
        """Whether the row is a full strict pass (``verdict == "passed"``)."""
        return self.verdict == "passed"


class Scorer:
    """Accumulates per-test results and computes rubric scores.

    Attributes:
        results: Per-row results keyed by rubric identifier, in
            recording order.
        partial_floor: The similarity floor at or above which a
            non-passing string row is credited as ``"partial"``
            rather than ``"failed"``.
    """

    def __init__(self, partial_floor: float) -> None:
        """Start with an empty result map and the partial-credit floor.

        Args:
            partial_floor: Similarity ratio at or above which a
                non-passing row is credited as ``"partial"``. The
                resolved value (CLI over ``grader.yaml`` over the
                module default) is supplied by the caller.
        """
        self.results: dict[str, TestResult] = {}
        self.partial_floor = partial_floor

    def record(
        self,
        test_id: str,
        passed: bool,
        message: str,
        full_output: str = "",
        diagnostic: str | None = None,
        similarity: float | None = None,
    ) -> None:
        """Record one test result, resolving its three-state verdict.

        A pass is ``"passed"`` at full points. A non-pass is
        ``"partial"`` when ``similarity`` is at or above ``partial_floor``,
        else ``"failed"``; both keep their similarity ratio (recorded for
        the distribution, scored only on ``"partial"``). A pass is never
        anything but ``"passed"``, so strict grades are untouched.

        Args:
            test_id: Rubric identifier (``"P.1.1"``, ``"C.3.7"``,
                ``"C.2.3.mem"``, etc.).
            passed: Whether the matcher accepted the row.
            message: Short summary for the console output.
            full_output: Complete output for the JSON report;
                falls back to ``message`` when empty.
            diagnostic: Optional unscored annotation (the
                ``matching`` mode the row was accepted under).
            similarity: Edit-distance similarity ratio for a
                non-passing string row, or ``None`` when the row
                passed or has no string contract.
        """
        if passed:
            verdict, kept_similarity = "passed", None
        elif similarity is not None and similarity >= self.partial_floor:
            verdict, kept_similarity = "partial", round(similarity, 6)
        else:
            verdict = "failed"
            kept_similarity = round(similarity, 6) if similarity is not None else None
        self.results[test_id] = TestResult(
            test_id=test_id,
            verdict=verdict,
            message=message,
            full_output=full_output or message,
            diagnostic=diagnostic,
            similarity=kept_similarity,
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

        ``total`` sums credited points (``points`` on a pass,
        ``points * similarity`` on a partial, zero on a fail),
        ``total_strict`` sums ``points`` over the ``"passed"`` rows
        only, ``total_partial`` is their difference, and ``max`` is the
        node's rubric maximum.

        Args:
            tests: The rubric rows the node aggregates over.

        Returns:
            The four-field score node for ``tests``.
        """
        total = 0.0
        total_strict = 0
        max_score = 0
        for test in tests:
            max_score += test.points
            result = self.results.get(test.id)
            if result is None:
                continue
            total += _earned(result, test.points)
            if result.verdict == "passed":
                total_strict += test.points
        total = round(total, 6)
        return {
            "total": _whole(total),
            "total_strict": total_strict,
            "total_partial": _whole(round(total - total_strict, 6)),
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


def _earned(result: TestResult, points: int) -> float:
    """Return the points credited for one row from its verdict.

    Full ``points`` on a ``"passed"`` row, ``points * similarity`` on a
    ``"partial"`` row (a value strictly between zero and ``points``),
    and zero on a ``"failed"`` row.

    Args:
        result: The recorded result carrying the verdict and, on a
            partial, the similarity ratio.
        points: The row's rubric maximum.

    Returns:
        The credited points for the row.
    """
    if result.verdict == "passed":
        return points
    if result.verdict == "partial":
        return round(points * (result.similarity or 0.0), 6)
    return 0


def _whole(value: float) -> float | int:
    """Return ``value`` as an ``int`` when it is whole, else unchanged.

    Keeps a node total that carries no fractional partial credit (every
    clean submission) serialized as ``100`` rather than ``100.0``.
    """
    return int(value) if float(value).is_integer() else value


def _test_entry(
    defs: dict[str, TestDefinition],
    test_id: str,
    result: TestResult,
) -> dict:
    """Build the per-test JSON payload preserving the documented field set."""
    definition = defs.get(test_id)
    points = definition.points if definition else 0
    entry: dict[str, Any] = {
        # ``verdict`` is three-state: ``"passed"`` (full points), ``"partial"``
        # (a near-miss credited fractionally), or ``"failed"`` (zero).
        # ``points_earned`` is kept distinct from ``points`` (the row maximum)
        # so a partial row can report a value strictly between zero and it.
        "verdict": result.verdict,
        "points": points,
        "points_earned": _earned(result, points) if definition else 0,
    }
    # ``similarity`` is recorded on any string row that ran the partial
    # check (``"partial"`` or ``"failed"``), between ``points_earned`` and the
    # descriptive fields, so the JSON carries the full ratio distribution, not
    # only the awarded partials.
    if result.similarity is not None:
        entry["similarity"] = result.similarity
    entry.update(
        {
            "category": definition.category if definition else "unknown",
            "description": definition.description if definition else "",
            "message": result.message,
            "full_output": result.full_output,
        }
    )
    if result.diagnostic is not None:
        entry["diagnostic"] = result.diagnostic
    return entry
