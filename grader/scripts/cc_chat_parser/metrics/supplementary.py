#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Supplementary metrics: subagent activity and reasoning-token share.

Subagent metrics describe how often the calling agent delegates
work to a dispatched subagent and how much tool work those
subagents perform on their own. They sit in the supplementary
group because the unit of comparison for the case study is
framework against framework rather than agent against subagent;
the subagent metrics characterise behaviour but are not
hypothesis-tested.

Reasoning-token share approximates the fraction of the model's
output tokens spent on explicit ``thinking`` deliberation. The
Anthropic API's ``message.usage.output_tokens`` is a single
aggregate across every content block of a streaming response and
does not split by block type, so the share is computed as the
ratio of characters in ``thinking`` blocks to the characters
across every assistant output block (``thinking`` + ``text`` +
serialised ``tool_use`` input). The character-to-token ratio
cancels out of the quotient, which is why this approximation
holds without needing a separate per-block token counter. The
caveat is documented here and surfaced in the report's
diagnostics so a reader knows the figure is an approximation
rather than a direct measurement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from ..schema import (
    CONTENT_BLOCK_TEXT,
    CONTENT_BLOCK_THINKING,
    CONTENT_BLOCK_TOOL_USE,
    Record,
    assistant_content_blocks,
    is_synthetic_assistant,
)
from ..turns import Turn


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
        reasoning_token_share: Approximate share of output tokens
            spent on ``thinking`` deliberation, computed as the
            ratio of ``thinking`` block characters to the total
            characters across every assistant output block in
            scope. Returns ``0.0`` when the scope has no assistant
            output characters.
    """

    subagent_count: int
    subagent_tool_count: int
    reasoning_token_share: float


def compute_supplementary_metrics(turns: Iterable[Turn]) -> SupplementaryMetrics:
    """Compute supplementary metrics over a set of turns."""
    subagent_count = 0
    subagent_tool_count = 0
    thinking_chars = 0
    total_output_chars = 0
    for turn in turns:
        for record in turn.records:
            if is_synthetic_assistant(record):
                continue
            if record.record_type == "assistant":
                for block in assistant_content_blocks(record):
                    block_type = block.get("type")
                    if block_type == CONTENT_BLOCK_TOOL_USE and block.get("name") == "Agent":
                        subagent_count += 1
                    output_chars = _output_chars(block)
                    total_output_chars += output_chars
                    if block_type == CONTENT_BLOCK_THINKING:
                        thinking_chars += output_chars
            elif record.record_type == "user":
                tool_use_result = record.payload.get("toolUseResult")
                if isinstance(tool_use_result, dict):
                    total = tool_use_result.get("totalToolUseCount")
                    if isinstance(total, int):
                        subagent_tool_count += total
    share = (thinking_chars / total_output_chars) if total_output_chars > 0 else 0.0
    return SupplementaryMetrics(
        subagent_count=subagent_count,
        subagent_tool_count=subagent_tool_count,
        reasoning_token_share=share,
    )


def _output_chars(block: dict[str, Any]) -> int:
    """Return the character count contributed by an assistant output block.

    ``text`` and ``thinking`` blocks contribute the length of their
    ``text`` field; ``tool_use`` blocks contribute the JSON-serialised
    length of their ``input`` field, which is what the model emitted
    to invoke the tool. Other block types contribute zero.
    """
    block_type = block.get("type")
    if block_type in (CONTENT_BLOCK_TEXT, CONTENT_BLOCK_THINKING):
        text = block.get("text") if block_type == CONTENT_BLOCK_TEXT else block.get("thinking")
        if isinstance(text, str):
            return len(text)
        text_field = block.get("text")
        if isinstance(text_field, str):
            return len(text_field)
        return 0
    if block_type == CONTENT_BLOCK_TOOL_USE:
        tool_input = block.get("input")
        if tool_input is None:
            return 0
        try:
            return len(json.dumps(tool_input, ensure_ascii=False))
        except (TypeError, ValueError):
            return 0
    return 0
