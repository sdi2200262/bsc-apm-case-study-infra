#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Per-conversation subagent-model index for accurate delegated cost.

When the main agent dispatches a Task tool call (the Claude Code
``Agent`` block), the subagent runs in its own conversation and Claude
Code writes the subagent's records to
``<projects>/<encoded>/<sessionId>/subagents/agent-<agentId>.jsonl``
alongside the main session JSONL. The subagent's records carry the
actual model id (``message.model``) on every assistant record; the
parent's ``toolUseResult.usage`` rolls up the subagent's token totals
but does not name the model. Pricing the subagent's tokens against the
parent's modal model would conflate Haiku ``Explore`` dispatches and
Sonnet helper agents with Opus main work and over-bill them.

This module discovers and parses those sibling subagent files for one
main session JSONL and exposes the result as a
``agentId -> canonical model id`` map. Callers in ``metrics/economic``
look up each delegated dispatch's ``agentId`` (read from the parent's
``toolUseResult.agentId``) and price its rolled-up usage against the
matched model's rates instead of the parent's. When a subagent file is
absent (the case-study submission contract may exclude them on
historical zips, or no subagents were dispatched), callers fall back
to the per-invocation alias on the parent's ``tool_use`` block, then to
the built-in ``Explore`` rule, then to inheriting the parent's model.

The index is built per main JSONL and keyed by ``agentId``. The
date-suffixed model id Claude Code writes on subagent records (e.g.
``claude-haiku-4-5-20251001``) is normalised through
``rates.canonical_model_id`` so the result matches the family-keyed
entries in ``rates.yaml``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .rates import canonical_model_id
from .schema import SYNTHETIC_MODEL_MARKER

SUBAGENTS_SUBDIR_NAME = "subagents"
SUBAGENT_FILENAME_PREFIX = "agent-"
SUBAGENT_FILENAME_SUFFIX = ".jsonl"


@dataclass(frozen=True)
class SubagentModelIndex:
    """Map from subagent ``agentId`` to the canonical model the subagent ran on.

    Attributes:
        by_agent_id: ``agentId`` to canonical (family-keyed,
            date-suffix-stripped, alias-resolved) model id, sourced
            from the first non-synthetic assistant record of each
            sibling ``agent-*.jsonl`` file.
        files_seen: Count of ``agent-*.jsonl`` files inspected next
            to the main session JSONL.
        files_without_model: Count of files whose first non-synthetic
            assistant record did not carry a usable ``message.model``
            (zero on well-formed Claude Code data; surfaced for
            diagnostics).
    """

    by_agent_id: dict[str, str]
    files_seen: int
    files_without_model: int

    @classmethod
    def empty(cls) -> "SubagentModelIndex":
        """Return an index with no entries and zero counts."""
        return cls(by_agent_id={}, files_seen=0, files_without_model=0)


def build_subagent_model_index(main_jsonl_path: Path) -> SubagentModelIndex:
    """Build the subagent-model index for one main session JSONL.

    Looks for the sibling directory
    ``<main_jsonl_path.parent>/<main_jsonl_path.stem>/subagents/``
    and reads each ``agent-<agentId>.jsonl`` file inside. The first
    non-synthetic assistant record's ``message.model`` is taken as
    the subagent's model and normalised through
    ``rates.canonical_model_id``. Files that contain no qualifying
    record are tallied as ``files_without_model`` and contribute no
    entry.

    Args:
        main_jsonl_path: Absolute path to a main session JSONL.
            The function is robust to a non-existent sibling
            directory (returns an empty index without raising).

    Returns:
        A populated ``SubagentModelIndex``. When the sibling
        ``subagents/`` directory does not exist, the index is empty
        and both counts are zero.
    """
    session_id = main_jsonl_path.stem
    subagents_dir = main_jsonl_path.parent / session_id / SUBAGENTS_SUBDIR_NAME
    if not subagents_dir.is_dir():
        return SubagentModelIndex.empty()
    by_agent_id: dict[str, str] = {}
    files_seen = 0
    files_without_model = 0
    for path in sorted(subagents_dir.glob(f"{SUBAGENT_FILENAME_PREFIX}*{SUBAGENT_FILENAME_SUFFIX}")):
        files_seen += 1
        agent_id = _agent_id_from_filename(path.name)
        if agent_id is None:
            continue
        model = _first_non_synthetic_assistant_model(path)
        if model is None:
            files_without_model += 1
            continue
        by_agent_id[agent_id] = canonical_model_id(model)
    return SubagentModelIndex(
        by_agent_id=by_agent_id,
        files_seen=files_seen,
        files_without_model=files_without_model,
    )


def _agent_id_from_filename(filename: str) -> str | None:
    """Return the ``agentId`` carried in a subagent filename, or ``None`` if malformed.

    Subagent files are written as ``agent-<agentId>.jsonl``; the
    helper strips both the prefix and the suffix and returns the
    middle. Returns ``None`` when the filename does not match the
    documented shape.
    """
    if not filename.startswith(SUBAGENT_FILENAME_PREFIX):
        return None
    if not filename.endswith(SUBAGENT_FILENAME_SUFFIX):
        return None
    middle = filename[len(SUBAGENT_FILENAME_PREFIX): -len(SUBAGENT_FILENAME_SUFFIX)]
    return middle or None


def _first_non_synthetic_assistant_model(path: Path) -> str | None:
    """Return the ``message.model`` of the first non-synthetic assistant record.

    Walks the JSONL line by line until a record matching the
    selection rule is found. Lines that fail to parse as JSON are
    skipped silently; this matches the loader's tolerance of
    pre-record garbage and lets the function operate before the
    full loader pass runs.

    Args:
        path: Absolute path to an ``agent-*.jsonl`` file.

    Returns:
        The string value of ``message.model`` on the first
        non-synthetic assistant record encountered, or ``None`` if
        no such record exists in the file.
    """
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
            model = message.get("model")
            if not isinstance(model, str) or not model:
                continue
            if model == SYNTHETIC_MODEL_MARKER:
                continue
            return model
    return None
