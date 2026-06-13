# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Load Claude Code JSONL conversation files from disk.

A submission can be a single JSONL file or a directory of one or more
``<sessionId>.jsonl`` files copied straight from
``~/.claude/projects/<dashed-cwd>/``. For a directory, only top-level
``*.jsonl`` files load as main conversations; the sibling
``<sessionId>/subagents/`` directory adjacent to each main file is read
separately to populate the per-conversation ``SubagentModelIndex`` (so
delegated dispatches price against the subagent's model, not the
parent's), and ``<sessionId>/tool-results/`` directories are ignored.
Conversations are ordered by earliest record timestamp, not filename.

The loader does three orthogonal jobs over a single-pass walk of a file's
records:

1. Parse every JSONL line into a typed ``Record`` (via
   ``schema.parse_record``).
2. Build the ``RequestUsageIndex`` deduplicating ``message.usage`` by
   ``requestId``, the canonical per-call usage for token-sum metrics; the
   dedup rationale is on ``_build_usage_index`` and ``RequestUsageIndex``.
3. Replay the queue lifecycle to classify each ``queue-operation`` record
   as a ``delivered`` steer, an ``abandoned`` steer, or (for
   system-generated enqueues) filtered out, emitting one ``SteerEvent``
   per resolved user enqueue. Imbalances are recorded as warnings, not
   errors, so the parser continues and surfaces them in diagnostics.

Steer classification (delivered vs abandoned) is owned here; how a
delivered steer affects turn boundaries is owned by ``turns``, which
reads these ``SteerEvent`` records.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import (
    QUEUE_OP_DEQUEUE,
    QUEUE_OP_ENQUEUE,
    QUEUE_OP_POP_ALL,
    QUEUE_OP_REMOVE,
    SYSTEM_SUBTYPE_COMPACT_BOUNDARY,
    Record,
    SchemaError,
    assistant_message_usage,
    assistant_request_id,
    is_synthetic_assistant,
    is_user_authored_enqueue,
    parse_record,
    queue_operation,
)
from .subagent_models import SubagentModelIndex, build_subagent_model_index

CONVERSATION_FILE_GLOB = "*.jsonl"

STEER_FATE_DELIVERED = "delivered"
STEER_FATE_ABANDONED = "abandoned"


@dataclass(frozen=True)
class SteerEvent:
    """One classified enqueue and the disposition that resolved it.

    Attributes:
        enqueue_record: The ``queue-operation`` record carrying the
            enqueue.
        is_user_authored: ``True`` when the enqueue's content is a
            user-typed message, ``False`` when it is a Claude Code
            system-generated envelope (typically a task notification
            wrapped in ``<task-notification>...``). Steer metrics
            count only user-authored events.
        fate: ``STEER_FATE_DELIVERED`` when a later ``dequeue`` matched
            this enqueue and the queued content reached the model;
            ``STEER_FATE_ABANDONED`` when a later ``remove`` or
            ``popAll`` cancelled it before delivery.
        resolution_record: The ``queue-operation`` record that resolved
            this enqueue. ``None`` only when the conversation file ends
            with the enqueue still unresolved.
    """

    enqueue_record: Record
    is_user_authored: bool
    fate: str
    resolution_record: Record | None


@dataclass(frozen=True)
class RequestUsageIndex:
    """Per-conversation deduplication of ``message.usage`` by ``requestId``.

    Attributes:
        usage_by_request_id: One ``usage`` dict per unique non-synthetic
            ``requestId`` observed in the conversation. The first usage
            encountered for a given id is kept; later records sharing
            the id are verified to carry an identical ``usage`` shape
            and discarded.
        synthetic_assistant_count: Count of assistant records whose
            ``message.model`` is ``"<synthetic>"`` and which were
            therefore excluded from the index.
        records_without_request_id: Count of non-synthetic assistant
            records that lacked a ``requestId``. Always zero on
            well-formed Claude Code data; surfaced for diagnostics.
        errored_calls_excluded: Count of assistant records whose
            ``isApiErrorMessage`` flag was ``True`` and which were
            therefore excluded. Anthropic's API does not bill failed
            requests, so the exclusion keeps the cost figure honest; the
            count surfaces a high-error session in diagnostics.
    """

    usage_by_request_id: dict[str, dict[str, Any]]
    synthetic_assistant_count: int
    records_without_request_id: int
    errored_calls_excluded: int


@dataclass(frozen=True)
class CompactionEvent:
    """One Claude Code autocompaction event observed in a conversation.

    Attributes:
        boundary_record: The ``compact_boundary`` system record itself.
        trigger: The compaction trigger reported in ``compactMetadata``
            (typically ``"manual"`` or ``"auto"``); empty string when
            the field is absent.
        pre_tokens: Pre-compaction context size in tokens, as reported
            in ``compactMetadata``; ``None`` when absent.
        post_tokens: Post-compaction context size in tokens, as
            reported in ``compactMetadata``; ``None`` when absent.
        duration_ms: Wall-clock duration of the compaction operation,
            as reported in ``compactMetadata``; ``None`` when absent.
    """

    boundary_record: Record
    trigger: str
    pre_tokens: int | None
    post_tokens: int | None
    duration_ms: int | None


@dataclass(frozen=True)
class Conversation:
    """One JSONL file's records and the derived structures the rest of the parser needs.

    Attributes:
        path: Absolute path of the source file.
        session_id: The conversation's session uuid as written on its
            records. ``None`` only when no record in the file carries a
            ``sessionId``, which would itself be an anomaly.
        records: Every parsed record from the file in document order.
        usage_index: Deduplicated ``message.usage`` values keyed by
            ``requestId``.
        subagent_model_index: ``agentId``-keyed map of canonical model
            ids built from the sibling ``<sessionId>/subagents/``
            directory. Empty when that directory is absent.
        steer_events: Classified user-authored enqueues with their
            delivery or abandonment outcome.
        compaction_events: ``compact_boundary`` events observed in the
            file.
        queue_lifecycle_warnings: Human-readable warnings emitted during
            the queue replay (mismatched dequeue or remove with no open
            enqueue, unresolved enqueues at end of file). Surfaced in
            the diagnostics block of the report.
    """

    path: str
    session_id: str | None
    records: tuple[Record, ...]
    usage_index: RequestUsageIndex
    subagent_model_index: SubagentModelIndex
    steer_events: tuple[SteerEvent, ...]
    compaction_events: tuple[CompactionEvent, ...]
    queue_lifecycle_warnings: tuple[str, ...]


def discover_conversation_files(path: Path) -> list[Path]:
    """Return the main session JSONL files a submission path resolves to.

    Args:
        path: Either a single ``*.jsonl`` file or a directory containing
            one or more top-level ``*.jsonl`` files.

    Returns:
        A list of absolute paths in filesystem order. Top-level only when
        ``path`` is a directory; nested subdirectories are not descended.
        The ``SubagentModelIndex`` is built separately by
        ``load_conversation``. Sealing every file a submission ships
        is a separate concern owned by ``parser.sanitize``.

    Raises:
        SchemaError: When the path does not exist, when it is a file
            with the wrong extension, or when a directory contains no
            top-level ``*.jsonl`` files.
    """
    resolved = path.resolve()
    if not resolved.exists():
        raise SchemaError(f"submission path not found: {resolved}")
    if resolved.is_file():
        if resolved.suffix.lower() != ".jsonl":
            raise SchemaError(f"submission file is not a JSONL file: {resolved}")
        return [resolved]
    if resolved.is_dir():
        files = sorted(resolved.glob(CONVERSATION_FILE_GLOB))
        if not files:
            raise SchemaError(
                f"submission directory contains no {CONVERSATION_FILE_GLOB} files: {resolved}"
            )
        return files
    raise SchemaError(f"submission path is neither a file nor a directory: {resolved}")


def parse_conversation_records(path: Path) -> tuple[Record, ...]:
    """Parse a conversation file into its records, in document order.

    This is the read step the session cap runs before any record-derived index
    is built, so the cap can drop the over-cap tail and ``build_conversation``
    indexes only the survivors.

    Args:
        path: Absolute path to a single JSONL file.

    Returns:
        The parsed records in document order.

    Raises:
        SchemaError: On any unrecoverable parse failure.
        OSError: When the file cannot be read.
    """
    return tuple(_parse_lines(Path(path).resolve()))


def build_conversation(path: Path, records: tuple[Record, ...]) -> Conversation:
    """Build a ``Conversation`` and its record-derived indices from ``records``.

    The usage dedup, steer lifecycle, queue-lifecycle warnings, and compaction
    events are derived from ``records``; ``session_id`` from the records' modal
    sessionId; the subagent-model index from the sibling ``subagents/``
    directory. Building from a cap-filtered record set therefore indexes only
    the survivors, with no value carried over from a wider set.

    Args:
        path: Absolute path of the source file.
        records: The records to index, in document order.

    Returns:
        A populated ``Conversation``.

    Raises:
        SchemaError: When a record is structurally invalid for indexing.
    """
    resolved = Path(path).resolve()
    session_id = _resolve_session_id(records)
    usage_index = _build_usage_index(records, str(resolved))
    subagent_model_index = build_subagent_model_index(resolved)
    steer_events, queue_warnings = _replay_queue_lifecycle(records)
    compaction_events = tuple(_extract_compaction_events(records))
    return Conversation(
        path=str(resolved),
        session_id=session_id,
        records=records,
        usage_index=usage_index,
        subagent_model_index=subagent_model_index,
        steer_events=steer_events,
        compaction_events=compaction_events,
        queue_lifecycle_warnings=queue_warnings,
    )


def load_conversation(path: Path) -> Conversation:
    """Parse and build one conversation file in a single step (the uncapped path).

    Args:
        path: Absolute path to a single JSONL file.

    Returns:
        A populated ``Conversation`` over every record in the file.

    Raises:
        SchemaError: On any unrecoverable parse failure. Recoverable anomalies
            (mismatched queue operations) are recorded as warnings inside the
            returned ``Conversation``.
        OSError: When the file cannot be read.
    """
    resolved = Path(path).resolve()
    return build_conversation(resolved, parse_conversation_records(resolved))


def _parse_lines(path: Path) -> Iterable[Record]:
    """Yield one ``Record`` per non-empty line of ``path``."""
    with path.open("r", encoding="utf-8") as source:
        for line_index, line in enumerate(source):
            if not line.strip():
                continue
            yield parse_record(line, str(path), line_index)


def _resolve_session_id(records: tuple[Record, ...]) -> str | None:
    """Return the modal non-empty ``sessionId`` across records, or ``None`` when absent.

    Records can lack a ``sessionId`` (some ``file-history-snapshot``
    and ``last-prompt`` records do); the modal value across records
    that carry one is taken as the conversation's identifier.
    """
    counts: dict[str, int] = {}
    for record in records:
        if record.session_id:
            counts[record.session_id] = counts.get(record.session_id, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _build_usage_index(
    records: tuple[Record, ...],
    source_file: str,
) -> RequestUsageIndex:
    """Build the ``RequestUsageIndex`` for a conversation file.

    The first non-synthetic assistant record for a given ``requestId``
    contributes its ``message.usage``; later records sharing the id are
    skipped, because Claude Code emits identical usage on every record of a
    streaming response. Records whose ``isApiErrorMessage`` is ``True`` are
    excluded entirely: Anthropic's API does not bill failed requests, so an
    errored record's notional usage is not part of the cost paid. The
    exclusion is counted in ``errored_calls_excluded``.
    """
    usage_by_request_id: dict[str, dict[str, Any]] = {}
    synthetic_count = 0
    missing_request_id = 0
    errored_excluded = 0
    for record in records:
        if record.record_type != "assistant":
            continue
        if is_synthetic_assistant(record):
            synthetic_count += 1
            continue
        if record.payload.get("isApiErrorMessage") is True:
            errored_excluded += 1
            continue
        request_id = assistant_request_id(record)
        if request_id is None:
            missing_request_id += 1
            continue
        if request_id in usage_by_request_id:
            continue
        usage = assistant_message_usage(record)
        if usage is None:
            raise SchemaError(
                f"{source_file} line {record.source_line_index}: "
                f"assistant record has no message.usage block"
            )
        usage_by_request_id[request_id] = usage
    return RequestUsageIndex(
        usage_by_request_id=usage_by_request_id,
        synthetic_assistant_count=synthetic_count,
        records_without_request_id=missing_request_id,
        errored_calls_excluded=errored_excluded,
    )


def _replay_queue_lifecycle(
    records: tuple[Record, ...],
) -> tuple[tuple[SteerEvent, ...], tuple[str, ...]]:
    """Replay the queue lifecycle and emit one ``SteerEvent`` per resolved user enqueue.

    Claude Code's queue holds both user-authored enqueues (a participant
    steer typed mid-turn) and system-generated enqueues (task
    notifications wrapped in ``<task-notification>...``). The two share one
    ordered queue: ``dequeue`` pops the oldest open enqueue regardless of
    source, ``remove`` pops the most recent, ``popAll`` clears every open
    enqueue at once. The replay tracks every enqueue by source and emits a
    ``SteerEvent`` only when the resolved enqueue is user-authored; system
    enqueues are matched silently so the ordering invariant holds.

    Imbalances (a ``dequeue`` or ``remove`` with no open enqueue, or
    user-authored enqueues still open at end of file) are recorded as
    warnings; the ``SteerEvent`` list still captures everything resolvable.
    """
    open_enqueues: list[tuple[Record, bool]] = []
    events: list[SteerEvent] = []
    warnings: list[str] = []
    for record in records:
        op = queue_operation(record)
        if op is None:
            continue
        if op == QUEUE_OP_ENQUEUE:
            open_enqueues.append((record, is_user_authored_enqueue(record)))
            continue
        if op == QUEUE_OP_DEQUEUE:
            if not open_enqueues:
                warnings.append(
                    f"{record.source_file} line {record.source_line_index}: "
                    "dequeue with no open enqueue"
                )
                continue
            matched, is_user = open_enqueues.pop(0)
            events.append(
                SteerEvent(
                    enqueue_record=matched,
                    is_user_authored=is_user,
                    fate=STEER_FATE_DELIVERED,
                    resolution_record=record,
                )
            )
            continue
        if op == QUEUE_OP_REMOVE:
            if not open_enqueues:
                warnings.append(
                    f"{record.source_file} line {record.source_line_index}: "
                    "remove with no open enqueue"
                )
                continue
            matched, is_user = open_enqueues.pop()
            events.append(
                SteerEvent(
                    enqueue_record=matched,
                    is_user_authored=is_user,
                    fate=STEER_FATE_ABANDONED,
                    resolution_record=record,
                )
            )
            continue
        if op == QUEUE_OP_POP_ALL:
            for matched, is_user in open_enqueues:
                events.append(
                    SteerEvent(
                        enqueue_record=matched,
                        is_user_authored=is_user,
                        fate=STEER_FATE_ABANDONED,
                        resolution_record=record,
                    )
                )
            open_enqueues.clear()
            continue
    for unresolved, is_user in open_enqueues:
        if is_user:
            warnings.append(
                f"{unresolved.source_file} line {unresolved.source_line_index}: "
                "user-authored enqueue still open at end of file; treated as abandoned"
            )
        events.append(
            SteerEvent(
                enqueue_record=unresolved,
                is_user_authored=is_user,
                fate=STEER_FATE_ABANDONED,
                resolution_record=None,
            )
        )
    return tuple(events), tuple(warnings)


def _extract_compaction_events(records: tuple[Record, ...]) -> Iterable[CompactionEvent]:
    """Yield one ``CompactionEvent`` per ``compact_boundary`` record in the file."""
    for record in records:
        if record.record_type != "system":
            continue
        if record.subtype != SYSTEM_SUBTYPE_COMPACT_BOUNDARY:
            continue
        metadata = record.payload.get("compactMetadata")
        if not isinstance(metadata, dict):
            metadata = {}
        trigger = metadata.get("trigger")
        yield CompactionEvent(
            boundary_record=record,
            trigger=trigger if isinstance(trigger, str) else "",
            pre_tokens=_optional_int(metadata.get("preTokens")),
            post_tokens=_optional_int(metadata.get("postTokens")),
            duration_ms=_optional_int(metadata.get("durationMs")),
        )


def _optional_int(value: Any) -> int | None:
    """Return ``value`` when it is an int, otherwise ``None``."""
    return value if isinstance(value, int) else None
