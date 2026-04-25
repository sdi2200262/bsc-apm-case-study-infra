#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Derive conversational turns from a Claude Code conversation's record stream.

A JSONL assistant record is not a conversational turn. One API
streaming response writes one record per content block (one for
``thinking``, one for ``text``, one for each ``tool_use``); a
conversational turn (one user prompt, one model response, possibly with
tool work in the middle) spans many such records. This module groups
records into ``Turn`` instances bounded by turn-starting user prompts.

A user prompt is turn-starting if and only if it is not the result of a
queue ``dequeue``. Queued-then-delivered prompts (steers) reach the
model mid-turn; their delivery extends the ongoing turn rather than
opening a new one. The set of delivered-steer enqueue records is
provided by the caller (built by the loader's queue-lifecycle replay).

Steers detected during a turn are recorded as engagement events on
that turn. Compact-summary user records are excluded from
turn-starting consideration: they are Claude Code's own context-rebuild
artefact, not user-authored prompts.
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
    is_genuine_user_prompt,
    is_synthetic_assistant,
    is_user_authored_enqueue,
    queue_operation,
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
        Turns in document order. Empty when the conversation contains
        no genuine user prompt; this is rare but possible for files
        that consist entirely of attachments and snapshots.
    """
    delivered_enqueue_uuids = _delivered_enqueue_uuids(conversation.steer_events)
    turn_starts: list[int] = []
    for index, record in enumerate(conversation.records):
        if not _is_turn_starting(record, conversation.records, index, delivered_enqueue_uuids):
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
    delivered_enqueue_uuids: frozenset[str],
) -> bool:
    """Return ``True`` when ``record`` opens a new turn.

    The decision is local to the record: it is a genuine user prompt
    (not a tool-result, not the post-compaction synthesised summary)
    AND it was not delivered to the model via a queue ``dequeue``.
    Identifying "delivered via dequeue" is done by matching the prompt
    to the immediately preceding ``dequeue`` record in document order
    when one exists; the dequeue's matching enqueue uuid is then
    looked up against the delivered-enqueue set the caller provided.
    A simpler approximation is used here: a genuine user prompt that
    is immediately preceded by a ``queue-operation`` record with
    ``operation == "dequeue"`` is treated as steer-delivered. The
    matching is reliable because Claude Code emits the dequeue
    immediately before the synthesised user prompt that carries the
    queued content.
    """
    if not is_genuine_user_prompt(record):
        return False
    if is_compact_summary_user(record):
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
            return False
        break
    return True


def _delivered_enqueue_uuids(steer_events: tuple[SteerEvent, ...]) -> frozenset[str]:
    """Return the set of enqueue uuids that resolved to a delivered steer.

    Delivered enqueues are those whose matching dequeue successfully
    pulled them off the open queue. The enqueue uuid (the record's own
    uuid, not the dequeue's) is the addressable identifier.
    """
    uuids: set[str] = set()
    for event in steer_events:
        if event.fate != STEER_FATE_DELIVERED:
            continue
        if event.enqueue_record.uuid:
            uuids.add(event.enqueue_record.uuid)
    return frozenset(uuids)


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
