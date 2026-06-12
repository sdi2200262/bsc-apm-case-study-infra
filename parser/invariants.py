# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Invariant evaluator for the metrics artifact.

Once the artifact is otherwise assembled, every invariant identity
is checked across every scope: the time composition, the
per-category token composition, the prompt-token composition, the
steer accounting, the bucket share sums, and the phase and role
partition identities. A failing identity is recorded as a residual
block rather than raising, so the report still emits and the
failing entry surfaces in the analysis layer's diagnostics
inspection.

This module is a leaf: it operates on the assembled artifact dict
and the real-APM-role predicate, with no parser-package
dependencies. It is imported by ``data.diagnostics`` for the
diagnostics block.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

INVARIANT_TOLERANCE_SECONDS = 0.001
INVARIANT_TOLERANCE_RATIO = 1e-9
INVARIANT_TOLERANCE_TOKENS = 0


def _evaluate_invariants(
    artifact: dict[str, Any],
    is_real_apm_role: Callable[[str], bool],
) -> dict[str, Any]:
    """Evaluate every invariant identity across every scope.

    Walks session, every phase, and every role scope. For each
    scope checks the time composition (where defined), the
    per-category token composition (main + delegated == total),
    the prompt-token composition, the steer accounting, the
    bucket share sums, and the request-count mirror between the
    economic and process dimensions. Records partition is also
    checked: phase and role aggregations should sum to the
    session totals for every economic category, every
    supplementary count, the five additive process counts (turn
    count, turn-prompt count, and the three steer counts), and
    the three request-population counts. Each check returns
    ``{"status": "ok"}`` when within tolerance and a residual
    block otherwise.

    Cost is not cross-checked against a single-rate arithmetic
    identity. With per-call pricing each call is priced at its own
    model's rates, and the session's mixed-model token population
    does not reduce to a single rate. The
    ``model_token_distribution`` and the
    ``subagent_dispatches_resolved_without_index`` and
    ``subagent_dispatches_bracketed`` counters surface the
    attribution mix instead.
    """
    results: dict[str, Any] = {}
    scopes: list[tuple[str, dict[str, Any]]] = [("session", artifact["session"])]
    for phase, block in artifact["phases"].items():
        scopes.append((f"phase_{phase}", block))
    for role, block in artifact.get("roles", {}).items():
        scopes.append((f"role_{role}", block))
    for scope_label, block in scopes:
        time_block = block["process"]["time"]
        if "duration" in time_block and "inter_turn_time" in time_block:
            results[f"time_composition_{scope_label}"] = _assert_close(
                time_block["duration"]["value"],
                time_block["turn_time"]["value"] + time_block["inter_turn_time"]["value"],
                INVARIANT_TOLERANCE_SECONDS,
            )
        if "turn_time_solo" in time_block and "turn_time_concurrent" in time_block:
            results[f"turn_time_decomposition_{scope_label}"] = _assert_close(
                time_block["turn_time"]["value"],
                time_block["turn_time_solo"]["value"] + time_block["turn_time_concurrent"]["value"],
                INVARIANT_TOLERANCE_SECONDS,
            )
        economic = block["economic"]
        for category in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
            results[f"token_composition_{scope_label}_{category}"] = _assert_close(
                economic[f"total_{category}_tokens"]["value"],
                economic[f"main_{category}_tokens"]["value"]
                + economic[f"delegated_{category}_tokens"]["value"],
                INVARIANT_TOLERANCE_TOKENS,
            )
        results[f"prompt_token_composition_{scope_label}"] = _assert_close(
            economic["total_prompt_tokens"]["value"],
            economic["total_input_tokens"]["value"]
            + economic["total_cache_read_tokens"]["value"]
            + economic["total_cache_5m_tokens"]["value"]
            + economic["total_cache_1h_tokens"]["value"],
            INVARIANT_TOLERANCE_TOKENS,
        )
        user_input = block["process"]["user_input"]
        results[f"steer_accounting_{scope_label}"] = _assert_close(
            user_input["steer_attempted_count"]["value"],
            user_input["steer_delivered_count"]["value"]
            + user_input["steer_abandoned_count"]["value"],
            0,
        )
        # ``request_count`` and ``delegated_request_count`` are mirrored
        # from the process-dimension requests block into the economic
        # block so consumers can read either dimension's leaves without
        # cross-referencing. The mirror is a leaf copy, not a derived
        # quantity, so the identity holds exactly.
        process_requests = block["process"]["requests"]
        for field in ("request_count", "delegated_request_count"):
            results[f"economic_requests_mirror_{scope_label}_{field}"] = _assert_close(
                economic[field]["value"],
                process_requests[field]["value"],
                0,
            )
        for share_key, denominator in (
            ("turn_prompts_bucket_shares", user_input["turn_prompt_count"]["value"]),
            ("steer_delivered_bucket_shares", user_input["steer_delivered_count"]["value"]),
            (
                "all_inputs_bucket_shares",
                user_input["turn_prompt_count"]["value"]
                + user_input["steer_delivered_count"]["value"],
            ),
        ):
            shares = user_input[share_key]["value"]
            expected = 1.0 if denominator > 0 else 0.0
            results[f"bucket_shares_{share_key}_{scope_label}"] = _assert_close(
                sum(shares.values()), expected, INVARIANT_TOLERANCE_RATIO
            )
    session_economic = artifact["session"]["economic"]
    for category in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
        phase_sum = sum(
            artifact["phases"][phase]["economic"][f"total_{category}_tokens"]["value"]
            for phase in artifact["phases"]
        )
        results[f"phase_partition_{category}"] = _assert_close(
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
        results[f"phase_partition_{field}"] = _assert_close(
            session_supplementary[field]["value"],
            phase_sum,
            0,
        )
    # Process counts that partition cleanly: each turn, prompt, or
    # steer event belongs to exactly one phase (and one role for the
    # all-real-roles case). Wall-clock measures (duration,
    # inter_turn_time) and turn-time aggregates do not partition by
    # the same identity because cross-conversation overlaps are real
    # at the session level; those carry their own decomposition
    # invariants instead.
    session_process = artifact["session"]["process"]
    for subblock, field in (
        ("time", "turn_count"),
        ("user_input", "turn_prompt_count"),
        ("user_input", "steer_attempted_count"),
        ("user_input", "steer_delivered_count"),
        ("user_input", "steer_abandoned_count"),
    ):
        phase_sum = sum(
            artifact["phases"][phase]["process"][subblock][field]["value"]
            for phase in artifact["phases"]
        )
        results[f"phase_partition_{field}"] = _assert_close(
            session_process[subblock][field]["value"],
            phase_sum,
            0,
        )
    # Request-count fields partition cleanly across phases: each
    # request is tagged with the phase of its triggering record, so
    # the per-phase counts sum to the session count for every
    # request-population leaf the process-dimension exposes.
    session_requests = session_process["requests"]
    for field in ("request_count", "delegated_request_count", "requests_with_tool_use_count"):
        phase_sum = sum(
            artifact["phases"][phase]["process"]["requests"][field]["value"]
            for phase in artifact["phases"]
        )
        results[f"phase_partition_{field}"] = _assert_close(
            session_requests[field]["value"],
            phase_sum,
            0,
        )
    # Per-turn phase share buckets must sum to the turn's main
    # request count. The turn renderer emits ``request_count``
    # alongside ``phase_request_share``; the two derive from the
    # same record sweep but are computed independently, so a
    # divergence would indicate a builder bug. Each turn's
    # identity is checked separately so a divergence on one turn
    # is not masked by aggregation.
    for index, turn in enumerate(artifact.get("turns", [])):
        share = turn.get("phase_request_share")
        if not isinstance(share, dict):
            continue
        request_count = turn.get("request_count")
        if not isinstance(request_count, int):
            continue
        share_sum = sum(int(v) for v in share.values())
        results[f"turn_phase_request_share_sum_{index}"] = _assert_close(
            share_sum,
            request_count,
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
            results[f"role_partition_{category}"] = _assert_close(
                session_economic[f"total_{category}_tokens"]["value"],
                role_sum,
                INVARIANT_TOLERANCE_TOKENS,
            )
        for field in ("subagent_count", "subagent_tool_count", "model_invoked_skill_count"):
            role_sum = sum(
                artifact["roles"][role]["supplementary"][field]["value"]
                for role in artifact["roles"]
            )
            results[f"role_partition_{field}"] = _assert_close(
                session_supplementary[field]["value"],
                role_sum,
                0,
            )
        for subblock, field in (
            ("time", "turn_count"),
            ("user_input", "turn_prompt_count"),
            ("user_input", "steer_attempted_count"),
            ("user_input", "steer_delivered_count"),
            ("user_input", "steer_abandoned_count"),
        ):
            role_sum = sum(
                artifact["roles"][role]["process"][subblock][field]["value"]
                for role in artifact["roles"]
            )
            results[f"role_partition_{field}"] = _assert_close(
                session_process[subblock][field]["value"],
                role_sum,
                0,
            )
        for field in ("request_count", "delegated_request_count", "requests_with_tool_use_count"):
            role_sum = sum(
                artifact["roles"][role]["process"]["requests"][field]["value"]
                for role in artifact["roles"]
            )
            results[f"role_partition_{field}"] = _assert_close(
                session_requests[field]["value"],
                role_sum,
                0,
            )
    return results


def _every_conversation_has_real_role(
    artifact: dict[str, Any], is_real_apm_role: Callable[[str], bool]
) -> bool:
    """Return ``True`` when every conversation in metadata is a real APM role."""
    conversations = artifact["session_metadata"]["conversations"]
    return all(is_real_apm_role(conv["role_key"]) for conv in conversations)


def _assert_close(left: float, right: float, tolerance: float) -> dict[str, Any]:
    """Return ``{"status": "ok"}`` when within tolerance, otherwise residuals."""
    residual = abs(left - right)
    if residual <= tolerance:
        return {"status": "ok"}
    return {"status": "fail", "left": left, "right": right, "residual": residual}
