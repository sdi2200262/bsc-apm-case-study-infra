# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Delegated-dispatch call series for ``parser_data.json``.

The ``calls[]`` series covers only main-conversation calls; it structurally
never carries the usage of a subagent dispatch. Because the five-minute
ephemeral cache is written exclusively by subagents (see
``data.subagent_usage``), any per-category cost breakdown computed from
``calls[]`` alone silently drops all five-minute-cache cost and undercounts
the other categories. This module emits one already-priced row per delegated
dispatch, so a downstream consumer can sum a per-category cost breakdown that
includes delegated usage without re-implementing the pricing rules or reading
the rate table itself.

Each row carries the dispatch's resolved model, its five raw token counts
under the same flat keys ``calls[]`` uses, and a parallel ``*_cost_usd`` field
per category. A category's cost is that category's tokens priced against the
dispatch's model in isolation, so the five fields sum to the dispatch's total
cost and each is independently attributable.
"""

from __future__ import annotations

from typing import Any

from ..rates import CATEGORIES, RateTable, cost_in_usd
from .aggregate.call_records import iter_resolved_dispatches
from .session import Session
from .subagent_usage import SubagentDispatchIndex


def build_dispatch_calls(
    session: Session,
    subagent_index: SubagentDispatchIndex,
    rate_table: RateTable,
) -> list[dict[str, Any]]:
    """Return one priced row per delegated subagent dispatch in ``session``.

    Walks every conversation view and, for each, every Agent dispatch
    resolved by ``call_records.iter_resolved_dispatches`` (which prices the
    subagent's true token bag from its own transcript when the ``agentId`` is
    indexed). Each row carries the resolving model, the five raw token counts
    under the flat keys ``calls[]`` uses, and a parallel ``*_cost_usd`` field
    computed by pricing that category's tokens alone against the model.

    Args:
        session: The assembled parser session.
        subagent_index: Merged ``agentId``-keyed subagent model-and-usage
            index, used to resolve each dispatch's model and true token bag.
        rate_table: The rate table each category's tokens are priced against.

    Returns:
        A JSON-serialisable list of dispatch-call rows, ordered by parser
        conversation view order then dispatch document order.

    Raises:
        ValueError: When a dispatch is bracketed (its model could not be
            resolved to one), which has no defined per-category cost in this
            series. The current cohort contains no bracketed dispatch.
    """
    rows: list[dict[str, Any]] = []
    for view in session.views:
        conversation_id = view.conversation.session_id or ""
        role_key = view.role
        for dispatch in iter_resolved_dispatches(list(view.conversation.records), subagent_index):
            if dispatch.bracket is not None:
                raise ValueError(
                    f"bracketed dispatch in conversation {conversation_id!r} "
                    f"(role {role_key!r}) has no defined per-category cost in the "
                    "dispatch_calls series"
                )
            row: dict[str, Any] = {
                "conversation_id": conversation_id,
                "role_key": role_key,
                "model": dispatch.point_model,
            }
            for category in CATEGORIES:
                row[category] = dispatch.token_bag.get(category, 0)
            for category in CATEGORIES:
                row[f"{category}_cost_usd"] = cost_in_usd(
                    rate_table,
                    dispatch.point_model,
                    {category: dispatch.token_bag.get(category, 0)},
                )
            rows.append(row)
    return rows
