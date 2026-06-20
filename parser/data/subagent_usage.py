# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""True per-``agentId`` subagent token usage, summed from the nested transcripts.

A delegated dispatch's tokens must be priced from the subagent's own
transcript, not the rolled-up ``toolUseResult.usage`` the main transcript
records on the parent user record. That roll-up under-represents the
subagent's real token bag: in particular it carries ``cache_5m = 0``.

The reason is the cache time-to-live split. Per Claude Code's documented
behaviour (https://code.claude.com/docs/en/prompt-caching, section
"Subagents and the cache"), the main conversation writes to the one-hour
cache while each subagent writes to the five-minute cache. So all
five-minute cache-creation tokens live only inside the nested subagent
transcripts, never in the parent roll-up, and reading cost from the
roll-up zeroes them out.

Claude Code ships each subagent's own transcript next to the main session
JSONL at ``<sessionId>/subagents/agent-<agentId>.jsonl`` (the same files
``subagent_models`` reads for the subagent's model). This module reads each
of those files once and sums its assistant API records into a five-category
token bag, deduplicating by ``requestId`` and excluding synthetic and
API-error records exactly as the main-call path does, so the bag is the
subagent's true billed usage.

Attribution policy: each subagent file is summed once and attributed to the
``agentId`` carried in its filename. The cohort's dispatches are flat (a
main agent dispatches a subagent; no subagent dispatches a further
subagent), so no recursion is implemented. A subagent file whose
``agentId`` never matches a main-transcript dispatch contributes an entry
that the pricing call sites simply never look up; it does not inflate any
total, since totals are driven by the dispatches found in the main
transcript, not by the index.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    canonical_model_id,
)
from .schema import SYNTHETIC_MODEL_MARKER
from .subagent_models import (
    SUBAGENT_FILENAME_PREFIX,
    SUBAGENT_FILENAME_SUFFIX,
    SUBAGENTS_SUBDIR_NAME,
    agent_id_from_filename,
)
from .token_usage import token_sums_dict_from_usage


@dataclass(frozen=True)
class SubagentDispatchIndex:
    """Per-``agentId`` model and true token usage read from the subagent transcripts.

    Carries both halves of a delegated dispatch's pricing inputs so they
    travel together through the cost and token layers: the canonical
    model the subagent ran on, and the subagent's own five-category token
    bag (summed from its nested transcript, not the lossy parent
    roll-up). The two maps share the same ``agentId`` keys on
    well-formed Claude Code data.

    Attributes:
        model_by_agent_id: ``agentId`` to canonical (family-keyed,
            date-suffix-stripped, alias-resolved) model id, from the
            first non-synthetic assistant record of each
            ``agent-*.jsonl`` file.
        usage_by_agent_id: ``agentId`` to the five-category token bag
            (keyed by ``rates.CATEGORY_*``) summed over that subagent
            file's deduplicated, non-synthetic, non-errored assistant
            records. The pricing call sites use this bag in place of the
            parent roll-up whenever the dispatch's ``agentId`` is
            present here.
        files_seen: Count of ``agent-*.jsonl`` files inspected next to
            the main session JSONL.
        files_without_model: Count of files whose first non-synthetic
            assistant record carried no usable ``message.model`` (zero
            on well-formed data; surfaced for diagnostics).
    """

    model_by_agent_id: dict[str, str] = field(default_factory=dict)
    usage_by_agent_id: dict[str, dict[str, int]] = field(default_factory=dict)
    files_seen: int = 0
    files_without_model: int = 0

    @classmethod
    def empty(cls) -> SubagentDispatchIndex:
        """Return an index with no entries and zero counts."""
        return cls()


def build_subagent_dispatch_index(main_jsonl_path: Path) -> SubagentDispatchIndex:
    """Build the per-``agentId`` model-and-usage index for one main session JSONL.

    Reads the sibling
    ``<main_jsonl_path.parent>/<main_jsonl_path.stem>/subagents/``
    directory and walks each ``agent-<agentId>.jsonl`` file exactly once,
    extracting both the subagent's model (first non-synthetic assistant
    ``message.model``) and its summed five-category token bag (every
    deduplicated, non-synthetic, non-errored assistant record's usage).
    The single read covers both so the file is not opened twice.

    Args:
        main_jsonl_path: Absolute path to a main session JSONL. Robust to
            a non-existent sibling directory (returns an empty index
            without raising).

    Returns:
        A populated ``SubagentDispatchIndex``. Empty with zero counts
        when the sibling ``subagents/`` directory does not exist.
    """
    session_id = main_jsonl_path.stem
    subagents_dir = main_jsonl_path.parent / session_id / SUBAGENTS_SUBDIR_NAME
    if not subagents_dir.is_dir():
        return SubagentDispatchIndex.empty()
    model_by_agent_id: dict[str, str] = {}
    usage_by_agent_id: dict[str, dict[str, int]] = {}
    files_seen = 0
    files_without_model = 0
    for path in sorted(
        subagents_dir.glob(f"{SUBAGENT_FILENAME_PREFIX}*{SUBAGENT_FILENAME_SUFFIX}")
    ):
        files_seen += 1
        agent_id = agent_id_from_filename(path.name)
        if agent_id is None:
            continue
        model, token_bag = _model_and_usage_from_subagent_file(path)
        usage_by_agent_id[agent_id] = token_bag
        if model is None:
            files_without_model += 1
            continue
        model_by_agent_id[agent_id] = canonical_model_id(model)
    return SubagentDispatchIndex(
        model_by_agent_id=model_by_agent_id,
        usage_by_agent_id=usage_by_agent_id,
        files_seen=files_seen,
        files_without_model=files_without_model,
    )


def _model_and_usage_from_subagent_file(path: Path) -> tuple[str | None, dict[str, int]]:
    """Return the subagent's model and summed token bag from one ``agent-*.jsonl`` file.

    Walks the file once. The model is the ``message.model`` of the first
    non-synthetic assistant record (or ``None`` when none exists). The
    token bag sums ``token_sums_dict_from_usage`` over every assistant
    record, deduplicated by ``requestId`` and excluding synthetic and
    API-error records, so a streaming response's repeated usage is counted
    once and a failed (unbilled) request contributes nothing. This matches
    the main-call population's selection rule, since the subagent's records
    are ordinary main-agent API calls inside its own transcript.

    Lines that do not parse as JSON are skipped silently, matching the
    loader's tolerance and letting this run before the full loader pass.

    Args:
        path: Absolute path to an ``agent-*.jsonl`` file.

    Returns:
        A ``(model, token_bag)`` pair. ``model`` is ``None`` when the file
        holds no usable non-synthetic assistant record; ``token_bag`` is
        keyed by ``rates.CATEGORY_*`` and is all-zero when no record
        contributed usage.
    """
    model: str | None = None
    seen_request_ids: set[str] = set()
    token_bag = _zero_token_bag()
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("type") != "assistant":
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            record_model = message.get("model")
            if not isinstance(record_model, str) or not record_model:
                continue
            if record_model == SYNTHETIC_MODEL_MARKER:
                continue
            if record.get("isApiErrorMessage") is True:
                continue
            if model is None:
                model = record_model
            request_id = record.get("requestId")
            if not isinstance(request_id, str) or request_id in seen_request_ids:
                continue
            seen_request_ids.add(request_id)
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            _accumulate(token_bag, token_sums_dict_from_usage(usage))
    return model, token_bag


def _zero_token_bag() -> dict[str, int]:
    """Return an all-zero five-category token bag keyed by ``rates.CATEGORY_*``."""
    return {
        CATEGORY_INPUT: 0,
        CATEGORY_OUTPUT: 0,
        CATEGORY_CACHE_READ: 0,
        CATEGORY_CACHE_5M: 0,
        CATEGORY_CACHE_1H: 0,
    }


def _accumulate(target: dict[str, int], addend: dict[str, int]) -> None:
    """Add each category of ``addend`` into ``target`` in place."""
    for category, value in addend.items():
        target[category] += value
