#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Reliability dimension: tool-call success rate.

Anthropic's API marks a failed tool invocation by setting
``is_error: true`` on the ``tool_result`` content block returned to
the model. Successful invocations either omit the field or set it to
``false``. The convention is uniform across every tool the Claude
Code agent can invoke (Bash, Read, Edit, Write, Grep, Glob, Agent,
and any MCP tool the participant has configured), making
``is_error != True`` a single reliable success signal across the
entire tool surface.

The success rate is the share of tool invocations whose result
indicated success, where the denominator is every tool result the
agent received in scope. Synthetic assistant records are not
involved (they emit no tool calls); subagent-internal tool calls
are not in this denominator (they live in the subagent's own
transcript, which the parser does not consume) and therefore the
metric reflects reliability at the surface visible to the calling
agent. The thesis methodology declares this measurement boundary:
internal recoveries within a delegated subagent dispatch are
attributed to whatever ``is_error`` flag the parent ``Agent`` tool
result carries. The rate is reported as a supplementary descriptor:
its value is dominated by the underlying model's tool-use
capability rather than by framework choice, so it is not entered
into the paired hypothesis testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..schema import (
    CONTENT_BLOCK_TOOL_RESULT,
    Record,
    user_content_blocks,
)


@dataclass(frozen=True)
class ReliabilityMetrics:
    """Reliability metric block for a single scope.

    Attributes:
        tool_success_rate: Share of tool invocations in scope whose
            ``tool_result`` did not carry ``is_error: true``. In
            ``[0.0, 1.0]``. Reported as ``0.0`` when the scope
            contains zero tool results to keep the metric defined
            on every scope.
        tool_result_count: Total number of ``tool_result`` blocks
            observed in the scope (the denominator). Surfaced for
            diagnostics only; the only measurement metric exposed
            from this block is ``tool_success_rate``.
        tool_error_count: Subset of ``tool_result_count`` carrying
            ``is_error: true``. Diagnostic only.
    """

    tool_success_rate: float
    tool_result_count: int
    tool_error_count: int


def compute_reliability_metrics(records: Iterable[Record]) -> ReliabilityMetrics:
    """Compute reliability metrics over an arbitrary record subset.

    Args:
        records: The records to scan. Only user records contribute;
            other record types are inert. Iterating the scope's
            full record stream (rather than a per-turn slice) keeps
            the denominator stable across session, phase, and role
            aggregations.

    Returns:
        A populated ``ReliabilityMetrics``.
    """
    total = 0
    errors = 0
    for record in records:
        for block in _tool_result_blocks(record):
            total += 1
            if block.get("is_error") is True:
                errors += 1
    rate = (total - errors) / total if total > 0 else 0.0
    return ReliabilityMetrics(
        tool_success_rate=rate,
        tool_result_count=total,
        tool_error_count=errors,
    )


def _tool_result_blocks(record: Record) -> list[dict]:
    """Return every ``tool_result`` content block on a user record."""
    return [
        block
        for block in user_content_blocks(record)
        if block.get("type") == CONTENT_BLOCK_TOOL_RESULT
    ]
