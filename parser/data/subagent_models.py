# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Subagent-model attribution: indexed lookup plus the documented fallback resolver.

The canonical case-study submission ships a sibling
``<sessionId>/subagents/agent-<agentId>.jsonl`` next to every main
session JSONL. Each such file's first non-synthetic assistant record
carries the actual ``message.model`` the subagent ran on; the parent's
``toolUseResult.usage`` rolls up the subagent's token totals but does
not name the model. ``build_subagent_model_index`` reads the sibling
files and returns a ``agentId -> canonical model id`` map, and the cost
layer prices each delegated dispatch against the matched model's rates
rather than the parent's. This is the canonical
path and produces a deterministic single cost.

Some case-study submissions arrived without those sibling files. For
those, ``resolve_unindexed_subagent_model`` is the documented fallback
the parser uses: it inspects the dispatch's ``input.subagent_type`` and
``input.model`` from the main JSONL, looks up the documented default
for known subagent types, and otherwise frames the cost as a
``(haiku, opus)`` bracket so the cost output is honest about its
unverified assumption rather than committing to a single number.

The resolver honours Claude Code's documented precedence
(https://docs.claude.com/en/docs/claude-code/sub-agents): a
per-invocation ``input.model`` overrides every registry lookup, the
subagent's frontmatter default applies otherwise, and the frontmatter
default falls through to the main conversation's model when set to
``inherit``. The parser cannot read environment variables or the
subagent's frontmatter from the participant's host, so this module
registers the public defaults of every subagent type the case study
expects (Claude Code built-ins plus the one APM framework agent) and
brackets the cost for any custom subagent type it does not know.

The date-suffixed model id Claude Code writes on subagent records
(e.g. ``claude-haiku-4-5-20251001``) is normalised through
``rates.canonical_model_id`` so the result matches the family-keyed
entries in ``rates.yaml``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..rates import canonical_model_id
from .schema import SYNTHETIC_MODEL_MARKER

SUBAGENTS_SUBDIR_NAME = "subagents"
SUBAGENT_FILENAME_PREFIX = "agent-"
SUBAGENT_FILENAME_SUFFIX = ".jsonl"

# Subagent type Claude Code uses when an Agent dispatch's input omits
# the ``subagent_type`` field. Documented at
# https://docs.claude.com/en/docs/claude-code/sub-agents.
IMPLICIT_SUBAGENT_TYPE = "general-purpose"

# Default model alias for built-in Claude Code subagent types whose
# documented default is a specific model rather than inheritance.
# Source: https://docs.claude.com/en/docs/claude-code/sub-agents
BUILTIN_DEFAULT_MODELS: dict[str, str] = {
    "Explore": "haiku",
    "claude-code-guide": "haiku",
    "statusline-setup": "sonnet",
}

# Built-in Claude Code subagent types documented to inherit the main
# conversation's model when no per-invocation model is set.
# Source: https://docs.claude.com/en/docs/claude-code/sub-agents
BUILTIN_INHERIT_TYPES: frozenset[str] = frozenset(
    {
        "Plan",
        "general-purpose",
    }
)

# Framework-shipped subagent types whose upstream definition declares
# no ``model:`` frontmatter; per the Claude Code default these inherit
# from the main conversation.
#
# - apm-archive-explorer:
#   https://github.com/sdi2200262/agentic-project-management
KNOWN_INHERIT_FRAMEWORK_AGENTS: frozenset[str] = frozenset(
    {
        "apm-archive-explorer",
    }
)

# Cheapest and most expensive model aliases an unknown custom
# subagent's frontmatter could plausibly pin. Used as the
# ``(lower, upper)`` bracket when the resolver cannot identify the
# subagent type.
UNKNOWN_BRACKET_BOUNDS: tuple[str, str] = ("haiku", "opus")


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
    def empty(cls) -> SubagentModelIndex:
        """Return an index with no entries and zero counts."""
        return cls(by_agent_id={}, files_seen=0, files_without_model=0)


@dataclass(frozen=True)
class ResolvedSubagentModel:
    """Outcome of resolving a delegated dispatch when no subagent file was shipped.

    Attributes:
        canonical_model: Canonicalised model id used to price the
            dispatch's rolled-up usage. Always populated.
        bracket: When the resolution rests on an unverified
            assumption (the dispatch is for a custom subagent type
            the registries do not recognise and ``input.model`` was
            not set), the ``(lower, upper)`` pair of canonical
            model ids whose rates frame the cost as a range.
            ``None`` when the resolution is deterministic.
        rationale: Short human-readable provenance string for the
            resolution. Surfaced in diagnostics so a reader can see
            why a particular model was chosen.
    """

    canonical_model: str
    bracket: tuple[str, str] | None
    rationale: str


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
    for path in sorted(
        subagents_dir.glob(f"{SUBAGENT_FILENAME_PREFIX}*{SUBAGENT_FILENAME_SUFFIX}")
    ):
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


def resolve_unindexed_subagent_model(
    subagent_type: str | None,
    input_model: str | None,
    parent_main_model: str,
) -> ResolvedSubagentModel:
    """Resolve the pricing model for a dispatch whose subagent file was not shipped.

    The canonical case-study submission ships a sibling subagent
    file for every Agent dispatch and ``build_subagent_model_index``
    reads the actual ``message.model`` from it. This function is
    the documented fallback for submissions that arrived without
    those sibling files.

    Resolution honours Claude Code's documented precedence
    (https://docs.claude.com/en/docs/claude-code/sub-agents): a
    per-invocation ``input.model`` overrides every registry, the
    subagent's frontmatter default applies otherwise, and the
    frontmatter default falls through to the main conversation's
    model when set to ``inherit``. The parser cannot read
    environment variables or the subagent's frontmatter from
    outside the participant's host, so the registries declared at
    module level record the public defaults of every subagent type
    the case study expects. A custom subagent type unknown to all
    registries yields a ``(haiku, opus)`` bracket so the cost is
    framed as a range rather than committed to an unverified model.

    Args:
        subagent_type: The ``input.subagent_type`` value on the
            dispatch's tool_use block, or ``None`` when the field
            was omitted (Claude Code treats omitted as
            ``general-purpose``).
        input_model: The ``input.model`` value on the dispatch's
            tool_use block, or ``None`` when the field was not set.
            When set, takes precedence over every registry lookup.
        parent_main_model: The ``message.model`` of the assistant
            record that emitted the dispatch. Used as the resolved
            model for inheriting types and as the point estimate
            beneath the unknown bracket.

    Returns:
        A populated ``ResolvedSubagentModel``. ``bracket`` is set
        only when the resolution rests on an unverified assumption.
    """
    if input_model:
        return ResolvedSubagentModel(
            canonical_model=canonical_model_id(input_model),
            bracket=None,
            rationale=f"per-invocation input.model={input_model!r}",
        )
    effective_type = subagent_type if subagent_type else IMPLICIT_SUBAGENT_TYPE
    if effective_type in BUILTIN_DEFAULT_MODELS:
        return ResolvedSubagentModel(
            canonical_model=canonical_model_id(BUILTIN_DEFAULT_MODELS[effective_type]),
            bracket=None,
            rationale=f"built-in {effective_type!r} default model",
        )
    if effective_type in BUILTIN_INHERIT_TYPES:
        return ResolvedSubagentModel(
            canonical_model=canonical_model_id(parent_main_model),
            bracket=None,
            rationale=f"built-in {effective_type!r} inherits parent",
        )
    if effective_type in KNOWN_INHERIT_FRAMEWORK_AGENTS:
        return ResolvedSubagentModel(
            canonical_model=canonical_model_id(parent_main_model),
            bracket=None,
            rationale=f"framework agent {effective_type!r} inherits parent",
        )
    lower_alias, upper_alias = UNKNOWN_BRACKET_BOUNDS
    return ResolvedSubagentModel(
        canonical_model=canonical_model_id(parent_main_model),
        bracket=(canonical_model_id(lower_alias), canonical_model_id(upper_alias)),
        rationale=(
            f"custom subagent type {effective_type!r}; point=parent inherit; "
            f"bracket={lower_alias}..{upper_alias}"
        ),
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
    middle = filename[len(SUBAGENT_FILENAME_PREFIX) : -len(SUBAGENT_FILENAME_SUFFIX)]
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
