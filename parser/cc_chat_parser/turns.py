#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Derive conversational turns from a Claude Code conversation's record stream.

A JSONL assistant record is not a conversational turn. One API
streaming response writes one record per content block (one for
``thinking``, one for ``text``, one for each ``tool_use``); a
conversational turn (one user prompt, one model response, possibly with
tool work in the middle) spans many such records. This module groups
records into ``Turn`` instances bounded by turn-starting user prompts.

Turn-starting prompts come in two shapes. A free-typed user record is
turn-starting on its own. A user-driven slash invocation is turn-starting
on the marker record (the ``<command-message>`` echo); its paired
rendered body, which the platform writes in the same ``promptId`` group
and delivers to the model, lives within the marker-anchored turn rather
than opening a new one. The marker, not the rendered body, is the turn
anchor: it carries the user's invocation including the command name and
arguments and feeds the bucket classifier directly via the
``<command-name>`` tag.

Three group-level guards keep platform bookkeeping out of the
turn-starting set. A slash marker whose ``promptId`` group has no
rendered body never reached the model: this covers local-only commands
(``/model``, ``/effort``, ``/clear``) and typos that hit the local
parser. A free-typed-shaped error string in a ``promptId`` group whose
only sibling is a caveat is the ``Unknown command: ...`` line Claude
Code emits for typos. A user record carrying ``sourceToolUseID`` is the
rendering of a Skill the model itself invoked via the Skill tool, which
is model-driven content rather than a user-authored prompt.

Delivered steers are still handled as before: a queued-then-delivered
prompt reaches the model mid-turn and extends the ongoing turn rather
than opening a new one. The set of delivered-steer dequeue records is
provided by the loader's queue-lifecycle replay.

Compact-summary user records are excluded from turn-starting
consideration: they are Claude Code's own context-rebuild artefact, not
user-authored prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .loader import STEER_FATE_DELIVERED, Conversation, SteerEvent
from .schema import (
    QUEUE_OP_ENQUEUE,
    Record,
    is_compact_summary_user,
    is_synthetic_assistant,
    is_user_authored_enqueue,
    queue_operation,
)
from .user_prompts import (
    is_local_command_caveat,
    is_slash_command_marker,
    is_slash_command_rendered_body,
    is_user_authored_prompt,
)


@dataclass(frozen=True)
class Turn:
    """One conversational turn within a conversation file.

    A turn covers the interval from a turn-starting user prompt to the
    last record before the next turn-starting prompt (or the last
    non-attachment record of the file when no next turn exists).

    Attributes:
        conversation_path: Absolute path of the source conversation
            file.
        starting_prompt: The turn-starting user prompt record.
        records: Every record (in document order) that belongs to this
            turn, including the starting prompt.
        steer_events: Steer events whose enqueue timestamp falls within
            the turn's interval. Both delivered and abandoned steers
            are listed; classification is on the event itself.
        start_timestamp: Timestamp of the starting prompt record.
        end_timestamp: Timestamp of the last record in ``records`` that
            carries one. Falls back to ``start_timestamp`` for the rare
            single-record turn whose only record is the prompt itself.
    """

    conversation_path: str
    starting_prompt: Record
    records: tuple[Record, ...]
    steer_events: tuple[SteerEvent, ...]
    start_timestamp: datetime
    end_timestamp: datetime


def derive_turns(conversation: Conversation) -> tuple[Turn, ...]:
    """Group a conversation's records into conversational turns.

    Args:
        conversation: A loaded conversation with its steer events
            already classified.

    Returns:
        Turns in document order. Empty when the conversation
        contains no user-authored turn-starting prompt; this is
        rare but possible for files that consist entirely of
        attachments and snapshots.
    """
    matched_dequeue_keys = _matched_dequeue_keys(conversation.steer_events)
    promptids_with_rendered_body = _promptids_with_rendered_body(conversation.records)
    promptids_with_failed_local_invocation = _promptids_with_failed_local_invocation(
        conversation.records,
        promptids_with_rendered_body,
    )
    turn_starts: list[int] = []
    for index, record in enumerate(conversation.records):
        if not _is_turn_starting(
            record,
            conversation.records,
            index,
            matched_dequeue_keys,
            promptids_with_rendered_body,
            promptids_with_failed_local_invocation,
        ):
            continue
        turn_starts.append(index)
    if not turn_starts:
        return ()
    boundaries = turn_starts + [len(conversation.records)]
    turns: list[Turn] = []
    for start, end in zip(boundaries, boundaries[1:]):
        slice_records = tuple(conversation.records[start:end])
        starting = slice_records[0]
        if starting.timestamp is None:
            continue
        end_timestamp = _last_timestamp(slice_records, fallback=starting.timestamp)
        steer_events = tuple(_steer_events_in_interval(
            conversation.steer_events,
            starting.timestamp,
            end_timestamp,
        ))
        turns.append(Turn(
            conversation_path=conversation.path,
            starting_prompt=starting,
            records=slice_records,
            steer_events=steer_events,
            start_timestamp=starting.timestamp,
            end_timestamp=end_timestamp,
        ))
    return tuple(turns)


def _is_turn_starting(
    record: Record,
    all_records: tuple[Record, ...],
    index: int,
    matched_dequeue_keys: frozenset[tuple[str, int]],
    promptids_with_rendered_body: frozenset[str],
    promptids_with_failed_local_invocation: frozenset[str],
) -> bool:
    """Return ``True`` when ``record`` opens a new turn.

    The record must first satisfy ``is_user_authored_prompt``: the
    user-authored shape predicate that excludes tool-results,
    compact summaries, model-invoked Skill renderings, local-command
    caveats, local-command stdout/stderr, and platform-rendered slash
    bodies.

    Two further conversation-level guards apply. A slash-command
    marker is a turn-starter only when its ``promptId`` group
    contains a rendered body; a marker without a paired rendering
    covers local-only commands (which never reach the model) and
    typos that hit the local parser. A free-typed-shaped record
    whose ``promptId`` group is a failed local invocation (a caveat
    with no rendered body) is the ``Unknown command: ...`` error
    string Claude Code emits for a typo'd slash invocation.

    Steer delivery preserves the existing semantics: when the
    closest preceding non-attachment, non-snapshot record is a
    ``dequeue`` whose matching enqueue was resolved by the loader's
    queue-lifecycle replay, the prompt is the synthesised payload of
    that delivery and continues the ongoing turn. An unmatched
    dequeue does not disqualify the prompt: nothing was actually
    delivered to absorb it into the previous turn. Queue-operation
    records carry no ``uuid``; the matched-dequeue identity uses
    ``(source_file, source_line_index)``, unique within a
    conversation.
    """
    if not is_user_authored_prompt(record):
        return False
    promptid = record.payload.get("promptId")
    if is_slash_command_marker(record):
        if not isinstance(promptid, str):
            return False
        if promptid not in promptids_with_rendered_body:
            return False
    else:
        if isinstance(promptid, str) and promptid in promptids_with_failed_local_invocation:
            return False
    preceding_index = index - 1
    while preceding_index >= 0:
        preceding = all_records[preceding_index]
        if preceding.record_type == "attachment":
            preceding_index -= 1
            continue
        if preceding.record_type == "file-history-snapshot":
            preceding_index -= 1
            continue
        if queue_operation(preceding) == "dequeue":
            key = (preceding.source_file, preceding.source_line_index)
            if key in matched_dequeue_keys:
                return False
            return True
        break
    return True


def _promptids_with_rendered_body(records: tuple[Record, ...]) -> frozenset[str]:
    """Return ``promptId``s whose group contains a rendered slash body.

    The presence of a rendered body proves the slash invocation
    expanded into a prompt the platform delivered to the model. A
    marker whose group has no rendered body either ran a local-only
    command or was a typo the local parser refused.
    """
    promptids: set[str] = set()
    for record in records:
        if not is_slash_command_rendered_body(record):
            continue
        promptid = record.payload.get("promptId")
        if isinstance(promptid, str):
            promptids.add(promptid)
    return frozenset(promptids)


def _promptids_with_failed_local_invocation(
    records: tuple[Record, ...],
    promptids_with_rendered_body: frozenset[str],
) -> frozenset[str]:
    """Return ``promptId``s of caveat-only groups that produced no rendered body.

    Local-only slash commands and typos both write a caveat record
    into the conversation. A typo additionally writes a free-typed-
    shaped error string (``Unknown command: ...``) into the same
    ``promptId`` group; that string would otherwise pass
    ``is_user_authored_prompt``. A local-only command writes a
    marker and a stdout record into the same group; the marker is
    already filtered by the absence of a rendered body. Free-typed
    records in the returned set are dropped at the turn-starting
    decision.
    """
    promptids: set[str] = set()
    for record in records:
        if not is_local_command_caveat(record):
            continue
        promptid = record.payload.get("promptId")
        if not isinstance(promptid, str):
            continue
        if promptid in promptids_with_rendered_body:
            continue
        promptids.add(promptid)
    return frozenset(promptids)


def _matched_dequeue_keys(
    steer_events: tuple[SteerEvent, ...],
) -> frozenset[tuple[str, int]]:
    """Return identity keys of dequeue records that successfully resolved an enqueue.

    A dequeue is considered matched when the loader's
    queue-lifecycle replay paired it with an open enqueue
    (user-authored or system-generated). Matched dequeues
    correspond to a real delivery: the queued content reached the
    model as the next streamed user-side payload. Unmatched
    dequeues (queue lifecycle warnings) deliver nothing. The
    identity key is ``(source_file, source_line_index)`` because
    queue-operation records do not carry their own uuid in the
    Claude Code rollout.
    """
    keys: set[tuple[str, int]] = set()
    for event in steer_events:
        if event.fate != STEER_FATE_DELIVERED:
            continue
        resolution = event.resolution_record
        if resolution is None:
            continue
        keys.add((resolution.source_file, resolution.source_line_index))
    return frozenset(keys)


def _steer_events_in_interval(
    events: tuple[SteerEvent, ...],
    start: datetime,
    end: datetime,
) -> Iterable[SteerEvent]:
    """Yield steer events whose enqueue timestamp falls within ``[start, end]``."""
    for event in events:
        ts = event.enqueue_record.timestamp
        if ts is None:
            continue
        if start <= ts <= end:
            yield event


def _last_timestamp(records: tuple[Record, ...], fallback: datetime) -> datetime:
    """Return the latest timestamp on any record in ``records``, or ``fallback``."""
    latest: datetime | None = None
    for record in records:
        if record.timestamp is None:
            continue
        if is_synthetic_assistant(record):
            continue
        if latest is None or record.timestamp > latest:
            latest = record.timestamp
    return latest if latest is not None else fallback
