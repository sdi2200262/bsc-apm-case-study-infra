# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Assemble a participant submission into a typed ``Session``.

A submission consists of one or more conversation files belonging to
the same participant session. Spec-kit submissions are expected to
contain a single conversation file by canonical workflow; an APM
submission contains one Planner conversation, one or more Manager
conversations (more when handoffs occurred), and one or more Worker
conversations (one per Worker the participant initiated, plus any
handoff continuations).

Three responsibilities sit here, above the per-conversation work the
loader does and the role and phase computation the framework
assigners do:

1. Number each APM conversation's role and key it. The role itself
   is determined by ``apm_roles.assign_apm_roles``; this
   module numbers roles sequentially by first-record timestamp
   ascending, with no parsing of participant-supplied identifiers.
   Participants type worker identifiers by hand on
   ``/apm-3-initiate-worker <id>``, so typos in re-invocations would
   split what is semantically the same worker into two distinct keys
   (``frontend-agent`` and ``fronend-agent``) if the parser tried to
   use the participant's id. Sequential numbering avoids the trap;
   the verbatim first command of each conversation is preserved per
   file so a downstream reviewer can spot two role-keys with
   similar-but-typo-different first commands and decide whether to
   merge them.

2. Partition each framework assigner's per-record phase output back
   per conversation file and attach it to the view. APM role and phase
   come from ``apm_roles.assign_apm_roles``, Spec-kit phase
   from ``speckit_phases.assign_speckit_phases``; this
   module does no phase computation of its own.

3. Compute the session identity facts: the modal Claude Code version,
   model, authentication-mode indicator, entrypoint and service tier,
   the session start and end timestamps, and the per-conversation
   array. These are data read from the assembled session and are
   surfaced through the report layer's session-metadata block.
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
    discover_conversation_files,
    load_conversation,
)
from .prompts import is_user_authored_prompt
from .schema import (
    RECORD_TYPE_ASSISTANT,
    SYNTHETIC_MODEL_MARKER,
    Record,
    SchemaError,
    is_synthetic_assistant,
)
from .speckit_phases import assign_speckit_phases
from .turns import Turn, derive_turns


@dataclass(frozen=True)
class ConversationView:
    """Per-conversation view assembled at session level.

    Attributes:
        conversation: The loaded ``Conversation`` from the loader.
        role: Role label for APM conversations, including the
            sequential index suffix (``planner-1``, ``manager-2``,
            ``worker-3``); the literal string ``unassigned-N`` for
            APM conversations whose first slash command is not a role
            initiator; the literal string ``conversation-N`` for any
            Spec-kit conversation (Spec-kit has no role concept, so
            the label is descriptive rather than role-bearing).
        first_command: Verbatim first slash command observed in the
            conversation, including any arguments, typos, or
            whitespace as written by the participant. Empty string
            when no slash command appears in any record.
        first_command_record: The record carrying ``first_command``,
            or ``None`` when no such record exists.
        first_record_timestamp: Earliest user-authored prompt
            timestamp in the conversation; falls back to the earliest
            timestamped record only when no user-authored prompt
            exists. Used to order conversations for sequential role
            numbering.
        phase_by_record_uuid: Phase label keyed by record uuid. For
            APM this maps each genuine user-prompt record to the
            role's phase. For Spec-kit this is the per-conversation
            slice of
            ``speckit_phases.PhaseWalkResult.phase_by_uuid``,
            which documents the three populations covered.
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
        framework: ``FRAMEWORK_APM`` or ``FRAMEWORK_SPECKIT``, set by
            the strict ``--framework`` flag at load time.
        views: Per-conversation views in input order (filesystem
            order from the directory walk, single-file callers get a
            single-element tuple).
        turns: Every derived turn across every conversation, in global
            timestamp order. Each turn knows its conversation file via
            ``Turn.conversation_path``.
        backward_skill_invocations: Chronological log of backward
            Skill events from the Spec-kit phase assigner; entry schema is
            documented on
            ``speckit_phases.PhaseWalkResult.backward_skill_invocations``.
            Empty tuple for APM sessions and for Spec-kit sessions
            with no backward Skill invocations.
    """

    framework: str
    views: tuple[ConversationView, ...]
    turns: tuple[Turn, ...]
    backward_skill_invocations: tuple[dict[str, Any], ...]


def load_session(path: Path, framework: str) -> Session:
    """Load a participant submission and assemble it into a ``Session``.

    Args:
        path: Either a single ``*.jsonl`` file or a directory of
            ``*.jsonl`` files copied straight from
            ``~/.claude/projects/<dashed-cwd>/``.
        framework: ``FRAMEWORK_APM`` or ``FRAMEWORK_SPECKIT``. The
            value is taken verbatim from the caller's strict flag and
            is never inferred from file content.

    Returns:
        A populated ``Session``.

    Raises:
        SchemaError: When the path does not resolve to JSONL files,
            when any file fails to parse, or when ``framework`` is not
            one of the two recognised values.
        OSError: When a file cannot be read.
    """
    if framework not in (FRAMEWORK_APM, FRAMEWORK_SPECKIT):
        raise SchemaError(
            f"unknown framework {framework!r}; expected {FRAMEWORK_APM!r} or {FRAMEWORK_SPECKIT!r}"
        )
    files = discover_conversation_files(path)
    conversations = [load_conversation(p) for p in files]
    backward_skill_invocations: tuple[dict[str, Any], ...] = ()
    if framework == FRAMEWORK_APM:
        views = _build_apm_views(conversations)
    else:
        views, backward_skill_invocations = _build_speckit_views(conversations)
    turns = _collect_turns(views)
    return Session(
        framework=framework,
        views=views,
        turns=turns,
        backward_skill_invocations=backward_skill_invocations,
    )


def _build_apm_views(conversations: list[Conversation]) -> tuple[ConversationView, ...]:
    """Assemble per-conversation views for an APM submission.

    Roles and per-record phases are computed by
    ``apm_roles.assign_apm_roles``. Conversations are then
    numbered sequentially per role kind by their earliest record
    timestamp ascending so that handoffs produce ``manager-2``,
    ``manager-3`` and parallel workers produce ``worker-1``,
    ``worker-2`` in chronological order.
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
    ``conversation-N`` for parallel structure with APM. The ratchet
    walk runs over the global timestamp-sorted prompt stream so that
    a multi-conversation Spec-kit submission still produces correct
    phase assignment for prompts in any conversation; the per-record
    phase assignments are then partitioned back per conversation
    file.
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
    """Return the earliest user-authored prompt timestamp in the records.

    Falls back to ``_earliest_timestamp`` when no user-authored
    prompt exists.

    Args:
        records: Conversation records in load order.

    Returns:
        The timestamp, or ``None`` when no timestamped record exists.
    """
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


def build_session_metadata(session: Session) -> dict[str, Any]:
    """Assemble the session-metadata block.

    The block carries the per-session descriptive identity fields the
    analysis layer reads before any metric: the modal Claude Code
    version, model, authentication-mode indicator, entrypoint, and
    service tier, the session start and end timestamps, and the
    per-conversation array. Session start is the earliest user-authored
    prompt across the session; session end is the latest non-synthetic
    record.
    """
    cc_versions = _modal_string_field(session, "version")
    auth_modes = _modal_string_field(session, "userType")
    entrypoints = _modal_string_field(session, "entrypoint")
    service_tiers = _modal_assistant_usage_field(session, "service_tier")
    models = _models_observed(session)
    pinned_model = max(models.items(), key=lambda item: item[1])[0] if models else ""
    start = iso_or_none(session_start_timestamp(session))
    end = _latest_real_timestamp_iso(session)
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
    return {
        "cc_version": cc_versions,
        "model": pinned_model,
        "model_drift": len(models) > 1,
        "auth_mode_indicator": auth_modes,
        "entrypoint": entrypoints,
        "service_tier": service_tiers,
        "session_start_timestamp": start,
        "session_end_timestamp": end,
        "conversations": conversations,
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

    Falls back to the earliest user-authored prompt, then to
    ``_earliest_real_timestamp``, when the session has no turns.

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
