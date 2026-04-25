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
    matched_dequeue_keys = _matched_dequeue_keys(conversation.steer_events)
    turn_starts: list[int] = []
    for index, record in enumerate(conversation.records):
        if not _is_turn_starting(record, conversation.records, index, matched_dequeue_keys):
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
) -> bool:
    """Return ``True`` when ``record`` opens a new turn.

    A user prompt is turn-starting when it is a genuine
    user-content record, is not the post-compaction synthesised
    summary, and is not the result of a matched queue ``dequeue``.
    The closest preceding non-attachment, non-snapshot record is
    inspected; when that record is a ``dequeue`` whose matching
    enqueue was successfully resolved during the loader's
    queue-lifecycle replay, the prompt is the synthesised payload
    of that delivery and continues the ongoing turn rather than
    opening a new one. An unmatched dequeue (recorded as a queue
    lifecycle warning) does not disqualify the prompt: nothing was
    actually delivered to absorb it into a previous turn.

    Queue-operation records carry no ``uuid`` field of their own,
    so the matched-dequeue identity uses ``(source_file,
    source_line_index)`` instead. Both fields are populated on
    every parsed ``Record``, and the pair is unique within a
    conversation.
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
            key = (preceding.source_file, preceding.source_line_index)
            if key in matched_dequeue_keys:
                return False
            return True
        break
    return True


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
