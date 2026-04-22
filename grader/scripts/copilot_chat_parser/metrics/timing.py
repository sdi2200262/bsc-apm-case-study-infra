#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Timing metrics: session duration, turn duration with distribution, and
per-phase span, active time, and inter-turn time.

All timing primitives depend on two fields per request:
``timestamp`` (user-send time, ms epoch) and
``modelState.completedAt`` (agent-response end, ms epoch). Requests with
no ``completedAt`` (the response never reached a terminal state) are
excluded from turn-duration and phase-timing computations.
"""

from __future__ import annotations

from statistics import median, pstdev
from typing import Any

from ..schema import IMPLEMENTATION_PHASE, OTHER_PHASE, PLANNING_PHASE
from ..session import AnnotatedRequest, Session

_MILLISECONDS_PER_SECOND = 1000.0
_MILLISECONDS_PER_MINUTE = 60000.0


def compute_session_duration(session: Session) -> dict[str, Any]:
    """Compute session wall-clock duration in minutes.

    Args:
        session: The assembled session.

    Returns:
        A dict with ``session_duration_minutes`` set to the wall-clock
        time from the earliest request timestamp to the latest response
        ``completedAt`` (across every conversation file), in minutes.
        When the session has no requests the value is ``0.0``.
    """
    if not session.requests:
        return {"session_duration_minutes": 0.0}
    min_start = min(annotated.raw.timestamp_ms for annotated in session.requests)
    max_end = _session_max_end(session)
    duration_ms = max_end - min_start
    return {"session_duration_minutes": duration_ms / _MILLISECONDS_PER_MINUTE}


def compute_turn_duration(session: Session) -> dict[str, Any]:
    """Compute mean turn duration with distribution summary.

    Turn duration for request ``i`` is
    ``(completedAt_i - timestamp_i) / 1000`` seconds. Requests without a
    ``completedAt`` are excluded.

    Args:
        session: The assembled session.

    Returns:
        A dict with ``mean_turn_duration_seconds``,
        ``turn_duration_p50_seconds``, ``turn_duration_p95_seconds``,
        ``turn_duration_stdev_seconds``, and ``turn_duration_sample_size``.
        When no requests contribute a duration, every numeric field is
        ``0.0`` and ``turn_duration_sample_size`` is ``0``.
    """
    durations = _turn_durations_seconds(session.requests)
    return _distribution_summary(durations, prefix="turn_duration")


def compute_phase_timing(session: Session) -> dict[str, Any]:
    """Compute phase span, active time, and inter-turn time per phase.

    For each phase ``p``:

    * ``phase_span_seconds_<p>``: ``max completedAt_i - min timestamp_i``
      over requests with ``phase(i) == p``.
    * ``phase_active_time_seconds_<p>``: sum of individual turn durations
      within phase ``p``.
    * ``phase_inter_turn_time_seconds_<p>``: ``span - active``; an
      approximation of user thinking and composition time between turns
      within the phase.

    Args:
        session: The assembled session.

    Returns:
        A dict with nine numeric fields covering ``planning``,
        ``implementation``, and ``other``. Phases with no contributing
        requests report zeros for all three of their fields.
    """
    output: dict[str, Any] = {}
    for phase in (PLANNING_PHASE, IMPLEMENTATION_PHASE, OTHER_PHASE):
        span_ms, active_ms = _phase_span_and_active(session, phase)
        output[f"phase_span_seconds_{phase}"] = span_ms / _MILLISECONDS_PER_SECOND
        output[f"phase_active_time_seconds_{phase}"] = active_ms / _MILLISECONDS_PER_SECOND
        output[f"phase_inter_turn_time_seconds_{phase}"] = (
            max(span_ms - active_ms, 0) / _MILLISECONDS_PER_SECOND
        )
    return output


def compute_role_turn_duration(
    requests: tuple[AnnotatedRequest, ...],
    role: str,
) -> dict[str, Any]:
    """Compute turn-duration distribution for a single APM role.

    Args:
        requests: The session's annotated requests.
        role: ``planner``, ``manager``, or ``worker``.

    Returns:
        Same shape as :func:`compute_turn_duration`, restricted to
        requests whose ``role`` matches the argument.
    """
    durations = _turn_durations_seconds(
        tuple(req for req in requests if req.role == role)
    )
    return _distribution_summary(durations, prefix="turn_duration")


def compute_role_inter_turn_time(
    requests: tuple[AnnotatedRequest, ...],
    role: str,
) -> dict[str, Any]:
    """Compute span, active time, and inter-turn time for a single APM role.

    Args:
        requests: The session's annotated requests.
        role: ``planner``, ``manager``, or ``worker``.

    Returns:
        A dict with ``span_seconds``, ``active_time_seconds``, and
        ``inter_turn_time_seconds`` for the role's requests. Role with
        no contributing requests yields zeros.
    """
    role_requests = tuple(
        req for req in requests
        if req.role == role and req.raw.completed_at_ms is not None
    )
    if not role_requests:
        return {
            "span_seconds": 0.0,
            "active_time_seconds": 0.0,
            "inter_turn_time_seconds": 0.0,
        }
    min_start = min(r.raw.timestamp_ms for r in role_requests)
    max_end = max(r.raw.completed_at_ms for r in role_requests if r.raw.completed_at_ms is not None)
    span_ms = max_end - min_start
    active_ms = sum(
        (r.raw.completed_at_ms - r.raw.timestamp_ms)
        for r in role_requests
        if r.raw.completed_at_ms is not None
    )
    return {
        "span_seconds": span_ms / _MILLISECONDS_PER_SECOND,
        "active_time_seconds": active_ms / _MILLISECONDS_PER_SECOND,
        "inter_turn_time_seconds": max(span_ms - active_ms, 0) / _MILLISECONDS_PER_SECOND,
    }


def _session_max_end(session: Session) -> int:
    """Return the latest observed end time across the session in ms.

    Falls back to the latest request ``timestamp`` when no request has a
    terminal-state ``completedAt``; this keeps the session duration
    well-defined even if every response was pending at export time.
    """
    completed = [
        r.raw.completed_at_ms for r in session.requests
        if r.raw.completed_at_ms is not None
    ]
    if completed:
        return max(completed)
    return max(r.raw.timestamp_ms for r in session.requests)


def _turn_durations_seconds(
    requests: tuple[AnnotatedRequest, ...],
) -> list[float]:
    """Extract per-request turn durations in seconds, skipping unfinished turns."""
    return [
        (req.raw.completed_at_ms - req.raw.timestamp_ms) / _MILLISECONDS_PER_SECOND
        for req in requests
        if req.raw.completed_at_ms is not None
    ]


def _phase_span_and_active(session: Session, phase: str) -> tuple[int, int]:
    """Return ``(span_ms, active_ms)`` for a single phase."""
    phase_requests = [
        r for r in session.requests
        if r.phase == phase and r.raw.completed_at_ms is not None
    ]
    if not phase_requests:
        return 0, 0
    min_start = min(r.raw.timestamp_ms for r in phase_requests)
    max_end = max(
        r.raw.completed_at_ms for r in phase_requests if r.raw.completed_at_ms is not None
    )
    span_ms = max_end - min_start
    active_ms = sum(
        (r.raw.completed_at_ms - r.raw.timestamp_ms)
        for r in phase_requests
        if r.raw.completed_at_ms is not None
    )
    return span_ms, active_ms


def _distribution_summary(values: list[float], prefix: str) -> dict[str, Any]:
    """Return mean, median, 95th percentile, stdev, and sample-size fields.

    Args:
        values: Sample values; the caller has already converted to the
            target unit.
        prefix: Field-name prefix to apply; the resulting keys are
            ``mean_<prefix>_seconds``, ``<prefix>_p50_seconds``,
            ``<prefix>_p95_seconds``, ``<prefix>_stdev_seconds``, and
            ``<prefix>_sample_size``.
    """
    if not values:
        return {
            f"mean_{prefix}_seconds": 0.0,
            f"{prefix}_p50_seconds": 0.0,
            f"{prefix}_p95_seconds": 0.0,
            f"{prefix}_stdev_seconds": 0.0,
            f"{prefix}_sample_size": 0,
        }
    mean_value = sum(values) / len(values)
    p50 = float(median(values))
    p95 = _percentile(values, 0.95)
    stdev = float(pstdev(values)) if len(values) > 1 else 0.0
    return {
        f"mean_{prefix}_seconds": mean_value,
        f"{prefix}_p50_seconds": p50,
        f"{prefix}_p95_seconds": p95,
        f"{prefix}_stdev_seconds": stdev,
        f"{prefix}_sample_size": len(values),
    }


def _percentile(values: list[float], fraction: float) -> float:
    """Return a linearly-interpolated percentile of the sample.

    Args:
        values: Sample values. Must be non-empty.
        fraction: Target fraction in ``[0, 1]``; for the 95th percentile
            pass ``0.95``.

    Returns:
        The interpolated percentile value.
    """
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low_index = int(position)
    high_index = min(low_index + 1, len(ordered) - 1)
    weight = position - low_index
    return ordered[low_index] * (1 - weight) + ordered[high_index] * weight
