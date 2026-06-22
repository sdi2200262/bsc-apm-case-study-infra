# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Run the Spec-kit phase ratchet over a session's event stream.

The ratchet is the per-prompt phase assignment for Spec-kit
submissions. It walks a merged stream of three event populations
in global timestamp order and produces a per-record phase mapping
plus a chronological tuple of backward Skill invocations.

The three event populations are:

1. Genuine user-prompt records.
2. The enqueue records of delivered user-authored steers (their
   text reaches the model context only through the enqueue
   record's ``content`` field).
3. Assistant ``Skill`` tool_use blocks whose declared skill is a
   recognised Spec-kit phase command (the model self-invoking a
   skill, notably ``speckit-implement``, without the participant
   typing the slash command).

The ratchet maintains a session-scoped current phase that
advances forward only along ``other`` -> ``planning`` ->
``implementation``. Surgical Spec-kit commands behind the ratchet
count their own event as the command's phase but do not move the
ratchet back. For a Skill tool_use, the declared phase is tagged
onto the triggering assistant record and onto every record in the
same conversation file sharing its ``requestId`` (the full
streaming response of that API call), so the implementation work
the model performs after self-invoking the skill is accounted for
in the ratchet's output. Backward Skill tool_uses still tag the
request group at the declared phase, but the ratchet itself does
not move back; each backward event is surfaced separately so the
diagnostics layer can report how often the model reaches back
into planning while implementing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .commands import (
    PHASE_OTHER,
    extract_command_names,
    is_speckit_skill_tool_use,
    phase_index,
    speckit_command_phase,
)
from .conversation import STEER_FATE_DELIVERED, Conversation
from .prompts import is_user_authored_prompt
from .schema import (
    RECORD_TYPE_ASSISTANT,
    Record,
    assistant_content_blocks,
    assistant_request_id,
    user_prompt_text,
)

_EVENT_KIND_PROMPT = "prompt"
_EVENT_KIND_STEER = "steer"
_EVENT_KIND_SKILL = "skill"


@dataclass(frozen=True)
class PhaseWalkResult:
    """Output of ``assign_speckit_phases``.

    Attributes:
        phase_by_uuid: Phase label keyed by record uuid. Covers
            three populations: prompt records, steer-enqueue
            records, and the request-grouped assistant records
            around each Skill event (the triggering record and
            every same-``requestId`` record in the same
            conversation file share the Skill's declared phase).
        backward_skill_invocations: Chronological tuple of one
            dict per backward Skill event, with keys
            ``record_uuid``, ``timestamp`` (ISO string),
            ``skill`` (the Spec-kit command name), and
            ``ratchet_phase_at_event`` (the ratchet phase
            observed at the moment the Skill event arrived).
            Empty when no backward Skill invocations occurred.
    """

    phase_by_uuid: dict[str, str]
    backward_skill_invocations: tuple[dict[str, Any], ...]


def assign_speckit_phases(conversations: list[Conversation]) -> PhaseWalkResult:
    """Run the Spec-kit phase ratchet over a globally-sorted event stream.

    Tiebreak on equal timestamps is deterministic on
    ``(session_id, parent_uuid, uuid)`` so the ratchet's output
    does not depend on input iteration order.

    Args:
        conversations: Conversation files belonging to the same
            Spec-kit session. The ratchet is session-scoped, so
            events from every conversation are merged into one
            stream and the ratchet advances over the global
            ordering.

    Returns:
        A ``PhaseWalkResult`` carrying the per-record phase
        mapping and the chronological backward-Skill log.
    """
    events, requestid_to_uuids = _collect_events(conversations)
    events.sort(
        key=lambda entry: (
            entry[0].timestamp,
            entry[0].session_id or "",
            entry[0].parent_uuid or "",
            entry[0].uuid or "",
        )
    )
    current_phase = PHASE_OTHER
    phase_by_uuid: dict[str, str] = {}
    backward: list[dict[str, Any]] = []
    for record, kind, payload in events:
        if kind == _EVENT_KIND_SKILL:
            assert isinstance(payload, str)
            event_phase = speckit_command_phase(payload)
            if event_phase is None:
                continue
            _tag_skill_request_group(record, event_phase, requestid_to_uuids, phase_by_uuid)
            if phase_index(event_phase) > phase_index(current_phase):
                current_phase = event_phase
            elif phase_index(event_phase) < phase_index(current_phase):
                backward.append(_backward_entry(record, payload, current_phase))
            continue
        # Prompt or steer event: payload is the prompt or steer text.
        assert isinstance(payload, str)
        assert record.uuid is not None
        commands = extract_command_names(payload)
        speckit_phases = [
            phase
            for command in commands
            for phase in (speckit_command_phase(command),)
            if phase is not None
        ]
        if speckit_phases:
            event_phase = speckit_phases[0]
            if phase_index(event_phase) > phase_index(current_phase):
                current_phase = event_phase
            phase_by_uuid[record.uuid] = event_phase
        else:
            phase_by_uuid[record.uuid] = current_phase
    return PhaseWalkResult(
        phase_by_uuid=phase_by_uuid,
        backward_skill_invocations=tuple(backward),
    )


def _collect_events(
    conversations: list[Conversation],
) -> tuple[
    list[tuple[Record, str, str]],
    dict[tuple[str, str], list[str]],
]:
    """Walk every conversation once to build the event stream and the request-fan-out index.

    The request-fan-out index maps ``(source_file, requestId)`` to
    the ordered list of record uuids belonging to that streaming
    response, so a Skill event can tag every record in its
    request group with the declared phase.

    Args:
        conversations: Conversation files belonging to the same
            Spec-kit session.

    Returns:
        A pair ``(events, requestid_to_uuids)``. ``events`` is the
        unsorted list of event tuples ``(record, kind, payload)``
        where ``kind`` is one of the ``_EVENT_KIND_*`` constants
        and ``payload`` is the prompt text, steer text, or Skill
        command name. ``requestid_to_uuids`` is the per-file
        ``requestId`` fan-out index.
    """
    events: list[tuple[Record, str, str]] = []
    requestid_to_uuids: dict[tuple[str, str], list[str]] = {}
    for conversation in conversations:
        for record in conversation.records:
            request_id = assistant_request_id(record)
            if request_id is not None and record.uuid is not None:
                key = (str(record.source_file), request_id)
                requestid_to_uuids.setdefault(key, []).append(record.uuid)
            if is_user_authored_prompt(record):
                if record.timestamp is None or record.uuid is None:
                    continue
                events.append((record, _EVENT_KIND_PROMPT, user_prompt_text(record)))
                continue
            if record.record_type == RECORD_TYPE_ASSISTANT:
                if record.timestamp is None or record.uuid is None:
                    continue
                if request_id is None:
                    continue
                for block in assistant_content_blocks(record):
                    skill_name = is_speckit_skill_tool_use(block)
                    if skill_name is None:
                        continue
                    events.append((record, _EVENT_KIND_SKILL, skill_name))
                    # A Skill tool_use is the last content block of its
                    # streaming response; one Skill event per assistant
                    # record is the expected shape.
                    break
        for event in conversation.steer_events:
            if not event.is_user_authored or event.fate != STEER_FATE_DELIVERED:
                continue
            enqueue = event.enqueue_record
            if enqueue.timestamp is None or enqueue.uuid is None:
                continue
            content = enqueue.payload.get("content")
            if not isinstance(content, str):
                content = ""
            events.append((enqueue, _EVENT_KIND_STEER, content))
    return events, requestid_to_uuids


def _tag_skill_request_group(
    record: Record,
    event_phase: str,
    requestid_to_uuids: dict[tuple[str, str], list[str]],
    phase_by_uuid: dict[str, str],
) -> None:
    """Stamp the Skill's declared phase onto every record in its request group.

    The request group is every record in the same conversation
    file carrying the same ``requestId`` as the triggering
    assistant record. When the request_id is missing (which the
    caller has already filtered out for the Skill code path but
    the fallback exists for safety), the group degenerates to the
    triggering record alone.

    Args:
        record: The assistant record whose Skill tool_use raised
            the event.
        event_phase: The Skill's declared Spec-kit phase.
        requestid_to_uuids: Per-file ``requestId`` fan-out index
            built by ``_collect_events``.
        phase_by_uuid: Output mapping mutated in place.
    """
    request_id = assistant_request_id(record)
    assert request_id is not None, "skill events carry a non-null requestId"
    group_uuids = requestid_to_uuids.get((str(record.source_file), request_id), [])
    for uuid in group_uuids:
        if uuid is not None:
            phase_by_uuid[uuid] = event_phase


def _backward_entry(record: Record, skill_name: str, ratchet_phase: str) -> dict[str, Any]:
    """Build a diagnostics entry for a backward Skill invocation.

    A backward Skill invocation is an assistant-side Skill
    tool_use whose declared Spec-kit phase sits behind the
    ratchet at the moment the event arrives.

    Args:
        record: The assistant record whose Skill tool_use raised
            the event.
        skill_name: The declared Spec-kit command name.
        ratchet_phase: The ratchet phase observed when the event
            arrived (the phase the ratchet keeps after the
            backward event, since the ratchet does not move back).

    Returns:
        A dict with keys ``record_uuid``, ``timestamp`` (ISO
        string), ``skill``, and ``ratchet_phase_at_event``.
    """
    ts = record.timestamp.isoformat() if record.timestamp else ""
    return {
        "record_uuid": record.uuid or "",
        "timestamp": ts,
        "skill": skill_name,
        "ratchet_phase_at_event": ratchet_phase,
    }
