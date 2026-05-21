#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Supplementary metrics: subagent activity and model-driven Skill use.

Subagent metrics describe how often the calling agent delegates
work to a dispatched subagent and how much tool work those
subagents perform on their own. They sit in the supplementary
group because the unit of comparison for the case study is
framework against framework rather than agent against subagent;
the subagent metrics characterise behaviour but are not
hypothesis-tested.

The model-invoked Skill count records how many times the main
agent itself reached for a Skill via the Skill tool. The platform
renders the invoked Skill body and injects it into the
conversation as a user-side record carrying ``sourceToolUseID``;
those renderings are not user-authored prompts (the user did not
type the slash) and are filtered out of turn-starting detection,
so without a dedicated count their occurrence would otherwise be
invisible at the metric layer. The count is supplementary because
self-invocation rates are an agent-behaviour signal rather than a
framework-comparison primary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..schema import (
    AGENT_TOOL_NAME,
    CONTENT_BLOCK_TOOL_USE,
    RECORD_TYPE_ASSISTANT,
    RECORD_TYPE_USER,
    Record,
    assistant_content_blocks,
    is_synthetic_assistant,
)
from ..user_prompts import is_model_invoked_skill_rendering


@dataclass(frozen=True)
class SupplementaryMetrics:
    """Supplementary metric block for a single scope.

    Attributes:
        subagent_count: Number of Agent tool_use blocks dispatched
            by the main agents in scope.
        subagent_tool_count: Sum of ``toolUseResult.totalToolUseCount``
            across user records that returned a populated subagent
            result. Dispatches whose result lacked the field
            contribute zero.
        model_invoked_skill_count: Number of user-side records in
            scope that are platform-rendered Skill bodies the model
            itself caused to be injected via the Skill tool.
    """

    subagent_count: int
    subagent_tool_count: int
    model_invoked_skill_count: int


def compute_supplementary_metrics(records: Iterable[Record]) -> SupplementaryMetrics:
    """Compute supplementary metrics over an arbitrary record subset.

    Iterating the scope's full record stream (rather than a per-turn
    slice) keeps the counts stable across session, phase, and role
    aggregations; in well-formed Claude Code data the per-turn and
    full-record streams coincide for the metrics this module
    computes.

    Args:
        records: The records in scope, in any order.

    Returns:
        The subagent dispatch count, the summed subagent tool-use
        count, and the model-invoked Skill count for the scope.
    """
    subagent_count = 0
    subagent_tool_count = 0
    model_invoked_skill_count = 0
    for record in records:
        if is_synthetic_assistant(record):
            continue
        if record.record_type == RECORD_TYPE_ASSISTANT:
            for block in assistant_content_blocks(record):
                if block.get("type") == CONTENT_BLOCK_TOOL_USE and block.get("name") == AGENT_TOOL_NAME:
                    subagent_count += 1
        elif record.record_type == RECORD_TYPE_USER:
            tool_use_result = record.payload.get("toolUseResult")
            if isinstance(tool_use_result, dict):
                total = tool_use_result.get("totalToolUseCount")
                if isinstance(total, int):
                    subagent_tool_count += total
            if is_model_invoked_skill_rendering(record):
                model_invoked_skill_count += 1
    return SupplementaryMetrics(
        subagent_count=subagent_count,
        subagent_tool_count=subagent_tool_count,
        model_invoked_skill_count=model_invoked_skill_count,
    )
