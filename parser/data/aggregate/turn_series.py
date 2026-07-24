# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Turn-level record assembly and phase membership for the canonical artifact.

This module owns the ``turns`` array of the metrics artifact and the
helpers that resolve each turn's primary phase, role, and per-phase
request distribution. The artifact-wide assembly lives in ``report``;
this module is the per-turn renderer it calls into.

It also owns phase membership at record granularity: the running-phase
walk, the records each phase scope aggregates, and the per-turn segments
a phase scope's wall-clock is measured over. Extensive measures follow
the phase in force at each record; point-in-time measures follow the
turn's starting prompt.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ...rates import (
    CATEGORIES,
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    RateTable,
    cost_in_usd,
)
from ..buckets import classify_bucket
from ..commands import PHASE_OTHER
from ..schema import Record, assistant_request_id, user_prompt_text
from ..session import ConversationView, Session, iso_or_none
from ..turns import Turn
from .call_records import iter_main_call_entries, iter_main_request_records

PHASE_KEYS: tuple[str, ...] = ("planning", "implementation", "other")


@dataclass(frozen=True)
class PhaseSegment:
    """One contiguous stretch of a turn spent in a single phase.

    Attributes:
        phase: The stretch's phase label.
        start: The turn's start for a turn's first segment, otherwise the
            timestamp of the first call of this phase.
        end: The turn's end for a turn's last segment, otherwise the next
            segment's start.
        turn: The turn the stretch is part of.
    """

    phase: str
    start: datetime
    end: datetime
    turn: Turn


def build_turn_records(session: Session, short_threshold: int) -> list[dict[str, Any]]:
    """Render the per-turn record-level output array.

    Each turn carries a ``phase_request_share`` dict with the three
    phase keys (``planning``, ``implementation``, ``other``). The
    values are integer counts of the turn's non-synthetic
    non-API-error main requests (deduplicated by ``requestId``,
    matching the selection rule in ``data.aggregate.call_records.iter_main_request_records``)
    bucketed by each request's phase. A request's phase is the phase
    of its first emitting assistant record in the conversation file's
    document order, looked up against a per-conversation phase index
    derived from the assigner output. The turn-level ``phase`` field
    still carries the phase of the turn's starting prompt.

    Each turn also carries a ``prompt_bucket`` (``protocol``,
    ``short``, or ``standard``): the content bucket of the turn's
    starting prompt, classified by the same text-and-threshold path
    that the turn-prompt metric uses to compute
    ``turn_prompts_bucket_shares`` (see
    ``data.aggregate.counts.compute_user_input_counts``), so the
    per-turn labels aggregate exactly to those shares within a scope.
    Its ``steer_count`` includes only user-authored steers associated
    with the turn; system-generated queue events remain excluded.

    Args:
        session: The session whose turns are being rendered.
        short_threshold: Upper bound (exclusive) on prompt length for
            the ``short`` bucket, in characters; the same value the
            turn-prompt metrics use.

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
                "prompt_bucket": _prompt_bucket_of_turn(turn, short_threshold),
                "start_timestamp": iso_or_none(turn.start_timestamp),
                "end_timestamp": iso_or_none(turn.end_timestamp),
                "duration_seconds": (turn.end_timestamp - turn.start_timestamp).total_seconds(),
                "steer_count": sum(event.is_user_authored for event in turn.steer_events),
                "request_count": _count_turn_requests(turn),
                "phase_request_share": _phase_request_share(turn, request_phase_index),
            }
        )
    return records


def build_call_series(session: Session, rate_table: RateTable) -> list[dict[str, Any]]:
    """Render the per-call canonical series for the data artifact.

    Walks the session's turns in order and, for each turn, emits one entry
    per main call in the turn (the same population the turn's
    ``request_count`` counts, via ``call_records.iter_main_call_entries``).
    Each entry carries the call's join key (``request_id``), resolved
    model, ISO timestamp, the five-category token bag spread to flat keys,
    a parallel ``*_cost_usd`` field per category (that category's tokens
    priced against the call's model in isolation), and its turn, phase, and
    role membership. A call's phase is the phase recorded for its
    ``requestId`` in the per-conversation phase index; its role is the role
    of the turn it belongs to.

    A main call that precedes the first turn-starting prompt belongs to no
    turn and is therefore not in the series; the series' per-turn count
    equals each turn's ``request_count`` by construction.

    Args:
        session: The session whose calls are being rendered.
        rate_table: The rate table each category's tokens are priced against.

    Returns:
        One dict per main call, in turn order then record order within a
        turn.
    """
    request_phase_by_conversation = _build_request_phase_index(session)
    series: list[dict[str, Any]] = []
    for turn in session.turns:
        request_phase_index = request_phase_by_conversation.get(turn.conversation_path, {})
        role_key = role_of_turn(session, turn)
        turn_id = turn.starting_prompt.uuid
        for entry in iter_main_call_entries(turn.records):
            row: dict[str, Any] = {
                "request_id": entry.request_id,
                "model": entry.canonical_model,
                "timestamp": iso_or_none(entry.timestamp),
                "input": entry.token_bag[CATEGORY_INPUT],
                "output": entry.token_bag[CATEGORY_OUTPUT],
                "cache_read": entry.token_bag[CATEGORY_CACHE_READ],
                "cache_5m": entry.token_bag[CATEGORY_CACHE_5M],
                "cache_1h": entry.token_bag[CATEGORY_CACHE_1H],
                "turn": turn_id,
                "phase": request_phase_index.get(entry.request_id, PHASE_OTHER),
                "role": role_key,
            }
            for category in CATEGORIES:
                row[f"{category}_cost_usd"] = cost_in_usd(
                    rate_table,
                    entry.canonical_model,
                    {category: entry.token_bag[category]},
                )
            series.append(row)
    return series


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


def iter_record_phases(view: ConversationView) -> Iterator[tuple[Record, str]]:
    """Yield each of a conversation's records paired with the phase in force at it.

    Walks records in document order tracking a running phase, bumped
    whenever a record's uuid appears in the view's ``phase_by_record_uuid``
    map (user prompts and steer enqueues set the prompt's phase;
    Skill-tagged request groups override every same-``requestId`` assistant
    record). The running phase starts at ``other``, so records preceding
    the conversation's first phase-setting prompt are yielded as ``other``.

    For APM each user prompt sets the role phase, so every record inherits
    it. For Spec-kit the most recent prompt or steer holds until a Skill
    request group rewrites it.

    Args:
        view: The conversation view to walk.

    Yields:
        ``(record, phase)`` pairs in document order.
    """
    current_phase: str = PHASE_OTHER
    for record in view.conversation.records:
        if record.uuid is not None:
            tagged = view.phase_by_record_uuid.get(record.uuid)
            if tagged is not None:
                current_phase = tagged
        yield record, current_phase


def _build_request_phase_index(session: Session) -> dict[str, dict[str, str]]:
    """Build a per-conversation ``requestId -> phase`` index.

    The phase observed at a request's first assistant record, per the
    record-level walk in ``iter_record_phases``, becomes that request's
    phase.
    """
    index: dict[str, dict[str, str]] = {}
    for view in session.views:
        per_request: dict[str, str] = {}
        for record, phase in iter_record_phases(view):
            request_id = assistant_request_id(record)
            if request_id is None:
                continue
            if request_id in per_request:
                continue
            per_request[request_id] = phase
        index[view.conversation.path] = per_request
    return index


def records_in_phase(session: Session, phase: str) -> list[Record]:
    """Return the session's records belonging to ``phase``.

    Every record carries a phase, so the three phase selections partition
    the session's records exactly.

    Args:
        session: The session to select from.
        phase: The phase label to select.

    Returns:
        The phase's records, in view order then document order.
    """
    return [
        record
        for view in session.views
        for record, record_phase in iter_record_phases(view)
        if record_phase == phase
    ]


def build_phase_segments(session: Session) -> tuple[PhaseSegment, ...]:
    """Split every turn of the session into its per-phase segments.

    A turn's segments tile its interval, so the session's segments tile
    the same wall-clock its turns do.

    Args:
        session: The session whose turns to split.

    Returns:
        Segments in turn order, then phase order within a turn.
    """
    phase_by_record: dict[int, str] = {}
    for view in session.views:
        for record, phase in iter_record_phases(view):
            phase_by_record[id(record)] = phase
    segments: list[PhaseSegment] = []
    for turn in session.turns:
        segments.extend(_segments_of_turn(session, turn, phase_by_record))
    return tuple(segments)


def segments_in_phase(
    segments: tuple[PhaseSegment, ...],
    phase: str,
) -> list[tuple[datetime, datetime]]:
    """Return the ``(start, end)`` intervals of the segments belonging to ``phase``."""
    return [(segment.start, segment.end) for segment in segments if segment.phase == phase]


def closing_phase_by_turn(segments: tuple[PhaseSegment, ...]) -> dict[int, str]:
    """Map each turn's identity to the phase of its last segment.

    Args:
        segments: The session's segments, in turn order.

    Returns:
        ``id(turn) -> phase`` for every turn covered by ``segments``.
    """
    return {id(segment.turn): segment.phase for segment in segments}


def opening_phase_by_turn(segments: tuple[PhaseSegment, ...]) -> dict[int, str]:
    """Map each turn's identity to the phase of its first segment.

    Args:
        segments: The session's segments, in turn order.

    Returns:
        ``id(turn) -> phase`` for every turn covered by ``segments``.
    """
    opening: dict[int, str] = {}
    for segment in segments:
        opening.setdefault(id(segment.turn), segment.phase)
    return opening


def _segments_of_turn(
    session: Session,
    turn: Turn,
    phase_by_record: dict[int, str],
) -> list[PhaseSegment]:
    """Split one turn into its per-phase segments.

    The turn opens in its starting prompt's phase, so a turn whose calls
    stay in that phase yields one segment covering the whole turn. Each
    call whose phase differs from the running one closes the open segment
    at that call's timestamp and opens the next there.

    A call without a timestamp cannot position a boundary, so it leaves the
    running phase alone and the transition stays pending for the next
    timestamped call of that phase to place.

    The two clamps are not symmetric. A boundary at or before the open
    segment's start means the phase already held there, so it takes the
    open segment over. A boundary at or after the turn's end means the new
    phase occupies no wall-clock inside the turn, so it is dropped and the
    open segment keeps the phase it had.

    Args:
        session: The session the turn belongs to.
        turn: The turn to split.
        phase_by_record: Session-wide record-identity to phase map.

    Returns:
        The turn's segments in order; always at least one.
    """
    opening_phase = phase_of_turn(session, turn)
    boundaries: list[tuple[str, datetime]] = []
    running_phase = opening_phase
    for record in iter_main_request_records(turn.records):
        phase = phase_by_record.get(id(record), running_phase)
        if phase == running_phase or record.timestamp is None:
            continue
        running_phase = phase
        boundaries.append((phase, record.timestamp))

    segments: list[PhaseSegment] = []
    segment_start = turn.start_timestamp
    segment_phase = opening_phase
    for phase, boundary in boundaries:
        if boundary >= turn.end_timestamp:
            continue
        if boundary <= segment_start:
            segment_phase = phase
            continue
        segments.append(PhaseSegment(segment_phase, segment_start, boundary, turn))
        segment_start = boundary
        segment_phase = phase
    segments.append(PhaseSegment(segment_phase, segment_start, turn.end_timestamp, turn))
    return segments


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


def _prompt_bucket_of_turn(turn: Turn, short_threshold: int) -> str:
    """Return the content bucket of a turn's starting prompt.

    Reuses the turn-prompt metric's classification path exactly: the
    starting-prompt text comes from ``user_prompt_text`` and is fed to
    ``classify_bucket`` with the same threshold, so the per-turn label
    matches the input the ``turn_prompts_bucket_shares`` aggregate
    counts for this turn. The classifier is framework-agnostic (it
    keys on ``apm-*``/``speckit-*`` command markers in the text), so a
    non-protocol opener lands in ``short`` or ``standard`` by length
    rather than being mistaken for a protocol input.
    """
    return classify_bucket(user_prompt_text(turn.starting_prompt), short_threshold)


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
