# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""The field contract: the single description of every emitted measurement leaf.

The three output artifacts carry bare ``name: value`` leaves. The
description of each leaf, its kind (whether the data layer read it or the
metrics layer derived it), its analysis label (whether it drives a
hypothesis test, decomposes one, or is descriptive only), and a one-line
formula for the metrics, lives here and nowhere else. ``--schema`` writes
this map once to ``parser_schema.json``; the per-session artifacts do not
repeat it.

This module is a root leaf: it imports nothing from the ``data``,
``metrics``, or ``report`` layers, so the layers and the report assembler
may read it without creating a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Kind = Literal["data", "metric"]
Label = Literal["primary", "secondary", "supplementary"]


@dataclass(frozen=True)
class FieldSpec:
    """Specification of one emitted measurement leaf.

    Attributes:
        kind: ``"data"`` when the data layer read, aggregated, or counted
            the value; ``"metric"`` when the metrics layer derived it from
            a study-defined formula.
        label: ``"primary"`` for a hypothesis-tested endpoint,
            ``"secondary"`` for a decomposition of a Primary, and
            ``"supplementary"`` for a descriptive value that is not tested.
        formula: One-line description of the metric's computation, set for
            metrics and ``None`` for data leaves.
    """

    kind: Kind
    label: Label
    formula: str | None = None


_TOKEN_POPULATIONS: tuple[str, ...] = ("main", "delegated", "total")
_TOKEN_CATEGORIES: tuple[str, ...] = ("input", "output", "cache_read", "cache_5m", "cache_1h")

_TOKEN_SUM_SPECS: dict[str, FieldSpec] = {
    f"{population}_{category}_tokens": FieldSpec(
        kind="data",
        label="secondary" if population == "total" else "supplementary",
    )
    for population in _TOKEN_POPULATIONS
    for category in _TOKEN_CATEGORIES
}

CONTRACT: dict[str, FieldSpec] = {
    **_TOKEN_SUM_SPECS,
    "total_prompt_tokens": FieldSpec(kind="data", label="secondary"),
    "model_token_distribution": FieldSpec(kind="data", label="supplementary"),
    "cost_usd": FieldSpec(
        kind="metric",
        label="primary",
        formula="sum over each call's token bag priced at its resolved model's rate",
    ),
    "cost_usd_lower_bound": FieldSpec(
        kind="metric",
        label="primary",
        formula="cost_usd with each bracketed dispatch priced at its lower-bound model",
    ),
    "cost_usd_upper_bound": FieldSpec(
        kind="metric",
        label="primary",
        formula="cost_usd with each bracketed dispatch priced at its upper-bound model",
    ),
    "request_count": FieldSpec(kind="data", label="supplementary"),
    "delegated_request_count": FieldSpec(kind="data", label="supplementary"),
    "requests_with_tool_use_count": FieldSpec(kind="data", label="supplementary"),
    "duration": FieldSpec(
        kind="metric",
        label="primary",
        formula="turn_time + inter_turn_time (session: latest minus earliest real record)",
    ),
    "turn_time": FieldSpec(
        kind="metric",
        label="secondary",
        formula=(
            "union of turn intervals (phase scope: of phase segments; "
            "role scope: sum of per-turn durations)"
        ),
    ),
    "turn_time_solo": FieldSpec(
        kind="metric", label="secondary", formula="union time at active-turn count == 1"
    ),
    "turn_time_concurrent": FieldSpec(
        kind="metric", label="secondary", formula="union time at active-turn count >= 2"
    ),
    "inter_turn_time": FieldSpec(
        kind="metric",
        label="secondary",
        formula="duration - turn_time (phase scope: partitioned share of session idle)",
    ),
    "mean_turn_duration": FieldSpec(
        kind="metric",
        label="supplementary",
        formula="mean of per-turn durations (phase scope: of segment durations)",
    ),
    "turn_duration_p50": FieldSpec(
        kind="metric",
        label="supplementary",
        formula="median of per-turn durations (phase scope: of segment durations)",
    ),
    "turn_duration_p95": FieldSpec(
        kind="metric",
        label="supplementary",
        formula=(
            "linearly interpolated 95th percentile of per-turn durations "
            "(phase scope: of segment durations)"
        ),
    ),
    "turn_duration_stdev": FieldSpec(
        kind="metric",
        label="supplementary",
        formula=(
            "population standard deviation of per-turn durations "
            "(phase scope: of segment durations)"
        ),
    ),
    "turn_prompt_count": FieldSpec(kind="data", label="primary"),
    "steer_delivered_count": FieldSpec(kind="data", label="primary"),
    "steer_attempted_count": FieldSpec(kind="data", label="primary"),
    "steer_abandoned_count": FieldSpec(kind="data", label="secondary"),
    "turn_prompts_bucket_shares": FieldSpec(
        kind="metric",
        label="primary",
        formula="count per bucket over the turn-prompt population",
    ),
    "steer_delivered_bucket_shares": FieldSpec(
        kind="metric",
        label="primary",
        formula="count per bucket over the delivered-steer population",
    ),
    "all_inputs_bucket_shares": FieldSpec(
        kind="metric",
        label="primary",
        formula="count per bucket over the union of turn prompts and delivered steers",
    ),
    "turn_prompts_magnitude_by_bucket": FieldSpec(
        kind="metric",
        label="primary",
        formula="mean character length per bucket over the turn-prompt population",
    ),
    "steer_delivered_magnitude_by_bucket": FieldSpec(
        kind="metric",
        label="primary",
        formula="mean character length per bucket over the delivered-steer population",
    ),
    "tool_success_rate": FieldSpec(
        kind="metric",
        label="supplementary",
        formula="(tool_result_count - tool_error_count) / tool_result_count, "
        "or null when there are no tool results",
    ),
    "subagent_count": FieldSpec(kind="data", label="supplementary"),
    "subagent_tool_count": FieldSpec(kind="data", label="supplementary"),
    "subagent_request_count": FieldSpec(kind="data", label="supplementary"),
    "model_invoked_skill_count": FieldSpec(kind="data", label="supplementary"),
    "tool_result_count": FieldSpec(kind="data", label="supplementary"),
    "tool_error_count": FieldSpec(kind="data", label="supplementary"),
}


def schema_document() -> dict[str, Any]:
    """Serialize the contract to the schema-artifact mapping.

    Each field maps to its ``kind`` and ``label``; a metric also carries
    its ``formula``. A ``formula`` of ``None`` is omitted so the schema
    stays minimal.

    Returns:
        The ``parser_schema.json`` body: a dict from field name to its
        specification dict.
    """
    document: dict[str, Any] = {}
    for name, spec in CONTRACT.items():
        entry: dict[str, Any] = {"kind": spec.kind, "label": spec.label}
        if spec.formula is not None:
            entry["formula"] = spec.formula
        document[name] = entry
    return document
