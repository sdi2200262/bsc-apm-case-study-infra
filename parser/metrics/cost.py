# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""API-equivalent cost: the rate table folded over the resolved call series.

Cost is the metric layer's only economic computation. The data layer
resolves which model billed each main call and each Agent dispatch and
carries the token bag (``data/aggregate/call_records``); this module
prices each entry against that model's row in the rate table and sums. The
metric layer reads no transcript records of its own (see ``metrics``).

Two populations are priced: each main call at its own canonicalised model,
each delegated dispatch at the subagent's resolved model, which may be a
``(lower, upper)`` rate bracket for an unknown custom subagent. A bracketed
dispatch turns the scope's cost from a point into a bound pair; the exact
output shape is documented on ``CostMetrics``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.aggregate.call_records import (
    iter_resolved_dispatches,
    iter_resolved_main_calls,
)
from ..data.schema import Record
from ..data.subagent_usage import SubagentDispatchIndex
from ..rates import RateTable, cost_in_usd


@dataclass(frozen=True)
class CostMetrics:
    """Cost metric block for a single scope.

    Exactly one of the two shapes is populated: a single ``cost_usd``
    when no dispatch in the scope was bracketed, or the
    ``cost_usd_lower_bound`` / ``cost_usd_upper_bound`` pair when at least
    one was.

    Attributes:
        cost_usd: API-equivalent USD cost; ``None`` when bracketed.
        cost_usd_lower_bound: Lower bound when bracketed; else ``None``.
        cost_usd_upper_bound: Upper bound when bracketed; else ``None``.
    """

    cost_usd: float | None
    cost_usd_lower_bound: float | None
    cost_usd_upper_bound: float | None


def compute_cost_for_records(
    records: list[Record],
    rate_table: RateTable,
    subagent_index: SubagentDispatchIndex,
) -> CostMetrics:
    """Fold the rate table over a record subset's resolved call series.

    Each main call is priced at its own canonicalised model and each
    delegated dispatch at its resolved model. A certain cost (every main
    call, and every dispatch priced deterministically) is added to both
    bounds; a bracketed dispatch adds its lower-model price to the lower
    bound and its upper-model price to the upper bound. The scope reports a
    single ``cost_usd`` when no dispatch was bracketed, otherwise the bound
    pair with ``cost_usd`` set to ``None``.

    Args:
        records: The records to price.
        rate_table: The rate table to compute cost against.
        subagent_index: Merged ``agentId``-keyed subagent
            model-and-usage index, used by the data layer to resolve each
            dispatch's model and to price its true token bag in place of
            the parent roll-up.

    Returns:
        A populated ``CostMetrics`` with either a single ``cost_usd`` or
        the bounded pair.

    Raises:
        RateTableError: When a resolved model is not present in
            ``rate_table.models``.
    """
    main_cost = 0.0
    for call in iter_resolved_main_calls(records):
        main_cost += cost_in_usd(rate_table, call.canonical_model, call.token_bag)
    cost_point = 0.0
    cost_lower = 0.0
    cost_upper = 0.0
    any_bracketed = False
    for dispatch in iter_resolved_dispatches(records, subagent_index):
        point_cost = cost_in_usd(rate_table, dispatch.point_model, dispatch.token_bag)
        cost_point += point_cost
        if dispatch.bracket is None:
            cost_lower += point_cost
            cost_upper += point_cost
        else:
            any_bracketed = True
            lower_model, upper_model = dispatch.bracket
            cost_lower += cost_in_usd(rate_table, lower_model, dispatch.token_bag)
            cost_upper += cost_in_usd(rate_table, upper_model, dispatch.token_bag)
    if any_bracketed:
        return CostMetrics(
            cost_usd=None,
            cost_usd_lower_bound=main_cost + cost_lower,
            cost_usd_upper_bound=main_cost + cost_upper,
        )
    return CostMetrics(
        cost_usd=main_cost + cost_point,
        cost_usd_lower_bound=None,
        cost_usd_upper_bound=None,
    )
