# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Session-duration cap: drop the over-cap tail and surface it for review.

The cap is applied at load time, right after a conversation's records are
parsed and before any record-derived index is built, so the survivors are
indexed once and nothing is rebuilt. ``apply_session_cap`` partitions every
conversation's parsed records at the cutoff; ``build_cap_filter`` assembles the
``CapFilter`` the loaded ``Session`` carries; ``cap_overrun`` and
``post_cap_actions`` read it back for the report layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .prompts import is_user_authored_prompt
from .schema import CONTENT_BLOCK_TOOL_USE, Record, assistant_content_blocks

if TYPE_CHECKING:
    from .session import ConversationView, Session

DEFAULT_CAP_HOURS = 3.0

# Tools that always write a file: a tool_use of one of these past the cap is a
# deterministic working-tree mutation, named as such in the notice.
_FILE_EDIT_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
_SHELL_TOOL = "Bash"
_KIND_WRITE = "write"
_KIND_SHELL = "shell"
# Bounded width for the command or path snippet surfaced in the notice detail.
_TAIL_TARGET_WIDTH = 80
# Most post-cap actions enumerated in the notice detail before eliding the rest.
_CAP_ACTION_LIMIT = 15


@dataclass(frozen=True)
class DroppedRecord:
    """One record dropped because its timestamp fell beyond the session cap.

    Attributes:
        record: The dropped ``Record`` itself.
        conversation_path: Absolute path of the owning conversation file.
        role: Role label of the owning view (``planner-1``, ``conversation-2``),
            for a human-readable location.
    """

    record: Record
    conversation_path: str
    role: str


@dataclass(frozen=True)
class CapFilter:
    """The outcome of applying the session-duration cap at load time.

    Attributes:
        active: ``True`` when a positive cap was applied.
        cap_hours: The cap span in hours that was requested.
        anchor: The cap anchor, the earliest user-authored prompt timestamp
            across every conversation; ``None`` when the cap was disabled or no
            timestamped user prompt exists.
        cutoff: ``anchor + cap_hours``; records strictly beyond it were dropped.
            ``None`` when the cap was disabled or no anchor exists.
        dropped: Every dropped record with its owning path and role, in
            session-view order then record order. Empty when nothing was dropped.
    """

    active: bool
    cap_hours: float
    anchor: datetime | None
    cutoff: datetime | None
    dropped: tuple[DroppedRecord, ...]


def apply_session_cap(
    parsed: list[tuple[str, tuple[Record, ...]]],
    cap_hours: float,
) -> tuple[
    list[tuple[str, tuple[Record, ...]]],
    dict[str, tuple[Record, ...]],
    datetime | None,
    datetime | None,
]:
    """Partition every parsed conversation's records at the session cap.

    The anchor is the earliest user-authored prompt timestamp across every
    conversation; the cutoff is ``anchor + cap_hours``. A record survives when
    it has no timestamp or its timestamp is at or before the cutoff; only
    records strictly beyond the cutoff are dropped. A non-positive ``cap_hours``,
    or the absence of any anchored prompt, disables the cap and returns the
    input unchanged.

    Args:
        parsed: ``(conversation_path, records)`` pairs, records in document
            order, before any index is built.
        cap_hours: The cap span in hours; non-positive disables the cap.

    Returns:
        A four-tuple of the kept ``(path, records)`` pairs in input order, a map
        from conversation path to its dropped records, the cutoff, and the
        anchor. The map is empty and the cutoff and anchor are ``None`` when the
        cap is disabled or no anchor exists.
    """
    if cap_hours <= 0:
        return parsed, {}, None, None
    anchor = _earliest_user_authored(records for _, records in parsed)
    if anchor is None:
        return parsed, {}, None, None
    cutoff = anchor + timedelta(hours=cap_hours)
    kept_parsed: list[tuple[str, tuple[Record, ...]]] = []
    dropped_by_path: dict[str, tuple[Record, ...]] = {}
    for path, records in parsed:
        kept: list[Record] = []
        dropped: list[Record] = []
        for record in records:
            if record.timestamp is None or record.timestamp <= cutoff:
                kept.append(record)
            else:
                dropped.append(record)
        kept_parsed.append((path, tuple(kept)))
        if dropped:
            dropped_by_path[path] = tuple(dropped)
    return kept_parsed, dropped_by_path, cutoff, anchor


def build_cap_filter(
    views: tuple[ConversationView, ...],
    cap_hours: float,
    anchor: datetime | None,
    cutoff: datetime | None,
    dropped_by_path: dict[str, tuple[Record, ...]],
) -> CapFilter:
    """Assemble the ``CapFilter`` for a loaded session.

    The dropped records are ordered by session-view order then record order,
    pairing each with its owning view's role and path. A disabled cap (no
    cutoff) yields an inactive filter with no dropped records.

    Args:
        views: The assembled per-conversation views.
        cap_hours: The cap span in hours that was requested.
        anchor: The cap anchor, or ``None`` when the cap was disabled.
        cutoff: The cap cutoff, or ``None`` when the cap was disabled.
        dropped_by_path: Map from conversation path to its dropped records, from
            ``apply_session_cap``.

    Returns:
        The populated ``CapFilter``.
    """
    if cutoff is None:
        return CapFilter(active=False, cap_hours=cap_hours, anchor=None, cutoff=None, dropped=())
    dropped: list[DroppedRecord] = []
    for view in views:
        for record in dropped_by_path.get(view.conversation.path, ()):
            dropped.append(
                DroppedRecord(
                    record=record,
                    conversation_path=view.conversation.path,
                    role=view.role,
                )
            )
    return CapFilter(
        active=True,
        cap_hours=cap_hours,
        anchor=anchor,
        cutoff=cutoff,
        dropped=tuple(dropped),
    )


def cap_overrun(cap_filter: CapFilter) -> timedelta | None:
    """Return how far past the cutoff the last dropped record ran, or ``None``.

    The last dropped record's timestamp is the session's true end; its distance
    past the cutoff is how long the session overran the cap. ``None`` when
    nothing was dropped or the cap was disabled.
    """
    if not cap_filter.dropped or cap_filter.cutoff is None:
        return None
    stamps = [d.record.timestamp for d in cap_filter.dropped if d.record.timestamp is not None]
    if not stamps:
        return None
    return max(stamps) - cap_filter.cutoff


def post_cap_actions(session: Session) -> list[tuple[str, str, str, str]]:
    """Return the post-cap file-write and shell tool calls, for review.

    A file-editing tool (``Write``, ``Edit``, ``MultiEdit``, ``NotebookEdit``)
    is a deterministic working-tree write and is reported as such. A ``Bash``
    command is listed verbatim without classifying its effect: a shell command's
    working-tree impact is not decidable from its text, so the analyst reviews
    it rather than the parser guessing. Read-only tools are omitted. The dropped
    records arrive in session-view order then record order, so the result is
    deterministic.

    Args:
        session: The fully loaded session, carrying its ``cap_filter``.

    Returns:
        A list of ``(location, tool, target, kind)`` tuples, where ``kind`` is
        ``"write"`` for a file-editing tool or ``"shell"`` for ``Bash``.
    """
    actions: list[tuple[str, str, str, str]] = []
    for dropped in session.cap_filter.dropped:
        for block in assistant_content_blocks(dropped.record):
            if block.get("type") != CONTENT_BLOCK_TOOL_USE:
                continue
            name = block.get("name")
            if not isinstance(name, str):
                continue
            resolved = _action_target(name, block)
            if resolved is None:
                continue
            target, kind = resolved
            actions.append((_tail_location(dropped), name, target, kind))
    return actions


def format_overrun(delta: timedelta) -> str:
    """Return a compact human-readable form of a non-negative duration.

    Renders as ``Hh Mm`` past an hour, ``Mm Ss`` past a minute, else ``Ss``.
    """
    total = max(0, int(delta.total_seconds()))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def cap_overrun_summary(session: Session) -> str:
    """Return the one-line summary of how far a session overran the cap.

    Names the overrun span and the count of records the cutoff excluded.
    """
    cap_filter = session.cap_filter
    overrun = cap_overrun(cap_filter)
    span = format_overrun(overrun) if overrun is not None else "an unmeasured span"
    dropped = len(cap_filter.dropped)
    return (
        f"session ran {span} past the {cap_filter.cap_hours:g}h cap; {dropped} "
        f"record{'s' if dropped != 1 else ''} past the cutoff were excluded from the metrics"
    )


def cap_overrun_detail(session: Session) -> str:
    """Return the post-cap action listing for review.

    Leads with the count of deterministic file writes and of shell commands,
    then enumerates them (bounded), so the analyst can judge whether the
    excluded tail changed the working tree.
    """
    actions = post_cap_actions(session)
    if not actions:
        return "no file writes or shell commands fall past the cap"
    writes = sum(1 for *_, kind in actions if kind == _KIND_WRITE)
    shells = len(actions) - writes
    lines = [f"{location} | {tool} | {target}" for location, tool, target, _ in actions]
    shown = lines[:_CAP_ACTION_LIMIT]
    if len(lines) > _CAP_ACTION_LIMIT:
        shown.append(f"... and {len(lines) - _CAP_ACTION_LIMIT} more")
    head = (
        f"{writes} file write{'s' if writes != 1 else ''} and {shells} shell "
        f"command{'s' if shells != 1 else ''} fall past the cap (review for working-tree effects):"
    )
    return "\n".join([head, *shown])


def _earliest_user_authored(record_lists: Any) -> datetime | None:
    """Return the earliest user-authored prompt timestamp across record lists."""
    earliest: datetime | None = None
    for records in record_lists:
        for record in records:
            if record.timestamp is None:
                continue
            if not is_user_authored_prompt(record):
                continue
            if earliest is None or record.timestamp < earliest:
                earliest = record.timestamp
    return earliest


def _action_target(tool_name: str, block: dict[str, Any]) -> tuple[str, str] | None:
    """Return ``(target, kind)`` for a file-write or shell tool call, else ``None``.

    A file-editing tool yields its target path and ``"write"``; a ``Bash`` tool
    yields a bounded command snippet and ``"shell"``. Any other tool yields
    ``None``.
    """
    tool_input = block.get("input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    if tool_name in _FILE_EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        target = str(path) if isinstance(path, str) and path else "(unknown path)"
        return target, _KIND_WRITE
    if tool_name == _SHELL_TOOL:
        command = tool_input.get("command")
        target = _bounded(command) if isinstance(command, str) and command else "(no command)"
        return target, _KIND_SHELL
    return None


def _bounded(text: str) -> str:
    """Return ``text`` collapsed to one line and truncated to the snippet width."""
    collapsed = " ".join(text.split())
    if len(collapsed) > _TAIL_TARGET_WIDTH:
        return collapsed[:_TAIL_TARGET_WIDTH] + " ..."
    return collapsed


def _tail_location(dropped: DroppedRecord) -> str:
    """Return a human-readable location for a dropped record (role and source line)."""
    return f"{dropped.role} line {dropped.record.source_line_index}"
