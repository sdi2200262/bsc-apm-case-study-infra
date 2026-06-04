#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Slash-command vocabulary for the two frameworks the case study compares.

The Agentic Project Management (APM) framework defines nine
participant-facing slash commands. Three of them (``apm-1-initiate-planner``,
``apm-2-initiate-manager``, ``apm-3-initiate-worker``) are role
initiators: the first such command in a conversation file fixes that
file's role for the whole session. The remaining six commands continue
work within an existing role's conversation.

In APM, the conversation's role determines the phase. A Planner
conversation is entirely planning; Manager and Worker conversations are
entirely implementation. Individual commands within a conversation do
not change the phase, so APM has no command-to-phase table at the
classifier level. The set of recognised APM command names is kept here
to drive the protocol-bucket classifier and to surface unknown
``apm-*`` commands in diagnostics.

The Spec Kit framework's commands are surfaced in Claude Code as slash
commands by the spec-kit Claude integration. Spec-kit's own canonical
names use dotted notation (``speckit.specify``, ``speckit.git.commit``);
the integration installs them as Claude Code skills with dots replaced
by hyphens (``/speckit-specify``, ``/speckit-git-commit``), and the
integration's own hook note instructs the model to use the hyphenated
form when constructing slash commands. The JSONL records this parser
consumes therefore carry the hyphenated form, and the table below
matches that form.

Two installable surfaces ship: the core template set with nine commands
(``analyze``, ``checklist``, ``clarify``, ``constitution``,
``implement``, ``plan``, ``specify``, ``tasks``, ``taskstoissues``) and
the git extension with five (``git-commit``, ``git-feature``,
``git-initialize``, ``git-remote``, ``git-validate``). Of the core
commands, only ``speckit-implement`` sits on the implementation side;
the other eight are planning. The five git-extension commands are
not phase-defining work: they are repo bookkeeping or out-of-band hooks
(per the upstream extension's own description, ``speckit.git.commit``
runs as a hook around core commands rather than as a phase event), so
they are recognised by the known-command set but do not participate in
phase assignment. Phase assignment in Spec-kit is per-prompt and follows
a forward-only ratchet with surgical exceptions: once a prompt advances
the ratchet to ``implementation``, later ``planning`` commands count
themselves as planning but do not move the ratchet back. The
command-to-phase table is consumed by the per-prompt classifier in the
session assembler.

A third vocabulary lives alongside the framework tables: Claude Code's
own built-in slash commands. The platform ships dozens of built-ins
covering session control (``/exit``, ``/clear``, ``/compact``, ``/resume``),
configuration (``/model``, ``/effort``, ``/permissions``, ``/config``,
``/theme``), bundled skills that drive a model call (``/review``,
``/loop``, ``/simplify``, ``/init``, ``/security-review``), and
diagnostic surfaces (``/status``, ``/usage``, ``/stats``, ``/doctor``).
Source: https://code.claude.com/docs/en/commands. A participant typing
any of these produces a slash-command marker that the parser must
recognise as a known invocation; otherwise every such occurrence
pollutes the ``unknown_commands_observed`` diagnostic. Built-ins are
classified separately from the framework tables: they do not move the
Spec-kit phase ratchet, do not assign an APM role, and do not count
toward the framework protocol bucket. The case study compares the two
frameworks, not the platform; built-ins are platform vocabulary the
participant happens to use alongside the framework they are running.
"""

from __future__ import annotations

import re
from typing import Any

FRAMEWORK_APM = "apm"
FRAMEWORK_SPECKIT = "speckit"

ROLE_PLANNER = "planner"
ROLE_MANAGER = "manager"
ROLE_WORKER = "worker"
ROLE_UNASSIGNED = "unassigned"

PHASE_PLANNING = "planning"
PHASE_IMPLEMENTATION = "implementation"
PHASE_OTHER = "other"

SPECKIT_PHASE_ORDER: tuple[str, ...] = (
    PHASE_OTHER,
    PHASE_PLANNING,
    PHASE_IMPLEMENTATION,
)

APM_KNOWN_COMMANDS: frozenset[str] = frozenset({
    "apm-1-initiate-planner",
    "apm-2-initiate-manager",
    "apm-3-initiate-worker",
    "apm-4-check-tasks",
    "apm-5-check-reports",
    "apm-6-handoff-manager",
    "apm-7-handoff-worker",
    "apm-8-summarize-session",
    "apm-9-recover",
})

APM_ROLE_BY_INITIATE_COMMAND: dict[str, str] = {
    "apm-1-initiate-planner": ROLE_PLANNER,
    "apm-2-initiate-manager": ROLE_MANAGER,
    "apm-3-initiate-worker": ROLE_WORKER,
}

APM_PHASE_BY_ROLE: dict[str, str] = {
    ROLE_PLANNER: PHASE_PLANNING,
    ROLE_MANAGER: PHASE_IMPLEMENTATION,
    ROLE_WORKER: PHASE_IMPLEMENTATION,
}

SPECKIT_PHASE_BY_COMMAND: dict[str, str] = {
    "speckit-analyze": PHASE_PLANNING,
    "speckit-checklist": PHASE_PLANNING,
    "speckit-clarify": PHASE_PLANNING,
    "speckit-constitution": PHASE_PLANNING,
    "speckit-plan": PHASE_PLANNING,
    "speckit-specify": PHASE_PLANNING,
    "speckit-tasks": PHASE_PLANNING,
    "speckit-taskstoissues": PHASE_PLANNING,
    "speckit-implement": PHASE_IMPLEMENTATION,
}

# The five git-extension commands are recognised as known Spec-kit
# vocabulary so they do not pollute ``unknown_commands_observed``, but
# they are absent from ``SPECKIT_PHASE_BY_COMMAND`` because they do not
# define a phase event. Listing the known set as a literal frozenset
# keeps the recognition surface stable when the phase table changes.
SPECKIT_KNOWN_COMMANDS: frozenset[str] = frozenset({
    "speckit-analyze",
    "speckit-checklist",
    "speckit-clarify",
    "speckit-constitution",
    "speckit-plan",
    "speckit-specify",
    "speckit-tasks",
    "speckit-taskstoissues",
    "speckit-implement",
    "speckit-git-commit",
    "speckit-git-feature",
    "speckit-git-initialize",
    "speckit-git-remote",
    "speckit-git-validate",
})

# Claude Code built-in slash commands. Source:
# https://code.claude.com/docs/en/commands. The list covers every name
# the platform ships out of the box, including bundled skills that
# render a body to the model and local-only commands that act on the
# CLI without sending a payload. The names ``vim`` and ``pr-comments``
# are kept for transcripts captured against Claude Code versions that
# still shipped them.
CLAUDE_CODE_BUILTINS: frozenset[str] = frozenset({
    "add-dir", "agents", "autofix-pr", "batch", "branch", "btw",
    "chrome", "claude-api", "clear", "color", "compact", "config",
    "context", "copy", "debug", "desktop", "diff", "doctor", "effort",
    "exit", "export", "extra-usage", "fast", "feedback",
    "fewer-permission-prompts", "focus", "heapdump", "help", "hooks",
    "ide", "init", "insights", "install-github-app", "install-slack-app",
    "keybindings", "login", "logout", "loop", "mcp", "memory", "mobile",
    "model", "passes", "permissions", "plan", "plugin", "powerup",
    "pr-comments", "privacy-settings", "radio", "recap", "release-notes",
    "reload-plugins", "remote-control", "remote-env", "rename", "resume",
    "review", "rewind", "sandbox", "schedule", "security-review",
    "setup-bedrock", "setup-vertex", "simplify", "skills", "stats",
    "status", "statusline", "stickers", "tasks", "team-onboarding",
    "teleport", "terminal-setup", "theme", "tui", "ultraplan",
    "ultrareview", "upgrade", "usage", "vim", "voice", "web-setup",
})

# A user prompt's slash-command invocation appears inside the prompt
# text wrapped in a ``<command-name>`` XML-like tag, with a leading
# slash on the command name itself, e.g.
# ``<command-name>/apm-1-initiate-planner</command-name>``. The pattern
# below extracts the command name (without the leading slash) from
# every such marker in a piece of text. Multiple markers per prompt
# are possible when a participant types more than one command in one
# turn; ordering reflects document order in the prompt text.
_COMMAND_NAME_PATTERN = re.compile(
    r"<command-name>\s*/?(?P<name>[^<\s/]+)\s*</command-name>",
    re.IGNORECASE,
)


def extract_command_names(text: str) -> tuple[str, ...]:
    """Return every slash-command name found in a prompt text, in document order.

    Args:
        text: The concatenated text content of a user prompt record.

    Returns:
        A tuple of command names with the leading slash stripped, in
        the order they appear in ``text``. Empty when no command marker
        is present.
    """
    matches = _COMMAND_NAME_PATTERN.findall(text)
    return tuple(matches)


def classify_command(name: str) -> str:
    """Return the framework a command name belongs to.

    Args:
        name: A command name with the leading slash already stripped
            (e.g. ``apm-1-initiate-planner`` or ``speckit-specify``).

    Returns:
        ``FRAMEWORK_APM`` for ``apm-*`` names, ``FRAMEWORK_SPECKIT``
        for ``speckit-*`` names (the hyphenated form Claude Code uses
        for spec-kit slash commands), the empty string otherwise.
    """
    if name.startswith("apm-"):
        return FRAMEWORK_APM
    if name.startswith("speckit-"):
        return FRAMEWORK_SPECKIT
    return ""


def role_from_initiate_command(name: str) -> str:
    """Return the APM role implied by a role-initiating command name.

    Args:
        name: A command name with the leading slash stripped.

    Returns:
        ``ROLE_PLANNER``, ``ROLE_MANAGER``, or ``ROLE_WORKER`` for the
        three role initiators; ``ROLE_UNASSIGNED`` for any other name,
        including continuation commands like ``apm-4-check-tasks`` and
        unknown commands.
    """
    return APM_ROLE_BY_INITIATE_COMMAND.get(name, ROLE_UNASSIGNED)


def speckit_command_phase(name: str) -> str | None:
    """Return the phase a Spec-kit command belongs to, or ``None`` when unknown.

    Args:
        name: A command name with the leading slash stripped.

    Returns:
        ``PHASE_PLANNING`` or ``PHASE_IMPLEMENTATION`` for known
        Spec-kit commands; ``None`` for any name not in the Spec-kit
        table (including ``apm-*`` names and unknown ``speckit-*``
        names from third-party extensions).
    """
    return SPECKIT_PHASE_BY_COMMAND.get(name)


def skill_tool_use_name(block: dict[str, Any]) -> str | None:
    """Return the skill an assistant ``Skill`` tool_use declares, or ``None``.

    The structural half of skill-invocation detection, shared by the
    framework-specific predicates below. A participant never types
    these: the model itself invokes a skill through the Claude Code
    ``Skill`` tool, naming it in ``input.skill``. This recognises that
    block shape and returns the declared name verbatim, independent of
    which framework's vocabulary the name belongs to; the caller
    applies its own table.

    Args:
        block: A single content block from an assistant
            ``message.content`` array.

    Returns:
        The declared skill name when ``block`` is a ``Skill`` tool_use
        carrying a string ``input.skill``; ``None`` for every other
        block and for malformed ones.
    """
    if block.get("type") != "tool_use" or block.get("name") != "Skill":
        return None
    skill_input = block.get("input")
    if not isinstance(skill_input, dict):
        return None
    skill = skill_input.get("skill")
    if not isinstance(skill, str):
        return None
    return skill


def is_speckit_skill_tool_use(block: dict[str, Any]) -> str | None:
    """Return the speckit command an assistant Skill tool_use refers to, or ``None``.

    The Spec-kit phase assigner treats an assistant ``Skill`` tool_use
    whose declared skill names a known Spec-kit phase command as a
    phase event in its own right. This matches the Claude Code Skill
    tool: the model itself invokes the skill, no user prompt is typed.

    Args:
        block: A single content block from an assistant ``message.content``
            array.

    Returns:
        The speckit command name (e.g. ``speckit-implement``) when the
        block is a ``Skill`` tool_use whose declared skill resolves
        through :data:`SPECKIT_PHASE_BY_COMMAND`. ``None`` for every
        other block, for skills outside that table, and for malformed
        blocks.
    """
    skill = skill_tool_use_name(block)
    if skill is None or skill not in SPECKIT_PHASE_BY_COMMAND:
        return None
    return skill


def is_apm_role_skill_tool_use(block: dict[str, Any]) -> str | None:
    """Return the APM role command an assistant Skill tool_use names, or ``None``.

    The role-table counterpart to :func:`is_speckit_skill_tool_use`:
    it recognises the model self-invoking a role skill (``apm-1/2/3``)
    through the ``Skill`` tool, which is how a role initiates when the
    typed command did not expand.

    Args:
        block: A content block from an assistant ``message.content``.

    Returns:
        The role command name, or ``None`` for any other block.
    """
    skill = skill_tool_use_name(block)
    if skill is None or skill not in APM_ROLE_BY_INITIATE_COMMAND:
        return None
    return skill


def is_known_command(name: str) -> bool:
    """Return ``True`` when the command name is recognised by the parser.

    The known set is the union of both framework tables and the Claude
    Code built-in vocabulary. The ``unknown_commands_observed``
    diagnostic surfaces only names outside this union (typos, unknown
    plugins, custom user commands).
    """
    return (
        name in APM_KNOWN_COMMANDS
        or name in SPECKIT_KNOWN_COMMANDS
        or name in CLAUDE_CODE_BUILTINS
    )


def phase_index(phase: str) -> int:
    """Return the ratchet index of a phase within the Spec-kit forward order.

    The index defines the comparison the ratchet uses: a command's
    phase advances the ratchet only when its index is strictly greater
    than the ratchet's current index. ``PHASE_OTHER`` is index 0,
    ``PHASE_PLANNING`` is 1, ``PHASE_IMPLEMENTATION`` is 2.

    Args:
        phase: One of the three phase constants.

    Returns:
        The position of ``phase`` in ``SPECKIT_PHASE_ORDER``.

    Raises:
        ValueError: When ``phase`` is not a recognised phase constant.
    """
    return SPECKIT_PHASE_ORDER.index(phase)
