#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Input-bucket metrics: session-level shares and magnitudes,
phase-conditional shares, and a short-threshold sensitivity sweep.
"""

from __future__ import annotations

from typing import Any

from ..buckets import (
    BUCKET_PROTOCOL,
    BUCKET_SHORT,
    BUCKET_STANDARD,
    SHORT_THRESHOLD_SWEEP,
    classify_bucket,
)
from ..schema import IMPLEMENTATION_PHASE, PLANNING_PHASE
from ..session import AnnotatedRequest, Session

_BUCKETS: tuple[str, ...] = (BUCKET_PROTOCOL, BUCKET_SHORT, BUCKET_STANDARD)


def compute_session_bucket_shares(session: Session, short_threshold: int) -> dict[str, Any]:
    """Compute session-level bucket shares and average characters per bucket.

    Args:
        session: The assembled session.
        short_threshold: Upper bound on text length for the ``short``
            bucket, in characters.

    Returns:
        A dict with ``ratio_<bucket>_inputs`` and ``avg_chars_<bucket>``
        for every bucket plus ``total_user_messages``. Empty buckets
        report ratio and average of ``0.0``.
    """
    counts, char_totals = _bucket_counts_and_chars(session.requests, short_threshold)
    total = sum(counts.values())
    output: dict[str, Any] = {"total_user_messages": total}
    for bucket in _BUCKETS:
        count = counts[bucket]
        output[f"ratio_{bucket}_inputs"] = count / total if total > 0 else 0.0
        output[f"avg_chars_{bucket}"] = (
            char_totals[bucket] / count if count > 0 else 0.0
        )
    return output


def compute_phase_bucket_shares(session: Session, short_threshold: int) -> dict[str, Any]:
    """Compute bucket shares conditioned on phase, for planning and implementation.

    Args:
        session: The assembled session.
        short_threshold: Upper bound on text length for the ``short``
            bucket, in characters.

    Returns:
        A dict with ``ratio_<bucket>_inputs_<phase>`` for every bucket
        and for ``planning`` and ``implementation``, plus
        ``planning_user_messages`` and ``implementation_user_messages``.
        A phase with no user messages reports every ratio as ``0.0``.
    """
    output: dict[str, Any] = {}
    for phase in (PLANNING_PHASE, IMPLEMENTATION_PHASE):
        phase_requests = tuple(r for r in session.requests if r.phase == phase)
        counts, _ = _bucket_counts_and_chars(phase_requests, short_threshold)
        total = sum(counts.values())
        output[f"{phase}_user_messages"] = total
        for bucket in _BUCKETS:
            count = counts[bucket]
            output[f"ratio_{bucket}_inputs_{phase}"] = (
                count / total if total > 0 else 0.0
            )
    return output


def compute_role_bucket_shares(
    requests: tuple[AnnotatedRequest, ...],
    role: str,
    short_threshold: int,
) -> dict[str, Any]:
    """Compute bucket shares for one APM role.

    Args:
        requests: The session's annotated requests.
        role: ``planner``, ``manager``, or ``worker``.
        short_threshold: Upper bound on text length for the ``short``
            bucket, in characters.

    Returns:
        A dict with ``ratio_<bucket>_inputs`` for every bucket plus
        ``user_messages`` (the role-scoped denominator). A role with
        no requests reports zeros.
    """
    role_requests = tuple(r for r in requests if r.role == role)
    counts, _ = _bucket_counts_and_chars(role_requests, short_threshold)
    total = sum(counts.values())
    output: dict[str, Any] = {"user_messages": total}
    for bucket in _BUCKETS:
        count = counts[bucket]
        output[f"ratio_{bucket}_inputs"] = count / total if total > 0 else 0.0
    return output


def compute_short_threshold_sensitivity(session: Session) -> dict[str, Any]:
    """Compute bucket shares across every threshold in the sweep.

    At each threshold the sweep reports the three session-level bucket
    ratios and the directional sub-metric
    ``ratio_standard_inputs_implementation``. Per-role and
    non-directional phase-conditional ratios are not repeated across the
    sweep; they appear once at the primary threshold elsewhere in the
    report.

    Args:
        session: The assembled session.

    Returns:
        A dict keyed by threshold (as integer). Each value is a dict
        with ``ratio_protocol_inputs``, ``ratio_short_inputs``,
        ``ratio_standard_inputs``, and ``ratio_standard_inputs_implementation``.
    """
    output: dict[str, Any] = {}
    for threshold in SHORT_THRESHOLD_SWEEP:
        session_counts, _ = _bucket_counts_and_chars(session.requests, threshold)
        session_total = sum(session_counts.values())
        impl_requests = tuple(r for r in session.requests if r.phase == IMPLEMENTATION_PHASE)
        impl_counts, _ = _bucket_counts_and_chars(impl_requests, threshold)
        impl_total = sum(impl_counts.values())
        output[str(threshold)] = {
            f"ratio_{bucket}_inputs": (
                session_counts[bucket] / session_total if session_total > 0 else 0.0
            )
            for bucket in _BUCKETS
        } | {
            "ratio_standard_inputs_implementation": (
                impl_counts[BUCKET_STANDARD] / impl_total if impl_total > 0 else 0.0
            )
        }
    return output


def _bucket_counts_and_chars(
    requests: tuple[AnnotatedRequest, ...],
    short_threshold: int,
) -> tuple[dict[str, int], dict[str, int]]:
    """Tally bucket counts and total characters by bucket across a request set."""
    counts: dict[str, int] = {bucket: 0 for bucket in _BUCKETS}
    char_totals: dict[str, int] = {bucket: 0 for bucket in _BUCKETS}
    for annotated in requests:
        bucket = classify_bucket(
            annotated.raw.message_text,
            annotated.raw.slash_commands,
            short_threshold,
        )
        counts[bucket] += 1
        char_totals[bucket] += len(annotated.raw.message_text)
    return counts, char_totals
