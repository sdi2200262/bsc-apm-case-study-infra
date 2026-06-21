# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Assemble a participant submission into a typed ``Session``.

A submission is one or more conversation files for the same participant
session. A Spec-kit submission carries a single conversation by canonical
workflow; an APM submission carries one Planner conversation, one or more
Manager conversations (more when handoffs occurred), and one or more
Worker conversations (one per Worker initiated, plus handoff
continuations).

Three responsibilities sit here, above the per-conversation loader work
and the framework role and phase computation:

1. Number each APM conversation's role and key it. The role comes from
   ``apm_roles.assign_apm_roles``; this module numbers roles sequentially
   by first-record timestamp ascending, never keying on a
   participant-supplied identifier. Worker identifiers are typed by hand
   on ``/apm-3-initiate-worker <id>``, so keying on the id would split one
   semantic worker into two on a re-invocation typo. The verbatim first
   command of each conversation is preserved so a reviewer can spot and
   merge typo-different role-keys.

2. Partition each framework assigner's per-record phase output back per
   conversation file and attach it to the view; no phase computation of
   its own.

3. Compute the session identity facts surfaced through the report layer's
   session-metadata block.

The session-duration cap applied here at load time lives in
``session_cap``; ``load_session`` calls it before view assembly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .apm_roles import ConversationRole, assign_apm_roles
from .commands import (
    FRAMEWORK_APM,
    FRAMEWORK_SPECKIT,
)
from .conversation import (
    Conversation,
    build_conversation,
    discover_conversation_files,
    parse_conversation_records,
)
from .prompts import is_user_authored_prompt
from .reset_events import reset_event_blocks
from .schema import (
    RECORD_TYPE_ASSISTANT,
    SYNTHETIC_MODEL_MARKER,
    Record,
    SchemaError,
    is_synthetic_assistant,
)
from .session_cap import (
    DEFAULT_CAP_HOURS,
    CapFilter,
    apply_session_cap,
    build_cap_filter,
)
from .speckit_phases import assign_speckit_phases
from .turns import Turn, derive_turns


@dataclass(frozen=True)
class ConversationView:
    """Per-conversation view assembled at session level.

    Attributes:
        conversation: The loaded ``Conversation`` from the loader.
        role: Role label. For APM, the base role plus a sequential index
            suffix (``planner-1``, ``manager-2``, ``worker-3``), or
            ``unassigned-N`` when the first slash command is not a role
            initiator. For Spec-kit, ``conversation-N`` (no role concept).
        first_command: Verbatim first slash command observed in the
            conversation, with arguments, typos, and whitespace as the
            participant wrote them. Empty string when none appears.
        first_command_record: The record carrying ``first_command``,
            or ``None`` when no such record exists.
        first_record_timestamp: Earliest user-authored prompt timestamp
            in the conversation; falls back to the earliest timestamped
            record. Used to order conversations for role numbering.
        phase_by_record_uuid: Phase label keyed by record uuid. For APM,
            each genuine user-prompt record's role phase; for Spec-kit,
            the per-conversation slice of
            ``speckit_phases.PhaseWalkResult.phase_by_uuid``.
    """

    conversation: Conversation
    role: str
    first_command: str
    first_command_record: Record | None
    first_record_timestamp: datetime | None
    phase_by_record_uuid: dict[str, str]


@dataclass(frozen=True)
class Session:
    """A complete participant submission, ready for metric computation.

    Attributes:
        framework: ``FRAMEWORK_APM`` or ``FRAMEWORK_SPECKIT``, set by the
            strict ``--framework`` flag at load time.
        views: Per-conversation views in input order (filesystem order
            from the directory walk; a single-file caller gets a one-element
            tuple).
        turns: Every derived turn across every conversation, in global
            timestamp order. Each turn knows its conversation file via
            ``Turn.conversation_path``.
        backward_skill_invocations: Chronological log of backward Skill
            events from the Spec-kit phase assigner; entry schema on
            ``speckit_phases.PhaseWalkResult.backward_skill_invocations``.
            Empty for APM and for Spec-kit with no backward invocations.
        cap_filter: The outcome of the session-duration cap applied at
            load time. Its ``dropped`` tuple is empty for a session with
            no records beyond the cutoff, so the views and turns are then
            byte-identical to an uncapped load. A cap-overrun session
            carries its dropped records here; its views, turns, and
            aggregates are built from the surviving records, with the
            loader's per-conversation indices rebuilt to match.
    """

    framework: str
    views: tuple[ConversationView, ...]
    turns: tuple[Turn, ...]
    backward_skill_invocations: tuple[dict[str, Any], ...]
    cap_filter: CapFilter


def load_session(path: Path, framework: str, cap_hours: float = DEFAULT_CAP_HOURS) -> Session:
    """Load a participant submission and assemble it into a ``Session``.

    The session-duration cap is applied before view assembly via
    ``session_cap.apply_session_cap``; every record-derived index and
    downstream aggregate is then computed against the survivors. A session
    whose records all fall within the cap is assembled identically to an
    uncapped load.

    Args:
        path: Either a single ``*.jsonl`` file or a directory of
            ``*.jsonl`` files copied straight from
            ``~/.claude/projects/<dashed-cwd>/``.
        framework: ``FRAMEWORK_APM`` or ``FRAMEWORK_SPECKIT``, taken
            verbatim from the caller's strict flag and never inferred.
        cap_hours: The session-duration cap in hours. A non-positive value
            disables the cap.

    Returns:
        A populated ``Session``.

    Raises:
        SchemaError: When the path does not resolve to JSONL files, when
            any file fails to parse, or when ``framework`` is not one of
            the two recognised values.
        OSError: When a file cannot be read.
    """
    if framework not in (FRAMEWORK_APM, FRAMEWORK_SPECKIT):
        raise SchemaError(
            f"unknown framework {framework!r}; expected {FRAMEWORK_APM!r} or {FRAMEWORK_SPECKIT!r}"
        )
    files = discover_conversation_files(path)
    parsed = [(str(p.resolve()), parse_conversation_records(p)) for p in files]
    kept_parsed, dropped_by_path, cutoff, anchor = apply_session_cap(parsed, cap_hours)
    conversations = [build_conversation(Path(p), records) for p, records in kept_parsed]
    backward_skill_invocations: tuple[dict[str, Any], ...] = ()
    if framework == FRAMEWORK_APM:
        views = _build_apm_views(conversations)
    else:
        views, backward_skill_invocations = _build_speckit_views(conversations)
    turns = _collect_turns(views)
    cap_filter = build_cap_filter(views, cap_hours, anchor, cutoff, dropped_by_path)
    return Session(
        framework=framework,
        views=views,
        turns=turns,
        backward_skill_invocations=backward_skill_invocations,
        cap_filter=cap_filter,
    )


def _build_apm_views(conversations: list[Conversation]) -> tuple[ConversationView, ...]:
    """Assemble per-conversation views for an APM submission.

    Roles and per-record phases come from ``apm_roles.assign_apm_roles``.
    Conversations are then numbered sequentially per role kind by their
    earliest record timestamp ascending, so handoffs produce ``manager-2``,
    ``manager-3`` and parallel workers ``worker-1``, ``worker-2`` in
    chronological order.
    """
    result = assign_apm_roles(conversations)
    initial: list[tuple[Conversation, ConversationRole, datetime | None]] = [
        (conversation, role, _earliest_user_authored_timestamp(conversation.records))
        for conversation, role in zip(conversations, result.conversation_roles, strict=False)
    ]
    initial.sort(key=lambda item: (item[2] is None, item[2]))
    counters: dict[str, int] = {}
    views: list[ConversationView] = []
    for conversation, role, first_ts in initial:
        counters[role.base_role] = counters.get(role.base_role, 0) + 1
        role_key = f"{role.base_role}-{counters[role.base_role]}"
        phase_by_uuid = {
            record.uuid: result.phase_by_uuid[record.uuid]
            for record in conversation.records
            if record.uuid and record.uuid in result.phase_by_uuid
        }
        views.append(
            ConversationView(
                conversation=conversation,
                role=role_key,
                first_command=role.first_command,
                first_command_record=role.first_command_record,
                first_record_timestamp=first_ts,
                phase_by_record_uuid=phase_by_uuid,
            )
        )
    return tuple(views)


def _build_speckit_views(
    conversations: list[Conversation],
) -> tuple[tuple[ConversationView, ...], tuple[dict[str, Any], ...]]:
    """Assemble per-conversation views for a Spec-kit submission.

    Spec-kit has no role concept; every conversation is labelled
    ``conversation-N``. The ratchet walk runs over the global
    timestamp-sorted prompt stream so a multi-conversation submission
    still assigns phases correctly for prompts in any conversation; the
    per-record phase assignments are then partitioned back per file.
    """
    initial: list[tuple[Conversation, str, Record | None, datetime | None]] = []
    for conversation in conversations:
        # Spec-kit has no role-initiating command, so the view's
        # first_command is empty by definition; only APM conversations
        # carry one.
        initial.append(
            (
                conversation,
                "",
                None,
                _earliest_user_authored_timestamp(conversation.records),
            )
        )
    initial.sort(key=lambda item: (item[3] is None, item[3]))
    walk_result = assign_speckit_phases(conversations)
    phase_by_uuid_global = walk_result.phase_by_uuid
    backward_skill_invocations = walk_result.backward_skill_invocations
    views: list[ConversationView] = []
    for index, (conversation, first_command, first_record, first_ts) in enumerate(initial, start=1):
        per_conversation: dict[str, str] = {
            record.uuid: phase_by_uuid_global[record.uuid]
            for record in conversation.records
            if record.uuid and record.uuid in phase_by_uuid_global
        }
        views.append(
            ConversationView(
                conversation=conversation,
                role=f"conversation-{index}",
                first_command=first_command,
                first_command_record=first_record,
                first_record_timestamp=first_ts,
                phase_by_record_uuid=per_conversation,
            )
        )
    return tuple(views), backward_skill_invocations


def _earliest_user_authored_timestamp(records: tuple[Record, ...]) -> datetime | None:
    """Return the earliest user-authored prompt timestamp, falling back to any timestamp."""
    earliest: datetime | None = None
    for record in records:
        if record.timestamp is None:
            continue
        if not is_user_authored_prompt(record):
            continue
        if earliest is None or record.timestamp < earliest:
            earliest = record.timestamp
    if earliest is not None:
        return earliest
    return _earliest_timestamp(records)


def _earliest_timestamp(records: tuple[Record, ...]) -> datetime | None:
    """Return the earliest timestamp across the records, or ``None`` when none carry one."""
    earliest: datetime | None = None
    for record in records:
        if record.timestamp is None:
            continue
        if earliest is None or record.timestamp < earliest:
            earliest = record.timestamp
    return earliest


def _collect_turns(views: tuple[ConversationView, ...]) -> tuple[Turn, ...]:
    """Derive turns for every conversation view and return them in global timestamp order."""
    all_turns: list[Turn] = []
    for view in views:
        all_turns.extend(derive_turns(view.conversation))
    all_turns.sort(key=lambda turn: turn.start_timestamp)
    return tuple(all_turns)


def build_identity(session: Session) -> dict[str, Any]:
    """Assemble the session identity block.

    Identity is the stable who-and-what of a session, read before any
    metric and shared verbatim by both per-session artifacts: the modal
    Claude Code version, the pinned model, the session start and end
    timestamps, and the per-conversation array. Session start is the
    earliest user-authored prompt; session end is the latest non-synthetic
    record. Validity and health signals are not identity; they live in
    ``session_health_signals``.

    Args:
        session: The assembled session.

    Returns:
        The identity block.
    """
    models = _models_observed(session)
    pinned_model = max(models.items(), key=lambda item: item[1])[0] if models else ""
    conversations = [
        {
            "role_key": view.role,
            "session_id": view.conversation.session_id,
            "first_command": view.first_command,
            "first_record_timestamp": iso_or_none(view.first_record_timestamp),
            "record_count": len(view.conversation.records),
        }
        for view in session.views
    ]
    compaction_events, handoffs = reset_event_blocks(
        (view.role, view.conversation) for view in session.views
    )
    return {
        "model": pinned_model,
        "cc_version": _modal_string_field(session, "version"),
        "session_start": iso_or_none(session_start_timestamp(session)),
        "session_end": _latest_real_timestamp_iso(session),
        "conversations": conversations,
        "compaction_events": compaction_events,
        "handoffs": handoffs,
    }


def session_health_signals(session: Session) -> dict[str, Any]:
    """Assemble the session validity and health signals for diagnostics.

    Health signals tell an analyst whether a session is the expected shape
    before its metrics enter the cohort. Unlike identity, they live in the
    diagnostics block.

    Args:
        session: The assembled session.

    Returns:
        ``model_drift``, ``auth_mode_indicator``, ``entrypoint``, and
        ``service_tier``.
    """
    models = _models_observed(session)
    return {
        "model_drift": len(models) > 1,
        "auth_mode_indicator": _modal_string_field(session, "userType"),
        "entrypoint": _modal_string_field(session, "entrypoint"),
        "service_tier": _modal_assistant_usage_field(session, "service_tier"),
    }


def _modal_string_field(session: Session, key: str) -> str:
    """Return the modal value of a top-level string field across every record."""
    counter: Counter[str] = Counter()
    for view in session.views:
        for record in view.conversation.records:
            value = record.payload.get(key)
            if isinstance(value, str) and value:
                counter[value] += 1
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def _modal_assistant_usage_field(session: Session, key: str) -> str:
    """Return the modal value of a string field inside ``message.usage`` on assistant records."""
    counter: Counter[str] = Counter()
    for view in session.views:
        for record in view.conversation.records:
            if record.record_type != RECORD_TYPE_ASSISTANT:
                continue
            if is_synthetic_assistant(record):
                continue
            message = record.payload.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            value = usage.get(key)
            if isinstance(value, str) and value:
                counter[value] += 1
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def _models_observed(session: Session) -> dict[str, int]:
    """Return a count of distinct non-synthetic models observed across assistant records."""
    counter: Counter[str] = Counter()
    for view in session.views:
        for record in view.conversation.records:
            if record.record_type != RECORD_TYPE_ASSISTANT:
                continue
            if is_synthetic_assistant(record):
                continue
            message = record.payload.get("message")
            if not isinstance(message, dict):
                continue
            model = message.get("model")
            if isinstance(model, str) and model and model != SYNTHETIC_MODEL_MARKER:
                counter[model] += 1
    return dict(counter)


def session_start_timestamp(session: Session) -> datetime | None:
    """Return the start timestamp of the session's first turn.

    Falls back to the earliest user-authored prompt, then to the earliest
    non-synthetic record, when the session has no turns.

    Args:
        session: The assembled session.

    Returns:
        The session-start timestamp, or ``None`` when no timestamped
        record exists.
    """
    if session.turns:
        return session.turns[0].start_timestamp
    earliest: datetime | None = None
    for view in session.views:
        for record in view.conversation.records:
            if record.timestamp is None:
                continue
            if not is_user_authored_prompt(record):
                continue
            if earliest is None or record.timestamp < earliest:
                earliest = record.timestamp
    if earliest is not None:
        return earliest
    return _earliest_real_timestamp(session)


def _earliest_real_timestamp(session: Session) -> datetime | None:
    """Return the earliest non-synthetic record timestamp across the session, or ``None``."""
    earliest = None
    for view in session.views:
        for record in view.conversation.records:
            if record.timestamp is None:
                continue
            if is_synthetic_assistant(record):
                continue
            if earliest is None or record.timestamp < earliest:
                earliest = record.timestamp
    return earliest


def latest_real_timestamp(session: Session) -> datetime | None:
    """Return the latest non-synthetic record timestamp across the session, or ``None``."""
    latest = None
    for view in session.views:
        for record in view.conversation.records:
            if record.timestamp is None:
                continue
            if is_synthetic_assistant(record):
                continue
            if latest is None or record.timestamp > latest:
                latest = record.timestamp
    return latest


def _latest_real_timestamp_iso(session: Session) -> str | None:
    """Return the latest non-synthetic record timestamp as ISO-8601, or ``None``."""
    return iso_or_none(latest_real_timestamp(session))


def iso_or_none(value: datetime | None) -> str | None:
    """Return an ISO-8601 string for a timestamp, or ``None`` when absent."""
    return value.isoformat() if value is not None else None
