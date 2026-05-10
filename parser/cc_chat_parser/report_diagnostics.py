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
from .rates import RateTable
from .schema import (
    SYNTHETIC_MODEL_MARKER,
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

INVARIANT_TOLERANCE_SECONDS = 0.001
INVARIANT_TOLERANCE_RATIO = 1e-9
INVARIANT_TOLERANCE_USD = 0.01
INVARIANT_TOLERANCE_TOKENS = 0


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
    invariants = _evaluate_invariants(artifact, rate_table, is_real_apm_role)
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
        "notes": [
            "cost is the API-equivalent cost from visible API calls "
            "and excludes the synthesis cost of compaction events when present.",
            "cost is summed call by call: each main call priced at its own "
            "message.model, each delegated dispatch priced at the subagent's "
            "model. The model is read from the sibling subagents/ directory "
            "when shipped, otherwise resolved by the documented fallback in "
            "subagents.resolve_unindexed_subagent_model.",
            "the cost shape is conditional: a single cost_usd leaf when every "
            "delegated dispatch was priced deterministically, a "
            "(cost_usd_lower_bound, cost_usd_upper_bound) pair when at least "
            "one dispatch was bracketed by the resolver.",
            "synthetic_assistant_records_excluded counts placeholder assistant "
            "records the local Claude Code client writes around session "
            "boundaries and adjacent to compaction events to keep the "
            "user-assistant alternation balanced. Their emission is "
            "independent of compaction event count: a session can produce "
            "more, fewer, or the same number of synthetic placeholders as "
            "compaction events, and the two should not be read as paired.",
        ],
    }


def _evaluate_invariants(
    artifact: dict[str, Any],
    rate_table: RateTable,
    is_real_apm_role: Callable[[str], bool],
) -> dict[str, Any]:
    """Evaluate every invariant identity across every scope.

    Walks session, every phase, and every role scope. For each
    scope checks the time composition (where defined), the
    per-category token composition (main + delegated == total),
    the prompt-token composition, the steer accounting, and the
    bucket share sums. Records partition is also checked: phase
    and role aggregations should sum to the session totals for
    every economic category and every supplementary count. Each
    check returns ``{"status": "ok"}`` when within tolerance and
    a residual block otherwise.

    Cost is no longer cross-checked against a single-rate
    arithmetic identity. With per-call pricing each call is priced
    at its own model's rates, and the session's mixed-model token
    population does not reduce to a single rate. The
    ``model_token_distribution`` and the
    ``delegated_priced_via_*`` counters surface the attribution
    mix instead.
    """
    checks: dict[str, Any] = {}
    scopes: list[tuple[str, dict[str, Any]]] = [("session", artifact["session"])]
    for phase, block in artifact["phases"].items():
        scopes.append((f"phase_{phase}", block))
    for role, block in artifact.get("roles", {}).items():
        scopes.append((f"role_{role}", block))
    for scope_label, block in scopes:
        time_block = block["process"]["time"]
        if "duration" in time_block and "inter_turn_time" in time_block:
            checks[f"time_composition_{scope_label}"] = _check_close(
                time_block["duration"]["value"],
                time_block["turn_time"]["value"] + time_block["inter_turn_time"]["value"],
                INVARIANT_TOLERANCE_SECONDS,
            )
        if "turn_time_solo" in time_block and "turn_time_concurrent" in time_block:
            checks[f"turn_time_decomposition_{scope_label}"] = _check_close(
                time_block["turn_time"]["value"],
                time_block["turn_time_solo"]["value"] + time_block["turn_time_concurrent"]["value"],
                INVARIANT_TOLERANCE_SECONDS,
            )
        economic = block["economic"]
        for category in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
            checks[f"token_composition_{scope_label}_{category}"] = _check_close(
                economic[f"total_{category}_tokens"]["value"],
                economic[f"main_{category}_tokens"]["value"]
                + economic[f"delegated_{category}_tokens"]["value"],
                INVARIANT_TOLERANCE_TOKENS,
            )
        checks[f"prompt_token_composition_{scope_label}"] = _check_close(
            economic["total_prompt_tokens"]["value"],
            economic["total_input_tokens"]["value"]
            + economic["total_cache_read_tokens"]["value"]
            + economic["total_cache_5m_tokens"]["value"]
            + economic["total_cache_1h_tokens"]["value"],
            INVARIANT_TOLERANCE_TOKENS,
        )
        user_input = block["process"]["user_input"]
        checks[f"steer_accounting_{scope_label}"] = _check_close(
            user_input["steer_attempted_count"]["value"],
            user_input["steer_delivered_count"]["value"]
            + user_input["steer_abandoned_count"]["value"],
            0,
        )
        for share_key, denominator in (
            ("turn_prompts_bucket_shares",
             user_input["turn_prompt_count"]["value"]),
            ("steer_delivered_bucket_shares",
             user_input["steer_delivered_count"]["value"]),
            ("all_inputs_bucket_shares",
             user_input["turn_prompt_count"]["value"]
             + user_input["steer_delivered_count"]["value"]),
        ):
            shares = user_input[share_key]["value"]
            expected = 1.0 if denominator > 0 else 0.0
            checks[f"bucket_shares_{share_key}_{scope_label}"] = _check_close(
                sum(shares.values()), expected, INVARIANT_TOLERANCE_RATIO
            )
    session_economic = artifact["session"]["economic"]
    for category in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
        phase_sum = sum(
            artifact["phases"][phase]["economic"][f"total_{category}_tokens"]["value"]
            for phase in artifact["phases"]
        )
        checks[f"phase_partition_{category}"] = _check_close(
            session_economic[f"total_{category}_tokens"]["value"],
            phase_sum,
            INVARIANT_TOLERANCE_TOKENS,
        )
    session_supplementary = artifact["session"]["supplementary"]
    for field in ("subagent_count", "subagent_tool_count", "model_invoked_skill_count"):
        phase_sum = sum(
            artifact["phases"][phase]["supplementary"][field]["value"]
            for phase in artifact["phases"]
        )
        checks[f"phase_partition_{field}"] = _check_close(
            session_supplementary[field]["value"],
            phase_sum,
            0,
        )
    # Role partition only holds when every conversation in the
    # session has a real APM role. Sessions with one or more
    # ``unassigned-N`` conversations contribute tokens to the
    # session and phase totals but do not appear in the roles
    # block, so the role-sum identity is partial by design.
    if "roles" in artifact and _every_conversation_has_real_role(artifact, is_real_apm_role):
        for category in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
            role_sum = sum(
                artifact["roles"][role]["economic"][f"total_{category}_tokens"]["value"]
                for role in artifact["roles"]
            )
            checks[f"role_partition_{category}"] = _check_close(
                session_economic[f"total_{category}_tokens"]["value"],
                role_sum,
                INVARIANT_TOLERANCE_TOKENS,
            )
        for field in ("subagent_count", "subagent_tool_count", "model_invoked_skill_count"):
            role_sum = sum(
                artifact["roles"][role]["supplementary"][field]["value"]
                for role in artifact["roles"]
            )
            checks[f"role_partition_{field}"] = _check_close(
                session_supplementary[field]["value"],
                role_sum,
                0,
            )
    return checks


def _every_conversation_has_real_role(artifact: dict[str, Any], is_real_apm_role: Callable[[str], bool]) -> bool:
    """Return ``True`` when every conversation in metadata is a real APM role."""
    conversations = artifact["session_metadata"]["conversations"]
    return all(is_real_apm_role(conv["role_key"]) for conv in conversations)


def _check_close(left: float, right: float, tolerance: float) -> dict[str, Any]:
    """Return ``{"status": "ok"}`` when within tolerance, otherwise residuals."""
    residual = abs(left - right)
    if residual <= tolerance:
        return {"status": "ok"}
    return {"status": "fail", "left": left, "right": right, "residual": residual}


def _tool_result_counts(session: Session) -> tuple[int, int]:
    """Return ``(total_tool_results, total_errors)`` across every conversation."""
    total = 0
    errors = 0
    for view in session.views:
        for record in view.conversation.records:
            if record.record_type != "user":
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
                if block.get("type") != "tool_result":
                    continue
                total += 1
                if block.get("is_error") is True:
                    errors += 1
    return total, errors


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
        for record in view.conversation.records:
            if record.record_type != "assistant":
                continue
            message = record.payload.get("message")
            if not isinstance(message, dict):
                continue
            if message.get("model") == SYNTHETIC_MODEL_MARKER:
                continue
            for block in message.get("content", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use" or block.get("name") != "Agent":
                    continue
                tool_use_id = block.get("id")
                if isinstance(tool_use_id, str):
                    agent_tool_use_ids.add(tool_use_id)
    total = len(agent_tool_use_ids)
    with_usage = 0
    for view in session.views:
        for record in view.conversation.records:
            if record.record_type != "user":
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
                if block.get("type") != "tool_result":
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
