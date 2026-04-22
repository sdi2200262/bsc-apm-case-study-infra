#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Request-count metrics.

The economic primary count is the total number of user-initiated
requests across every conversation file belonging to the session. Its
phase breakdown characterises how much of the session's request budget
each framework phase consumed.
"""

from __future__ import annotations

from typing import Any

from ..schema import IMPLEMENTATION_PHASE, OTHER_PHASE, PLANNING_PHASE
from ..session import Session


def compute_request_counts(session: Session) -> dict[str, Any]:
    """Compute the session-wide request count and its phase breakdown.

    Args:
        session: The assembled session.

    Returns:
        A dict with keys ``session_request_count``,
        ``planning_request_count``, ``implementation_request_count``,
        ``other_request_count``, and the three matching share fields
        (``planning_request_share``, ``implementation_request_share``,
        ``other_request_share``). Shares are ratios in ``[0, 1]``;
        when ``session_request_count`` is zero, shares are zero.
    """
    total = len(session.requests)
    per_phase: dict[str, int] = {
        PLANNING_PHASE: 0,
        IMPLEMENTATION_PHASE: 0,
        OTHER_PHASE: 0,
    }
    for annotated in session.requests:
        per_phase[annotated.phase] = per_phase.get(annotated.phase, 0) + 1

    def share(count: int) -> float:
        return count / total if total > 0 else 0.0

    return {
        "session_request_count": total,
        "planning_request_count": per_phase[PLANNING_PHASE],
        "implementation_request_count": per_phase[IMPLEMENTATION_PHASE],
        "other_request_count": per_phase[OTHER_PHASE],
        "planning_request_share": share(per_phase[PLANNING_PHASE]),
        "implementation_request_share": share(per_phase[IMPLEMENTATION_PHASE]),
        "other_request_share": share(per_phase[OTHER_PHASE]),
    }
