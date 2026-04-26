#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
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

from typing import Any

from .commands import (
    extract_command_names,
    is_known_command,
)
from .rates import RateTable
from .schema import (
    SYNTHETIC_MODEL_MARKER,
    is_genuine_user_prompt,
    user_prompt_text,
)
from .session import Session

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
    is_real_apm_role: Any,
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
    return {
        "compaction_events_total": compaction_total,
        "compaction_events_by_file": compaction_by_file,
        "cost_excludes_compaction_synthesis": compaction_total > 0,
        "synthetic_assistant_records_excluded": synthetic_excluded,
        "agent_dispatches_total": agent_dispatches_total,
        "agent_dispatches_without_usage": agent_dispatches_total - agent_dispatches_with_usage,
        "tool_result_count": tool_result_total,
        "tool_error_count": tool_error_total,
        "queue_lifecycle_warnings": queue_warnings,
        "unknown_commands_observed": unknown_commands,
        "entrypoint_valid": entrypoint_value == EXPECTED_ENTRYPOINT,
        "auth_mode_valid": auth_value == EXPECTED_AUTH_MODE,
        "turns_with_missing_uuid": turns_with_missing_uuid,
        "invariant_checks": invariants,
        "notes": [
            "cost_usd is the API-equivalent cost from visible API calls "
            "and excludes the synthesis cost of compaction events when present.",
            "reasoning_token_share is approximated from character counts because "
            "message.usage.output_tokens does not split by content block type.",
        ],
    }


def _evaluate_invariants(
    artifact: dict[str, Any],
    rate_table: RateTable,
    is_real_apm_role: Any,
) -> dict[str, Any]:
    """Evaluate every invariant identity across every scope.

    Walks session, every phase, and every role scope. For each
    scope checks the time composition (where defined), the
    per-category token composition (main + delegated == total),
    the prompt-token composition, the cost composition against
    the rate table, the steer accounting, and the bucket share
    sums. Records partition is also checked: phase tokens and
    role tokens should sum to the session totals for each
    category. Each check returns ``{"status": "ok"}`` when within
    tolerance and a residual block otherwise.
    """
    checks: dict[str, Any] = {}
    pinned_model = artifact["session_metadata"]["model"]
    rates = rate_table.models.get(pinned_model)
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
        if rates is not None:
            expected_cost = (
                economic["total_input_tokens"]["value"] * rates.input
                + economic["total_output_tokens"]["value"] * rates.output
                + economic["total_cache_read_tokens"]["value"] * rates.cache_read
                + economic["total_cache_5m_tokens"]["value"] * rates.cache_5m
                + economic["total_cache_1h_tokens"]["value"] * rates.cache_1h
            ) / 1_000_000.0
            checks[f"cost_composition_{scope_label}"] = _check_close(
                economic["cost_usd"]["value"], expected_cost, INVARIANT_TOLERANCE_USD
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
    return checks


def _every_conversation_has_real_role(artifact: dict[str, Any], is_real_apm_role: Any) -> bool:
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
    """Count Agent dispatches and how many had populated usage at session level."""
    total = 0
    with_usage = 0
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
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Agent":
                    total += 1
        for record in view.conversation.records:
            if record.record_type != "user":
                continue
            tool_use_result = record.payload.get("toolUseResult")
            if isinstance(tool_use_result, dict) and isinstance(tool_use_result.get("usage"), dict):
                with_usage += 1
    return total, with_usage


def _unknown_commands(session: Session) -> list[str]:
    """Return the sorted set of command names observed that are not in the known set."""
    seen: set[str] = set()
    for view in session.views:
        for record in view.conversation.records:
            if not is_genuine_user_prompt(record):
                continue
            for command in extract_command_names(user_prompt_text(record)):
                if not is_known_command(command):
                    seen.add(command)
    return sorted(seen)
