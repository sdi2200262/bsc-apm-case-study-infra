#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Per-role metrics for APM conversations (Planner, Manager, Worker).

Per-role metrics are defined only for APM; Spec-kit sessions do not
expose a role dimension. When the parser runs on a Spec-kit session the
caller skips this module's outputs.
"""

from __future__ import annotations

from typing import Any

from ..schema import FRAMEWORK_APM, MANAGER_ROLE, PLANNER_ROLE, WORKER_ROLE
from ..session import Session
from .buckets import compute_role_bucket_shares
from .timing import compute_role_inter_turn_time, compute_role_turn_duration

APM_ROLES: tuple[str, ...] = (PLANNER_ROLE, MANAGER_ROLE, WORKER_ROLE)


def compute_per_role_metrics(session: Session, short_threshold: int) -> dict[str, Any]:
    """Compute per-role timing, inter-turn time, and bucket shares for APM.

    Args:
        session: The assembled session.
        short_threshold: Upper bound on text length for the ``short``
            bucket, in characters.

    Returns:
        A dict keyed by role (``planner``, ``manager``, ``worker``)
        with each value being a dict of that role's timing and bucket
        fields. For non-APM sessions the returned dict is empty.
    """
    if session.framework != FRAMEWORK_APM:
        return {}

    output: dict[str, Any] = {}
    for role in APM_ROLES:
        timing = compute_role_turn_duration(session.requests, role)
        inter = compute_role_inter_turn_time(session.requests, role)
        buckets = compute_role_bucket_shares(session.requests, role, short_threshold)
        output[role] = timing | inter | buckets
    return output
