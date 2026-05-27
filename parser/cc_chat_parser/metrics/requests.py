#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Request-count metrics for process-dimension reporting.

A *request* is one model API call and response: the main agent
issues a prompt, the platform streams back content blocks under one
``requestId``, and Claude Code persists those blocks as multiple
assistant JSONL records all carrying that same id. Counting
distinct non-synthetic, non-API-error ``requestId`` values gives the
number of model actions the agent performed in scope; the same
deduplication recipe drives main-call token aggregation in
``economic._sum_main_from_records`` so the two counts are in
lockstep.

A *delegated request* counts Agent ``tool_use`` blocks. One block
corresponds to one subagent dispatch the main agent initiated;
whether the subagent's own response returned within the scope is a
separate concern tracked under ``agent_dispatches_with_usage`` in
the economic block.

A *request with tool use* is a main request whose persisted assistant
content carried at least one ``tool_use`` block. Because all records
of one streaming response share a ``requestId``, a request qualifies
when any of its assistant records emitted a ``tool_use`` block; the
count is taken over distinct qualifying ``requestId`` values to keep
the result a per-request count rather than a per-block count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..schema import (
    AGENT_TOOL_NAME,
    CONTENT_BLOCK_TOOL_USE,
    RECORD_TYPE_ASSISTANT,
    Record,
    SYNTHETIC_MODEL_MARKER,
    assistant_content_blocks,
    is_synthetic_assistant,
)


@dataclass(frozen=True)
class RequestMetrics:
    """Request-count block for a single scope.

    Attributes:
        request_count: Number of distinct non-synthetic, non-API-error
            main ``requestId`` values in scope.
        delegated_request_count: Number of Agent ``tool_use`` blocks
            dispatched by main agents in scope.
        requests_with_tool_use_count: Number of distinct main
            ``requestId`` values whose assistant records emitted at
            least one ``tool_use`` block.
    """

    request_count: int
    delegated_request_count: int
    requests_with_tool_use_count: int


def compute_requests_for_records(records: Iterable[Record]) -> RequestMetrics:
    """Compute request-count metrics over an arbitrary record subset.

    The three counts are computed in a single pass. The main-request
    dedup mirrors ``economic._sum_main_from_records``: synthetic
    assistant records, API-error records, and records lacking a
    string ``requestId`` are excluded; remaining records contribute
    their ``requestId`` to a set whose cardinality is the count.

    Args:
        records: The records in scope, in any order.

    Returns:
        The three counts wrapped in a ``RequestMetrics``.
    """
    main_request_ids: set[str] = set()
    requests_with_tool_use: set[str] = set()
    delegated_request_count = 0
    for record in records:
        if record.record_type != RECORD_TYPE_ASSISTANT:
            continue
        if is_synthetic_assistant(record):
            continue
        message = record.payload.get("message")
        if not isinstance(message, dict):
            continue
        if message.get("model") == SYNTHETIC_MODEL_MARKER:
            continue
        if record.payload.get("isApiErrorMessage") is True:
            continue
        request_id = record.payload.get("requestId")
        if not isinstance(request_id, str):
            continue
        main_request_ids.add(request_id)
        for block in assistant_content_blocks(record):
            if block.get("type") != CONTENT_BLOCK_TOOL_USE:
                continue
            requests_with_tool_use.add(request_id)
            if block.get("name") == AGENT_TOOL_NAME:
                delegated_request_count += 1
    return RequestMetrics(
        request_count=len(main_request_ids),
        delegated_request_count=delegated_request_count,
        requests_with_tool_use_count=len(requests_with_tool_use),
    )
