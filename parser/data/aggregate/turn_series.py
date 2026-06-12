# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Turn-level record assembly and phase-share computation for the canonical artifact.

This module owns the ``turns`` array of the metrics artifact and the
helpers that resolve each turn's primary phase, role, and per-phase
request distribution. The artifact-wide assembly lives in
``report``; this module is the per-turn renderer it calls into.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..commands import PHASE_OTHER
from ..schema import assistant_request_id
from ..session import Session, iso_or_none
from ..turns import Turn
from .call_records import iter_main_request_records

PHASE_KEYS: tuple[str, ...] = ("planning", "implementation", "other")


def build_turn_records(session: Session) -> list[dict[str, Any]]:
    """Render the per-turn record-level output array.

    Each turn carries a ``phase_request_share`` dict with the three
    phase keys (``planning``, ``implementation``, ``other``). The
    values are integer counts of the turn's non-synthetic
    non-API-error main requests (deduplicated by ``requestId``,
    matching the recipe in ``metrics.economic._sum_main_from_records``)
    bucketed by each request's phase. A request's phase is the phase
    of its first emitting assistant record in the conversation file's
    document order, looked up against a per-conversation phase index
    derived from the assigner output. The turn-level ``phase`` field
    still carries the phase of the turn's starting prompt.

    Args:
        session: The session whose turns are being rendered.

    Returns:
        One dict per turn in ``session.turns``.
    """
    request_phase_by_conversation = _build_request_phase_index(session)
    records: list[dict[str, Any]] = []
    for turn in session.turns:
        request_phase_index = request_phase_by_conversation.get(turn.conversation_path, {})
        records.append(
            {
                "turn_id": turn.starting_prompt.uuid,
                "conversation_id": _conversation_session_id(session, turn.conversation_path),
                "role_key": role_of_turn(session, turn),
                "phase": phase_of_turn(session, turn),
                "start_timestamp": iso_or_none(turn.start_timestamp),
                "end_timestamp": iso_or_none(turn.end_timestamp),
                "duration_seconds": (turn.end_timestamp - turn.start_timestamp).total_seconds(),
                "steer_count": len(turn.steer_events),
                "request_count": _count_turn_requests(turn),
                "phase_request_share": _phase_request_share(turn, request_phase_index),
            }
        )
    return records


def turns_in_phase(session: Session, phase: str) -> Iterable[Turn]:
    """Yield turns whose starting-prompt phase matches ``phase``."""
    for turn in session.turns:
        if phase_of_turn(session, turn) == phase:
            yield turn


def turns_in_role(session: Session, role_key: str) -> Iterable[Turn]:
    """Yield turns whose conversation has the given role key."""
    for view in session.views:
        if view.role != role_key:
            continue
        for turn in session.turns:
            if turn.conversation_path == view.conversation.path:
                yield turn


def phase_of_turn(session: Session, turn: Turn) -> str:
    """Return the phase label for a turn."""
    starting_uuid = turn.starting_prompt.uuid
    for view in session.views:
        if view.conversation.path != turn.conversation_path:
            continue
        if starting_uuid and starting_uuid in view.phase_by_record_uuid:
            return view.phase_by_record_uuid[starting_uuid]
        return PHASE_OTHER
    return PHASE_OTHER


def role_of_turn(session: Session, turn: Turn) -> str:
    """Return the role key for a turn."""
    for view in session.views:
        if view.conversation.path == turn.conversation_path:
            return view.role
    return ""


def _build_request_phase_index(session: Session) -> dict[str, dict[str, str]]:
    """Build a per-conversation ``requestId -> phase`` index.

    For each conversation file the function walks records in document
    order and tracks a running phase: it is bumped whenever a record's
    uuid appears in the conversation view's ``phase_by_record_uuid``
    map (user prompts and steer enqueues set the prompt's phase;
    Skill-tagged request groups override every same-``requestId``
    assistant record). The phase observed at a request's first
    assistant record becomes that request's phase. For APM the
    running phase is set by each user prompt to the role phase, so
    every request inherits the role's phase. For Spec-kit the phase
    is set by the most recent prompt or steer until a Skill request
    group rewrites it.
    """
    index: dict[str, dict[str, str]] = {}
    for view in session.views:
        per_request: dict[str, str] = {}
        current_phase: str = PHASE_OTHER
        for record in view.conversation.records:
            if record.uuid is not None:
                tagged = view.phase_by_record_uuid.get(record.uuid)
                if tagged is not None:
                    current_phase = tagged
            request_id = assistant_request_id(record)
            if request_id is None:
                continue
            if request_id in per_request:
                continue
            per_request[request_id] = current_phase
        index[view.conversation.path] = per_request
    return index


def _phase_request_share(
    turn: Turn,
    request_phase_index: dict[str, str],
) -> dict[str, int]:
    """Return the per-phase request count for a turn.

    Buckets each unique main-call ``requestId`` in the turn by the
    phase recorded for it in ``request_phase_index``. Requests whose
    phase falls outside the three canonical labels are dropped to
    keep the dict shape uniform.
    """
    buckets: dict[str, int] = {phase: 0 for phase in PHASE_KEYS}
    for record in iter_main_request_records(turn.records):
        request_id = record.payload["requestId"]
        phase = request_phase_index.get(request_id, PHASE_OTHER)
        if phase in buckets:
            buckets[phase] += 1
    return buckets


def _count_turn_requests(turn: Turn) -> int:
    """Return the count of unique main-call requestIds in a turn.

    Computed independently of ``_phase_request_share`` so an
    invariant check can compare the share's sum against this count
    and catch builder divergence.
    """
    return sum(1 for _ in iter_main_request_records(turn.records))


def _conversation_session_id(session: Session, conversation_path: str) -> str | None:
    """Return the sessionId for a conversation path, or ``None`` when not found."""
    for view in session.views:
        if view.conversation.path == conversation_path:
            return view.conversation.session_id
    return None
