# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Time-dimension metrics: turn duration distribution and wall-clock decomposition.

A session's wall-clock extent decomposes into time during which at least
one model was actively serving a turn (turn-time) and time during which no
model was active (inter-turn-time). The two sum to the session duration.

Turn-time itself decomposes into a solo component (exactly one turn
covered the instant) and a concurrent component (two or more turns covered
the instant). The decomposition matters for APM sessions where the
participant can drive several agents in parallel: a Manager dispatching two
Workers in quick succession produces overlapping turn intervals across
conversation files, and the parallel-dispatch usage is itself a
behavioural signal.

The union-of-intervals computation walks a sorted list of interval
endpoints and accumulates time at each active-count level. Solo time is
the duration spent at active-count == 1; concurrent time is the duration
spent at active-count >= 2. The two sum to the union of every interval
(turn-time).

A phase scope's inter-turn time is not its own span minus its turn time:
a phase's turns interleave with other phases across the session, so its
share of the session's idle gaps is partitioned by assigning each gap to
the phase of the turn that precedes it. This module owns that partition;
``compute_time_metrics`` applies it when given the session and a phase
label, keeping the per-phase inter-turn times disjoint and summing to the
session total.

Per-turn duration distribution metrics (mean, p50, p95, stdev) are
computed over the per-turn durations directly, with no union-dedup. A turn
whose interval overlaps another's still counts its full length toward the
distribution; the deduplication only applies to the wall-clock
decomposition. The count of turns in scope is data and lives in
``data/aggregate/counts``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from statistics import median, pstdev

from ..data.aggregate.turn_series import phase_of_turn
from ..data.session import (
    Session,
    latest_real_timestamp,
    session_start_timestamp,
)
from ..data.turns import Turn


@dataclass(frozen=True)
class TimeMetrics:
    """Time-dimension metric block for a single scope.

    Attributes:
        duration: Wall-clock extent of the scope in seconds.
        turn_time: Total wall-clock time during which at least one turn
            was active inside the scope (union of turn intervals).
        turn_time_solo: Subset of ``turn_time`` during which exactly one
            turn was active.
        turn_time_concurrent: Subset of ``turn_time`` during which two or
            more turns were active.
        inter_turn_time: ``duration - turn_time``; time during which no
            turn was active.
        mean_turn_duration: Mean of per-turn durations in seconds.
        turn_duration_p50: Median of per-turn durations in seconds.
        turn_duration_p95: 95th percentile of per-turn durations via
            linear interpolation.
        turn_duration_stdev: Population standard deviation of per-turn
            durations.
    """

    duration: float
    turn_time: float
    turn_time_solo: float
    turn_time_concurrent: float
    inter_turn_time: float
    mean_turn_duration: float
    turn_duration_p50: float
    turn_duration_p95: float
    turn_duration_stdev: float


def compute_time_metrics(
    turns: Iterable[Turn],
    scope_start: datetime | None = None,
    scope_end: datetime | None = None,
    *,
    session: Session | None = None,
    phase_label: str | None = None,
) -> TimeMetrics:
    """Compute time metrics over a set of turns.

    The scope's wall-clock extent defaults to the earliest turn start and
    the latest turn end inside the supplied turn set. Callers that need
    the scope to extend beyond the outermost turn boundaries supply
    explicit ``scope_start`` and ``scope_end``.

    For a phase scope the inter-turn time is partitioned rather than taken
    as the scope's own span minus its turn time. Passing ``session``
    together with ``phase_label`` computes the phase's share of the
    session's idle gaps (see ``_calculate_partitioned_inter_turn_time``);
    ``duration`` then becomes the sum of the scope's turn time and that
    partitioned inter-turn time.

    Args:
        turns: The turns to aggregate over. Order does not matter; empty
            input produces a zero metric block.
        scope_start: Optional explicit start of the scope's wall-clock
            interval. Falls back to the earliest turn start when ``None``.
        scope_end: Optional explicit end. Falls back to the latest turn
            end when ``None``.
        session: The full session, supplied for a phase scope so the
            partitioned inter-turn time can be computed. ``None`` for
            session and role scopes.
        phase_label: The phase whose gaps to partition, supplied with
            ``session`` for a phase scope. ``None`` for session and role
            scopes.

    Returns:
        A populated ``TimeMetrics``.
    """
    turn_list = list(turns)
    if not turn_list:
        return _zero_metrics()
    intervals = [(turn.start_timestamp, turn.end_timestamp) for turn in turn_list]
    turn_time, turn_time_solo, turn_time_concurrent = _decompose_intervals(intervals)

    inter_turn_override = None
    if session is not None and phase_label is not None:
        session_start = session_start_timestamp(session)
        session_end = latest_real_timestamp(session)
        if session_start is not None and session_end is not None:
            inter_turn_override = _calculate_partitioned_inter_turn_time(
                session, phase_label, session_start, session_end
            )

    if inter_turn_override is not None:
        inter_turn_time = inter_turn_override
        duration_seconds = turn_time + inter_turn_time
    else:
        effective_start = (
            scope_start if scope_start is not None else min(start for start, _ in intervals)
        )
        effective_end = scope_end if scope_end is not None else max(end for _, end in intervals)
        duration_seconds = max(0.0, (effective_end - effective_start).total_seconds())
        inter_turn_time = max(0.0, duration_seconds - turn_time)

    durations = [max(0.0, (end - start).total_seconds()) for start, end in intervals]
    return TimeMetrics(
        duration=duration_seconds,
        turn_time=turn_time,
        turn_time_solo=turn_time_solo,
        turn_time_concurrent=turn_time_concurrent,
        inter_turn_time=inter_turn_time,
        mean_turn_duration=sum(durations) / len(durations),
        turn_duration_p50=float(median(durations)),
        turn_duration_p95=_percentile(durations, 0.95),
        turn_duration_stdev=float(pstdev(durations)) if len(durations) > 1 else 0.0,
    )


def _merge_active_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Merge overlapping turn intervals into disjoint active spans.

    Emits one span per maximal stretch during which at least one turn is
    active, so overlapping turns from different conversations collapse into
    a single span and the complement of the result is the idle time.

    Args:
        intervals: ``(start, end)`` pairs for every turn; order is
            irrelevant and zero-length pairs are admitted.

    Returns:
        Disjoint ``(start, end)`` spans in ascending order. Empty when
        ``intervals`` is empty.
    """
    if not intervals:
        return []
    events: list[tuple[datetime, int]] = []
    for start, end in intervals:
        events.append((start, +1))
        events.append((end, -1))
    events.sort(key=lambda event: (event[0], -event[1]))
    merged: list[tuple[datetime, datetime]] = []
    active = 0
    span_start: datetime | None = None
    for time_point, delta in events:
        if active == 0 and delta > 0:
            span_start = time_point
        active += delta
        if active == 0 and span_start is not None:
            merged.append((span_start, time_point))
            span_start = None
    return merged


def _turn_ending_at(turns: tuple[Turn, ...], boundary: datetime) -> Turn | None:
    """Return a turn whose end coincides with an active span's right edge.

    The idle interval beginning at that edge is attributed to this turn's
    phase. Several turns ending together share a phase, so the first match
    suffices.

    Args:
        turns: The session turns.
        boundary: The active span's right edge to match.

    Returns:
        The matching turn, or ``None`` if no turn ends at ``boundary``.
    """
    # Linear scan per boundary, O(turns x gaps). Fine for a single session's
    # turn list; build an end-timestamp index if it ever matters.
    for turn in turns:
        if turn.end_timestamp == boundary:
            return turn
    return None


def _calculate_partitioned_inter_turn_time(
    session: Session,
    phase_label: str,
    scope_start: datetime,
    scope_end: datetime,
) -> float:
    """Return the session's idle time attributed to one phase.

    Idle time is every instant in ``[scope_start, scope_end]`` covered by
    no turn of any conversation: the complement of the merged active spans,
    plus the leading and trailing gaps. Each idle interval is attributed to
    the phase of the turn closing the span on its left, the leading gap to
    the earliest-starting turn. The intervals partition the session idle,
    so the per-phase totals sum to the session ``inter_turn_time``.

    Args:
        session: The full session; its start-sorted ``turns`` supply the
            intervals and the phase attribution.
        phase_label: The phase whose idle share to total.
        scope_start: Start of the session wall-clock interval.
        scope_end: End of the session wall-clock interval.

    Returns:
        Idle seconds attributed to ``phase_label``; ``0.0`` when the
        session has no turns or no active span.
    """
    all_turns = session.turns
    if not all_turns:
        return 0.0
    active_spans = _merge_active_intervals(
        [(turn.start_timestamp, turn.end_timestamp) for turn in all_turns]
    )
    if not active_spans:
        return 0.0

    total_idle = 0.0

    # Leading gap: scope_start to the first active instant, owned by the
    # earliest-starting turn's phase (the start-sorted first turn).
    first_span_start = active_spans[0][0]
    if first_span_start > scope_start and phase_of_turn(session, all_turns[0]) == phase_label:
        total_idle += (first_span_start - scope_start).total_seconds()

    # Inter-span gaps: each idle interval runs from one active span's end to
    # the next span's start, owned by the turn closing the span on its left.
    for current_span, next_span in pairwise(active_spans):
        owner = _turn_ending_at(all_turns, current_span[1])
        if owner is not None and phase_of_turn(session, owner) == phase_label:
            total_idle += (next_span[0] - current_span[1]).total_seconds()

    # Trailing gap: last active instant to scope_end, owned by the turn that
    # closed the final span.
    last_span_end = active_spans[-1][1]
    if scope_end > last_span_end:
        owner = _turn_ending_at(all_turns, last_span_end)
        if owner is not None and phase_of_turn(session, owner) == phase_label:
            total_idle += (scope_end - last_span_end).total_seconds()

    return total_idle


def _decompose_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> tuple[float, float, float]:
    """Return ``(turn_time, turn_time_solo, turn_time_concurrent)`` in seconds.

    Uses a sweep over interval endpoints. Each ``start`` event increases
    the active count by one; each ``end`` event decreases it. Between
    consecutive events the active count is constant; the elapsed
    wall-clock time between them contributes to the solo or concurrent
    total according to whether the active count is exactly one or at least
    two.
    """
    if not intervals:
        return 0.0, 0.0, 0.0
    events: list[tuple[datetime, int]] = []
    for start, end in intervals:
        events.append((start, +1))
        events.append((end, -1))
    events.sort(key=lambda event: (event[0], -event[1]))
    active = 0
    last_time: datetime | None = None
    solo_seconds = 0.0
    concurrent_seconds = 0.0
    for time_point, delta in events:
        if last_time is not None and time_point > last_time:
            elapsed = (time_point - last_time).total_seconds()
            if active == 1:
                solo_seconds += elapsed
            elif active >= 2:
                concurrent_seconds += elapsed
        active += delta
        last_time = time_point
    return solo_seconds + concurrent_seconds, solo_seconds, concurrent_seconds


def _percentile(values: list[float], fraction: float) -> float:
    """Return a linearly-interpolated percentile of a sample.

    Args:
        values: Sample values; must be non-empty.
        fraction: Target fraction in ``[0, 1]``; for the 95th percentile
            pass ``0.95``.

    Returns:
        The interpolated percentile as a float.
    """
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low_index = int(position)
    high_index = min(low_index + 1, len(ordered) - 1)
    weight = position - low_index
    return ordered[low_index] * (1 - weight) + ordered[high_index] * weight


def _zero_metrics() -> TimeMetrics:
    """Return a zeroed ``TimeMetrics`` for an empty scope."""
    return TimeMetrics(
        duration=0.0,
        turn_time=0.0,
        turn_time_solo=0.0,
        turn_time_concurrent=0.0,
        inter_turn_time=0.0,
        mean_turn_duration=0.0,
        turn_duration_p50=0.0,
        turn_duration_p95=0.0,
        turn_duration_stdev=0.0,
    )
