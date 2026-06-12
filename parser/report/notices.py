# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Session-attention notices for the parser's CLI summary modes.

A ``Notice`` flags one condition to weigh before accepting a session's metrics:
``REVIEW`` for a qualitatively ambiguous one needing judgment, ``WARNING`` for
an objectively abnormal one. ``collect_notices`` returns them REVIEW before
WARNING, deterministically; the logging module's ``notice_block`` renders them.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.aggregate.call_records import ModelPurityReport, ModelSwitch, compute_model_purity
from ..data.aggregate.counts import compute_tool_counts
from ..data.aggregate.tokens import compute_session_token_data
from ..data.aggregate.turn_series import turns_in_phase
from ..data.commands import (
    FRAMEWORK_SPECKIT,
    PHASE_IMPLEMENTATION,
    extract_command_names,
    is_known_command,
)
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
from ..data.session_cap import cap_overrun_detail, cap_overrun_summary

TAG_REVIEW = "REVIEW"
TAG_WARNING = "WARNING"

_UNKNOWN_COMMANDS_DISPLAY_WIDTH = 120


@dataclass(frozen=True)
class Notice:
    """A single session-attention signal surfaced in the CLI summary.

    Attributes:
        tag: ``"REVIEW"`` (qualitatively ambiguous; needs human judgment) or
            ``"WARNING"`` (objectively abnormal; no judgment to classify).
        label: A short identifier for the condition.
        summary: One sentence naming the condition and its magnitude.
        detail: A concrete next step or downstream impact; may equal ``summary``.
    """

    tag: str
    label: str
    summary: str
    detail: str


def collect_notices(session: Session) -> tuple[Notice, ...]:
    """Return every applicable notice for ``session``, REVIEW before WARNING.

    A pure aggregator (no I/O or mutation); conditions check in a fixed order.
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

    # REVIEW: activity past the session cap
    if session.cap_filter.dropped:
        review_notices.append(
            Notice(
                tag=TAG_REVIEW,
                label="activity past session cap",
                summary=cap_overrun_summary(session),
                detail=cap_overrun_detail(session),
            )
        )

    # REVIEW: spec-kit implementation phase never reached
    if speckit_implementation_ratchet_unreached(session):
        review_notices.append(
            Notice(
                tag=TAG_REVIEW,
                label="spec-kit implementation phase never reached",
                summary=(
                    "spec-kit session did tool-driven work but reached zero "
                    "implementation-phase turns; the planning-vs-implementation split is unreliable"
                ),
                detail=(
                    "the implementation ratchet never advanced (no speckit-implement issued), so "
                    "implementation-scale work likely ran inside planning-labelled turns; treat "
                    "the split as planning-inflated and confirm the phase boundary before using it"
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

    # REVIEW: model purity (multi-model conversations and off-assignment calls)
    review_notices.extend(model_purity_notices(session))

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


def speckit_implementation_ratchet_unreached(session: Session) -> bool:
    """Return ``True`` when a working spec-kit session never reached implementation.

    Fires for spec-kit only when no turn is assigned implementation (the ratchet
    never advanced, no ``speckit-implement`` issued) yet the session did
    tool-driven work; ``tool_result_count > 0`` keeps a planning-only session
    unflagged.
    """
    if session.framework != FRAMEWORK_SPECKIT:
        return False
    if any(True for _ in turns_in_phase(session, PHASE_IMPLEMENTATION)):
        return False
    scope_records = [record for view in session.views for record in view.conversation.records]
    return compute_tool_counts(scope_records).tool_result_count > 0


def model_purity_notices(session: Session) -> list[Notice]:
    """Return the model-purity REVIEW notices, empty when the session is model-pure.

    A conversation whose main calls bill on more than one model is impure: every
    model change raises a notice naming the conversation, the prior and new
    models, the time, and whether a user ``/model`` command backed it or it fell
    back silently. A leading summary carries the per-model counts and the share
    of calls off the assigned (modal) model. A single ``/model`` at startup
    leaves one billed model, so it raises nothing.
    """
    report = compute_model_purity(session)
    if not report.switches and report.off_assignment_calls == 0:
        return []
    notices = [_model_purity_summary_notice(report)]
    notices.extend(_switch_notice(switch) for switch in report.switches)
    return notices


def _model_purity_summary_notice(report: ModelPurityReport) -> Notice:
    """Build the summary notice: switch breakdown, per-model counts, off-assignment share."""
    counts_str = ", ".join(
        f"{model}: {report.per_model_counts[model]}" for model in sorted(report.per_model_counts)
    )
    total = len(report.switches)
    silent = len(report.silent_switches)
    return Notice(
        tag=TAG_REVIEW,
        label="model purity",
        summary=(
            f"{total} main-model switch{'es' if total != 1 else ''} observed "
            f"({silent} silent, {total - silent} user-backed); "
            f"{report.off_assignment_calls} of {report.total_main_calls} deduped main "
            f"calls ({report.off_assignment_fraction:.1%}) billed off the assigned model "
            f"{report.assigned_model or '(none)'!r}"
        ),
        detail=(
            f"per-model deduped main-call counts: {counts_str or '(none)'}; "
            "cue: confirm the session ran on the assigned model"
        ),
    )


def _switch_notice(switch: ModelSwitch) -> Notice:
    """Build the per-switch notice, classified by whether a user ``/model`` backed it."""
    when = switch.timestamp.isoformat() if switch.timestamp is not None else "(no timestamp)"
    cause = (
        "a user /model command preceded it"
        if switch.backed
        else "no user /model command preceded it (silent fallback)"
    )
    return Notice(
        tag=TAG_REVIEW,
        label="main-model switch",
        summary=(
            f"{switch.role_key}: main model changed from "
            f"{switch.from_model or '(none)'} to {switch.to_model or '(none)'} at {when}"
        ),
        detail=f"{cause}; cue: confirm whether the off-model calls belong in the cohort record",
    )


def agent_dispatch_counts(session: Session) -> tuple[int, int]:
    """Return ``(total_dispatches, with_usage)`` for Agent tool calls in ``session``.

    Matched by tool_use id so a non-Agent tool's own usage cannot inflate it.
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

    An unpaired marker (same ``promptId``) ran a local-only command or a typo;
    the invocation never reached the model.
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
    """Return ``(files_seen, files_without_model)`` across every conversation."""
    files_seen = sum(view.conversation.subagent_model_index.files_seen for view in session.views)
    files_without_model = sum(
        view.conversation.subagent_model_index.files_without_model for view in session.views
    )
    return files_seen, files_without_model
