# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Reliability dimension: tool-call success rate.

Anthropic's API marks a failed tool invocation by setting
``is_error: true`` on the ``tool_result`` content block returned to the
model; successful invocations either omit the field or set it to
``false``. The convention is uniform across every tool the Claude Code
agent can invoke, making ``is_error != True`` a single reliable success
signal across the entire tool surface.

The success rate is the share of tool invocations whose result indicated
success, over every tool result the agent received in scope. The two
counts are data and are produced by ``data/aggregate/counts``; this module
divides them. The rate is reported as a supplementary descriptor: its
value is dominated by the underlying model's tool-use capability rather
than by framework choice, so it is reported descriptively rather than
hypothesis-tested.
"""

from __future__ import annotations

from ..data.aggregate.counts import ToolCounts


def tool_success_rate(tool_counts: ToolCounts) -> float:
    """Return the tool-call success rate for a scope.

    Args:
        tool_counts: The scope's ``tool_result`` and error counts.

    Returns:
        The share of tool results in ``[0.0, 1.0]`` that did not carry
        ``is_error: true``. Reported as ``0.0`` when the scope contains
        zero tool results, to keep the rate defined on every scope.
    """
    total = tool_counts.tool_result_count
    errors = tool_counts.tool_error_count
    return (total - errors) / total if total > 0 else 0.0
