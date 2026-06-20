# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Subagent-model attribution: the documented fallback resolver and its shared helpers.

This module owns the fallback that resolves which model a delegated
subagent dispatch ran on when no sibling subagent transcript was shipped,
plus the filename constants and helpers the canonical indexed path
(``subagent_usage.build_subagent_dispatch_index``) shares. The indexed
path reads the subagent's actual ``message.model`` (and its true token
usage) straight from the sibling
``<sessionId>/subagents/agent-<agentId>.jsonl`` file; this module's
resolver covers only submissions that arrived without those files.

The fallback, ``resolve_unindexed_subagent_model``, applies Claude Code's
documented model-resolution precedence against the registries declared at
module level. The precedence rules and the bracketing of unknown subagent
types are documented on that function; the registries it reads carry their
sourcing in inline comments.

Date-suffixed model ids Claude Code writes on subagent records
(e.g. ``claude-haiku-4-5-20251001``) are normalised through
``rates.canonical_model_id`` so results match the family-keyed entries in
``rates.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..rates import canonical_model_id

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


def agent_id_from_filename(filename: str) -> str | None:
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
