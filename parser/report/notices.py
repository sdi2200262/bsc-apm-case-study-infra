# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Session-attention notices for the parser's CLI summary modes.

A ``Notice`` captures a single condition that an analyst should be
aware of before interpreting or accepting a session's metrics. Two
tags are defined: ``REVIEW`` for conditions that are qualitatively
ambiguous and require human judgment, and ``WARNING`` for conditions
that are objectively abnormal and require no judgment to classify.

``collect_notices`` inspects a loaded ``Session`` and returns the
full tuple of applicable notices, REVIEW notices first, then WARNING
notices, in deterministic iteration order within each group. Rendering
is not done here: a caller hands the collected notices to the terminal
logging module's ``notice_block`` to emit them.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.aggregate.tokens import compute_session_token_data
from ..data.commands import extract_command_names, is_known_command
from ..data.prompts import (
    is_slash_command_marker,
    is_slash_command_rendered_body,
    is_user_authored_prompt,
)
from ..data.schema import (
    CONTENT_BLOCK_TOOL_RESULT,
    RECORD_TYPE_USER,
    iter_agent_dispatch_blocks,
    user_prompt_text,
)
from ..data.session import Session, session_health_signals

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
        distinct = sorted(
            {
                str(entry.get("skill", ""))
                for entry in session.backward_skill_invocations
                if entry.get("skill")
            }
        )
        skills_str = ", ".join(distinct) if distinct else "(none)"
        review_notices.append(
            Notice(
                tag=TAG_REVIEW,
                label="backward skill invocations",
                summary=(
                    f"{count} backward invocation{'s' if count != 1 else ''} observed; "
                    f"distinct skills: {skills_str}"
                ),
                detail="cue: audit this session before drawing phase-distribution conclusions",
            )
        )

    # REVIEW: turns with missing uuid
    missing_uuid_count = turns_with_missing_uuid_count(session)
    if missing_uuid_count > 0:
        review_notices.append(
            Notice(
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
            )
        )

    # WARNING: queue lifecycle warnings
    total_queue_warnings = sum(
        len(view.conversation.queue_lifecycle_warnings) for view in session.views
    )
    files_with_warnings = sum(
        1 for view in session.views if view.conversation.queue_lifecycle_warnings
    )
    if total_queue_warnings > 0:
        warning_notices.append(
            Notice(
                tag=TAG_WARNING,
                label="queue lifecycle warnings",
                summary=(
                    f"{total_queue_warnings} queue lifecycle "
                    f"warning{'s' if total_queue_warnings != 1 else ''} observed "
                    f"across {files_with_warnings} "
                    f"conversation file{'s' if files_with_warnings != 1 else ''}"
                ),
                detail=(
                    "inspect view.conversation.queue_lifecycle_warnings for the per-file detail"
                ),
            )
        )

    # WARNING: unknown commands
    unknown = unknown_commands(session)
    if unknown:
        truncated = ", ".join(unknown)
        if len(truncated) > _UNKNOWN_COMMANDS_DISPLAY_WIDTH:
            truncated = truncated[:_UNKNOWN_COMMANDS_DISPLAY_WIDTH] + " ..."
        warning_notices.append(
            Notice(
                tag=TAG_WARNING,
                label="unknown commands observed",
                summary=(
                    f"{len(unknown)} unknown command name"
                    f"{'s' if len(unknown) != 1 else ''} observed"
                ),
                detail=f"commands: {truncated}",
            )
        )

    # WARNING: agent dispatches without usage
    total_dispatches, with_usage = agent_dispatch_counts(session)
    without_usage = total_dispatches - with_usage
    if without_usage > 0:
        warning_notices.append(
            Notice(
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
            )
        )

    # WARNING: subagent files without resolvable model
    subagent_files_seen, subagent_files_without_model = subagent_file_counts(session)
    if subagent_files_without_model > 0:
        warning_notices.append(
            Notice(
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
            )
        )

    # WARNING: slash command markers without rendered body
    slash_dropped = slash_invocation_counts(session)
    if slash_dropped > 0:
        warning_notices.append(
            Notice(
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
            )
        )

    health = session_health_signals(session)

    # REVIEW: model drift
    if health["model_drift"]:
        review_notices.append(
            Notice(
                tag=TAG_REVIEW,
                label="model drift",
                summary="more than one distinct model observed across the session",
                detail="cue: per-model attribution mixes models; confirm the intended model",
            )
        )

    # REVIEW: cost is a floor (compaction synthesis excluded)
    compaction_total = sum(len(view.conversation.compaction_events) for view in session.views)
    if compaction_total > 0:
        review_notices.append(
            Notice(
                tag=TAG_REVIEW,
                label="cost is a floor",
                summary=(
                    f"{compaction_total} compaction "
                    f"event{'s' if compaction_total != 1 else ''} observed"
                ),
                detail="cost excludes compaction synthesis; the figure is a lower bound",
            )
        )

    # REVIEW: cost is a range (bracketed dispatches)
    bracketed = compute_session_token_data(session).dispatches_bracketed
    if bracketed > 0:
        review_notices.append(
            Notice(
                tag=TAG_REVIEW,
                label="cost is a range",
                summary=(
                    f"{bracketed} dispatch{'es' if bracketed != 1 else ''} "
                    "priced at a model bracket"
                ),
                detail="bracketed dispatches widen the cost into a range, not a point",
            )
        )

    # WARNING: unexpected entrypoint
    if health["entrypoint"] != "cli":
        warning_notices.append(
            Notice(
                tag=TAG_WARNING,
                label="unexpected entrypoint",
                summary=f"entrypoint is {health['entrypoint']!r}, expected 'cli'",
                detail="the session did not originate from the CLI entrypoint",
            )
        )

    # WARNING: unexpected auth mode
    if health["auth_mode_indicator"] != "external":
        warning_notices.append(
            Notice(
                tag=TAG_WARNING,
                label="unexpected auth mode",
                summary=(f"auth mode is {health['auth_mode_indicator']!r}, expected 'external'"),
                detail="the session did not use the expected external authentication mode",
            )
        )

    # WARNING: errored calls excluded
    errored_excluded = sum(
        view.conversation.usage_index.errored_calls_excluded for view in session.views
    )
    if errored_excluded > 0:
        warning_notices.append(
            Notice(
                tag=TAG_WARNING,
                label="errored calls excluded",
                summary=(
                    f"{errored_excluded} errored "
                    f"call{'s' if errored_excluded != 1 else ''} excluded from usage"
                ),
                detail="errored assistant records carry no usable usage and are dropped",
            )
        )

    return tuple(review_notices + warning_notices)


def agent_dispatch_counts(session: Session) -> tuple[int, int]:
    """Count Agent dispatches and how many had populated usage at session level.

    The dispatch total is the number of distinct Agent tool_use ids observed
    across non-synthetic assistant records. The with-usage count is the number
    of user records whose ``tool_result`` references one of those ids and
    whose ``toolUseResult.usage`` is populated. Matching by tool_use id
    prevents non-Agent tools that may carry their own usage from inflating the
    with-usage count.
    """
    agent_tool_use_ids: set[str] = set()
    for view in session.views:
        for _record, block in iter_agent_dispatch_blocks(view.conversation.records):
            tool_use_id = block.get("id")
            if isinstance(tool_use_id, str):
                agent_tool_use_ids.add(tool_use_id)
    total = len(agent_tool_use_ids)
    with_usage = 0
    for view in session.views:
        for record in view.conversation.records:
            if record.record_type != RECORD_TYPE_USER:
                continue
            tool_use_result = record.payload.get("toolUseResult")
            if not isinstance(tool_use_result, dict):
                continue
            if not isinstance(tool_use_result.get("usage"), dict):
                continue
            message = record.payload.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != CONTENT_BLOCK_TOOL_RESULT:
                    continue
                tool_use_id = block.get("tool_use_id")
                if isinstance(tool_use_id, str) and tool_use_id in agent_tool_use_ids:
                    with_usage += 1
                    break
    return total, with_usage


def unknown_commands(session: Session) -> list[str]:
    """Return the sorted set of command names observed that are not in the known set."""
    seen: set[str] = set()
    for view in session.views:
        for record in view.conversation.records:
            if not is_user_authored_prompt(record):
                continue
            for command in extract_command_names(user_prompt_text(record)):
                if not is_known_command(command):
                    seen.add(command)
    return sorted(seen)


def slash_invocation_counts(session: Session) -> int:
    """Return the count of slash markers without a paired rendered body.

    A slash marker without a paired rendered body in the same ``promptId``
    group ran a local-only command or carried a typo; the invocation never
    reached the model and is dropped from turn-starting detection. Counting
    these renders the dropped population visible.
    """
    markers_dropped = 0
    for view in session.views:
        promptids_with_rendered_body: set[str] = set()
        for record in view.conversation.records:
            if is_slash_command_rendered_body(record):
                promptid = record.payload.get("promptId")
                if isinstance(promptid, str):
                    promptids_with_rendered_body.add(promptid)
        for record in view.conversation.records:
            if not is_slash_command_marker(record):
                continue
            promptid = record.payload.get("promptId")
            if not isinstance(promptid, str):
                markers_dropped += 1
                continue
            if promptid not in promptids_with_rendered_body:
                markers_dropped += 1
    return markers_dropped


def turns_with_missing_uuid_count(session: Session) -> int:
    """Return the count of turns whose starting prompt carries no uuid."""
    return sum(1 for turn in session.turns if not turn.starting_prompt.uuid)


def subagent_file_counts(session: Session) -> tuple[int, int]:
    """Return ``(files_seen, files_without_model)`` across every conversation.

    ``files_seen`` is the total subagent file count and ``files_without_model``
    is the subset whose model could not be resolved.
    """
    files_seen = sum(view.conversation.subagent_model_index.files_seen for view in session.views)
    files_without_model = sum(
        view.conversation.subagent_model_index.files_without_model for view in session.views
    )
    return files_seen, files_without_model
