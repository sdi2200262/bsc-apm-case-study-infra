#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Diagnostics block and invariant evaluator for the metrics artifact.

The diagnostics block surfaces everything the analysis layer needs
to decide whether to include, exclude, or annotate a session: the
count of compaction events (cost reported is a minimum when
non-zero), the number of synthetic assistant records excluded, the
number of Agent dispatches that did not return populated usage,
queue lifecycle warnings, unknown command markers observed,
auxiliary tool-result counts that support the success rate, the
``entrypoint`` and authentication-mode validity flags, the
turns-with-missing-uuid count, and the per-invariant pass-or-fail
status with a numerical residual when a check fails.

Invariants are evaluated once the artifact is otherwise assembled.
A failing identity is recorded as a residual block rather than
raising; the report still emits and the failing entry surfaces in
the analysis layer's diagnostics inspection.
"""

from __future__ import annotations

from typing import Any, Callable

from .commands import (
    extract_command_names,
    is_known_command,
)
from .metrics.economic import compute_session_economic
from .metrics.reliability import compute_reliability_metrics
from .rates import RateTable
from .report_invariants import _evaluate_invariants
from .schema import (
    CONTENT_BLOCK_TOOL_RESULT,
    RECORD_TYPE_USER,
    iter_agent_dispatch_blocks,
    user_prompt_text,
)
from .session import Session
from .user_prompts import (
    is_model_invoked_skill_rendering,
    is_slash_command_marker,
    is_slash_command_rendered_body,
    is_user_authored_prompt,
)

EXPECTED_ENTRYPOINT = "cli"
EXPECTED_AUTH_MODE = "external"


def build_diagnostics(
    session: Session,
    artifact: dict[str, Any],
    rate_table: RateTable,
    is_real_apm_role: Callable[[str], bool],
) -> dict[str, Any]:
    """Assemble the diagnostics block for the metrics artifact.

    ``is_real_apm_role`` is the predicate that distinguishes the
    three real APM role kinds (``planner-N``, ``manager-N``,
    ``worker-N``) from ``unassigned-N`` entries; the role-partition
    invariant fires only when every conversation belongs to a real
    role, since unassigned conversations contribute tokens to
    session and phase totals but not to the roles block.
    """
    compaction_total = sum(
        len(view.conversation.compaction_events) for view in session.views
    )
    compaction_by_file = {
        view.conversation.session_id or view.conversation.path: len(view.conversation.compaction_events)
        for view in session.views
        if view.conversation.compaction_events
    }
    synthetic_excluded = sum(
        view.conversation.usage_index.synthetic_assistant_count
        for view in session.views
    )
    queue_warnings = [
        warning
        for view in session.views
        for warning in view.conversation.queue_lifecycle_warnings
    ]
    unknown_commands = _unknown_commands(session)
    invariants = _evaluate_invariants(artifact, is_real_apm_role)
    agent_dispatches_total, agent_dispatches_with_usage = _agent_dispatch_counts(session)
    metadata = artifact["session_metadata"]
    entrypoint_value = metadata["entrypoint"]
    auth_value = metadata["auth_mode_indicator"]
    tool_result_total, tool_error_total = _tool_result_counts(session)
    turns_with_missing_uuid = sum(
        1 for turn in session.turns if not turn.starting_prompt.uuid
    )
    errored_excluded = sum(
        view.conversation.usage_index.errored_calls_excluded
        for view in session.views
    )
    subagent_files_seen = sum(
        view.conversation.subagent_model_index.files_seen
        for view in session.views
    )
    slash_markers_dropped, model_invoked_skill_renderings = _slash_invocation_counts(session)
    subagent_files_without_model = sum(
        view.conversation.subagent_model_index.files_without_model
        for view in session.views
    )
    subagent_models_indexed = sum(
        len(view.conversation.subagent_model_index.by_agent_id)
        for view in session.views
    )
    economic = compute_session_economic(session, rate_table)
    return {
        "compaction_events_total": compaction_total,
        "compaction_events_by_file": compaction_by_file,
        "cost_excludes_compaction_synthesis": compaction_total > 0,
        "errored_calls_excluded": errored_excluded,
        "synthetic_assistant_records_excluded": synthetic_excluded,
        "agent_dispatches_total": agent_dispatches_total,
        "agent_dispatches_without_usage": agent_dispatches_total - agent_dispatches_with_usage,
        "subagent_files_seen": subagent_files_seen,
        "subagent_files_without_model": subagent_files_without_model,
        "subagent_models_indexed": subagent_models_indexed,
        "subagent_dispatches_resolved_without_index": economic.dispatches_resolved_without_index,
        "subagent_dispatches_bracketed": economic.dispatches_bracketed,
        "slash_command_markers_without_rendered_body": slash_markers_dropped,
        "model_invoked_skill_renderings": model_invoked_skill_renderings,
        "model_token_distribution": economic.model_token_distribution,
        "tool_result_count": tool_result_total,
        "tool_error_count": tool_error_total,
        "queue_lifecycle_warnings": queue_warnings,
        "unknown_commands_observed": unknown_commands,
        "entrypoint_valid": entrypoint_value == EXPECTED_ENTRYPOINT,
        "auth_mode_valid": auth_value == EXPECTED_AUTH_MODE,
        "turns_with_missing_uuid": turns_with_missing_uuid,
        "invariant_checks": invariants,
    }


def _tool_result_counts(session: Session) -> tuple[int, int]:
    """Return ``(total_tool_results, total_errors)`` across every conversation.

    The walk is delegated to ``compute_reliability_metrics`` over the
    session's full record stream so the diagnostics counts and the
    reliability metric share one ``tool_result`` selection rule.
    """
    all_records = [
        record
        for view in session.views
        for record in view.conversation.records
    ]
    metrics = compute_reliability_metrics(all_records)
    return metrics.tool_result_count, metrics.tool_error_count


def _agent_dispatch_counts(session: Session) -> tuple[int, int]:
    """Count Agent dispatches and how many had populated usage at session level.

    The dispatch total is the number of distinct Agent tool_use ids
    observed across non-synthetic assistant records. The
    with-usage count is the number of user records whose
    ``tool_result`` references one of those ids and whose
    ``toolUseResult.usage`` is populated. Matching by tool_use id
    prevents non-Agent tools that may carry their own usage from
    inflating the with-usage count.
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


def _unknown_commands(session: Session) -> list[str]:
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


def _slash_invocation_counts(session: Session) -> tuple[int, int]:
    """Return ``(slash_markers_without_rendered_body, model_invoked_skill_renderings)``.

    A slash marker without a paired rendered body in the same
    ``promptId`` group ran a local-only command or carried a typo;
    the invocation never reached the model and is dropped from
    turn-starting detection. Counting these renders the dropped
    population visible at the diagnostics layer.

    A model-invoked Skill rendering is identical in count to the
    supplementary metric of the same name; it surfaces here for
    parity with the other dispatch counters in this block.
    """
    markers_dropped = 0
    model_invoked_renderings = 0
    for view in session.views:
        promptids_with_rendered_body: set[str] = set()
        for record in view.conversation.records:
            if is_slash_command_rendered_body(record):
                promptid = record.payload.get("promptId")
                if isinstance(promptid, str):
                    promptids_with_rendered_body.add(promptid)
            if is_model_invoked_skill_rendering(record):
                model_invoked_renderings += 1
        for record in view.conversation.records:
            if not is_slash_command_marker(record):
                continue
            promptid = record.payload.get("promptId")
            if not isinstance(promptid, str):
                markers_dropped += 1
                continue
            if promptid not in promptids_with_rendered_body:
                markers_dropped += 1
    return markers_dropped, model_invoked_renderings
