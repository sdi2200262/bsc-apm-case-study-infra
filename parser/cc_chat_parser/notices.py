#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Session-attention notices for the parser's CLI summary modes.

A ``Notice`` captures a single condition that an analyst should be
aware of before interpreting or accepting a session's metrics. Two
tags are defined: ``REVIEW`` for conditions that are qualitatively
ambiguous and require human judgment, and ``WARNING`` for conditions
that are objectively abnormal and require no judgment to classify.

``collect_notices`` inspects a loaded ``Session`` and returns the
full tuple of applicable notices, REVIEW notices first, then WARNING
notices, in deterministic iteration order within each group.
``print_notice_block`` renders that tuple to stdout using the shared
grammar expected by both the ``--process`` and ``--economic`` CLI
modes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .report_diagnostics import (
    agent_dispatch_counts,
    slash_invocation_counts,
    unknown_commands,
)
from .session import Session

TAG_REVIEW = "REVIEW"
TAG_WARNING = "WARNING"

_UNKNOWN_COMMANDS_DISPLAY_WIDTH = 120


@dataclass(frozen=True)
class Notice:
    """A single session-attention signal surfaced in the CLI summary.

    Attributes:
        tag: Either ``"REVIEW"`` or ``"WARNING"``. REVIEW notices are
            qualitatively ambiguous; the analyst must examine the
            session before the result enters the cohort record.
            WARNING notices are objectively abnormal; no judgment is
            required to classify them, but the report author should
            acknowledge them.
        label: A short identifier for the condition, suitable for a
            heading or index entry.
        summary: A single sentence naming the condition and its
            quantitative magnitude where applicable.
        detail: Elaboration that gives the analyst a concrete next
            step or names the impact on downstream consumers. May
            equal ``summary`` when no additional detail exists.
    """

    tag: str
    label: str
    summary: str
    detail: str


def collect_notices(session: Session) -> tuple[Notice, ...]:
    """Collect all applicable session-attention notices for ``session``.

    Inspects the session for each catalogued condition and returns a
    tuple of notices in canonical order: all REVIEW notices first (in
    the order the conditions are checked), then all WARNING notices
    (in the order the conditions are checked). The caller does not
    need to sort.

    This function is a pure aggregator: it performs no I/O, has no
    side effects, and does not mutate the session.

    Args:
        session: The fully loaded session to inspect.

    Returns:
        A tuple of ``Notice`` objects, possibly empty when no
        conditions fire.
    """
    review_notices: list[Notice] = []
    warning_notices: list[Notice] = []

    # REVIEW: backward skill invocations
    if session.backward_skill_invocations:
        count = len(session.backward_skill_invocations)
        distinct = sorted({
            str(entry.get("skill", ""))
            for entry in session.backward_skill_invocations
            if entry.get("skill")
        })
        skills_str = ", ".join(distinct) if distinct else "(none)"
        review_notices.append(Notice(
            tag=TAG_REVIEW,
            label="backward skill invocations",
            summary=(
                f"{count} backward invocation{'s' if count != 1 else ''} observed; "
                f"distinct skills: {skills_str}"
            ),
            detail="cue: audit this session before drawing phase-distribution conclusions",
        ))

    # REVIEW: turns with missing uuid
    missing_uuid_count = sum(
        1 for t in session.turns if not t.starting_prompt.uuid
    )
    if missing_uuid_count > 0:
        review_notices.append(Notice(
            tag=TAG_REVIEW,
            label="turns with missing uuid",
            summary=(
                f"{missing_uuid_count} turn{'s' if missing_uuid_count != 1 else ''} "
                "could not be uniquely keyed"
            ),
            detail=(
                "cue: per-turn analyses cannot uniquely identify "
                f"{'these turns' if missing_uuid_count != 1 else 'this turn'}"
            ),
        ))

    # WARNING: queue lifecycle warnings
    total_queue_warnings = sum(
        len(view.conversation.queue_lifecycle_warnings) for view in session.views
    )
    files_with_warnings = sum(
        1 for view in session.views
        if view.conversation.queue_lifecycle_warnings
    )
    if total_queue_warnings > 0:
        warning_notices.append(Notice(
            tag=TAG_WARNING,
            label="queue lifecycle warnings",
            summary=(
                f"{total_queue_warnings} queue lifecycle "
                f"warning{'s' if total_queue_warnings != 1 else ''} observed "
                f"across {files_with_warnings} "
                f"conversation file{'s' if files_with_warnings != 1 else ''}"
            ),
            detail=(
                "inspect view.conversation.queue_lifecycle_warnings "
                "for the per-file detail"
            ),
        ))

    # WARNING: unknown commands
    unknown = unknown_commands(session)
    if unknown:
        truncated = ", ".join(unknown)
        if len(truncated) > _UNKNOWN_COMMANDS_DISPLAY_WIDTH:
            truncated = truncated[:_UNKNOWN_COMMANDS_DISPLAY_WIDTH] + " ..."
        warning_notices.append(Notice(
            tag=TAG_WARNING,
            label="unknown commands observed",
            summary=(
                f"{len(unknown)} unknown command name{'s' if len(unknown) != 1 else ''} observed"
            ),
            detail=f"commands: {truncated}",
        ))

    # WARNING: agent dispatches without usage
    total_dispatches, with_usage = agent_dispatch_counts(session)
    without_usage = total_dispatches - with_usage
    if without_usage > 0:
        warning_notices.append(Notice(
            tag=TAG_WARNING,
            label="agent dispatches without usage",
            summary=(
                f"{without_usage} of {total_dispatches} agent "
                f"dispatch{'es' if total_dispatches != 1 else ''} "
                "returned no usage data"
            ),
            detail=(
                "delegated token counts for these dispatches are absent; "
                "the cost figure is a lower bound"
            ),
        ))

    # WARNING: subagent files without resolvable model
    subagent_files_without_model = sum(
        view.conversation.subagent_model_index.files_without_model
        for view in session.views
    )
    if subagent_files_without_model > 0:
        subagent_files_seen = sum(
            view.conversation.subagent_model_index.files_seen
            for view in session.views
        )
        warning_notices.append(Notice(
            tag=TAG_WARNING,
            label="subagent files without resolvable model",
            summary=(
                f"{subagent_files_without_model} of {subagent_files_seen} "
                f"subagent file{'s' if subagent_files_seen != 1 else ''} "
                "had no resolvable model"
            ),
            detail=(
                "per-model cost attribution for these files falls back to "
                "the session modal model; the distribution may be imprecise"
            ),
        ))

    # WARNING: slash command markers without rendered body
    slash_dropped = slash_invocation_counts(session)
    if slash_dropped > 0:
        warning_notices.append(Notice(
            tag=TAG_WARNING,
            label="slash command markers without rendered body",
            summary=(
                f"{slash_dropped} slash command "
                f"marker{'s' if slash_dropped != 1 else ''} "
                "had no paired rendered body"
            ),
            detail=(
                "each unpaired marker indicates a local-only command or a "
                "data inconsistency; the invocation did not reach the model"
            ),
        ))

    return tuple(review_notices + warning_notices)


def print_notice_block(notices: tuple[Notice, ...]) -> None:
    """Render ``notices`` to stdout using the shared notice-block grammar.

    When ``notices`` is empty, returns immediately without printing
    anything, so the preceding output bytes are unchanged.

    Each notice is rendered as a tag line followed by a label line
    and one or more detail lines, all indented by two spaces. No
    separator is placed between consecutive notices of the same tag,
    and no trailing blank line follows the final notice.

    Args:
        notices: The ordered tuple of notices to render, as returned
            by ``collect_notices``. REVIEW notices must precede
            WARNING notices; the renderer does not re-sort.

    Returns:
        None.
    """
    if not notices:
        return
    print()
    for notice in notices:
        print(f"[{notice.tag}]")
        print(f"  label: {notice.label}")
        for line in notice.detail.split("\n"):
            print(f"  {line}")
