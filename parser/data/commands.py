# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Slash-command vocabulary for the two frameworks the case study compares.

This module owns the command-name tables and the predicates over them:
the APM role and known-command sets, the Spec-kit phase and known-command
tables, the Claude Code built-in sets, and the helpers that classify a
command name's framework, role, or phase. The downstream classifiers
consume these tables; this module does not run them.

APM vocabulary lives here in full. The framework defines nine
participant-facing slash commands; three (``apm-1-initiate-planner``,
``apm-2-initiate-manager``, ``apm-3-initiate-worker``) are role
initiators that fix a conversation's role for the whole session, and the
other six continue work within an existing role. APM phase is
role-derived (a Planner conversation is all planning, Manager and Worker
all implementation), so there is no APM command-to-phase table; the
per-conversation role-to-phase derivation lives in ``apm_roles``.

Spec-kit commands reach the JSONL in the hyphenated form Claude Code uses
for the spec-kit integration's skills (``/speckit-specify``,
``/speckit-git-commit``), not spec-kit's own dotted canonical names, and
the tables here match that form. The forward-only Spec-kit phase ratchet
that consumes ``SPECKIT_PHASE_BY_COMMAND`` is owned by ``speckit_phases``;
see there for the ratchet mechanics. The five git-extension commands are
recognised vocabulary but absent from the phase table because they are
repo bookkeeping or out-of-band hooks, not phase events.

A third vocabulary is Claude Code's own built-in slash commands, split
into two disjoint sets (``LOCAL_ONLY_BUILTINS`` and
``MODEL_CALLING_BUILTINS``) whose recognition union is
``CLAUDE_CODE_BUILTINS``. Which set a given command falls in lives in the
inline comments next to each constant below; the split exists because the
schema layer's steer detection treats a queued local-only command as a
non-steer and a queued model-calling command as a real steer (see
``schema``). Built-ins are recognised so they do not pollute the
``unknown_commands_observed`` diagnostic, but they never move the Spec-kit
ratchet, assign an APM role, or count toward the framework protocol
bucket: the study compares the two frameworks, not the platform.
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

APM_KNOWN_COMMANDS: frozenset[str] = frozenset(
    {
        "apm-1-initiate-planner",
        "apm-2-initiate-manager",
        "apm-3-initiate-worker",
        "apm-4-check-tasks",
        "apm-5-check-reports",
        "apm-6-handoff-manager",
        "apm-7-handoff-worker",
        "apm-8-summarize-session",
        "apm-9-recover",
    }
)

APM_HANDOFF_COMMANDS: frozenset[str] = frozenset({"apm-6-handoff-manager", "apm-7-handoff-worker"})

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
SPECKIT_KNOWN_COMMANDS: frozenset[str] = frozenset(
    {
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
    }
)

# Claude Code built-in slash commands. Source:
# https://code.claude.com/docs/en/commands. The built-ins are split
# into two disjoint sets by whether invoking the command issues a model
# request. The names ``vim`` and ``pr-comments`` are kept for transcripts
# captured against Claude Code versions that still shipped them.

# Local-only built-ins act on the CLI, session, UI, or configuration and
# send no payload to the model. A queued one is not a steer.
LOCAL_ONLY_BUILTINS: frozenset[str] = frozenset(
    {
        "add-dir",
        "agents",
        "branch",
        "btw",
        "chrome",
        "clear",
        "color",
        "compact",
        "config",
        "context",
        "copy",
        "desktop",
        "diff",
        "doctor",
        "effort",
        "exit",
        "export",
        "extra-usage",
        "fast",
        "feedback",
        "fewer-permission-prompts",
        "focus",
        "heapdump",
        "help",
        "hooks",
        "ide",
        "keybindings",
        "login",
        "logout",
        "mcp",
        "memory",
        "mobile",
        "model",
        "passes",
        "permissions",
        "plugin",
        "powerup",
        "pr-comments",
        "privacy-settings",
        "radio",
        "release-notes",
        "reload-plugins",
        "remote-control",
        "remote-env",
        "rename",
        "resume",
        "rewind",
        "sandbox",
        "setup-bedrock",
        "setup-vertex",
        "skills",
        "stats",
        "status",
        "statusline",
        "stickers",
        "tasks",
        "teleport",
        "terminal-setup",
        "theme",
        "tui",
        "upgrade",
        "usage",
        "vim",
        "voice",
        "web-setup",
    }
)

# Model-calling built-ins are bundled skills or commands that render a
# body to the model and drive a model request. A queued one is a steer.
MODEL_CALLING_BUILTINS: frozenset[str] = frozenset(
    {
        "autofix-pr",
        "batch",
        "claude-api",
        "debug",
        "init",
        "insights",
        "install-github-app",
        "install-slack-app",
        "loop",
        "plan",
        "recap",
        "review",
        "schedule",
        "security-review",
        "simplify",
        "team-onboarding",
        "ultraplan",
        "ultrareview",
    }
)

# The recognition surface for ``is_known_command`` is the union of
# both sets, unchanged by the split.
CLAUDE_CODE_BUILTINS: frozenset[str] = LOCAL_ONLY_BUILTINS | MODEL_CALLING_BUILTINS

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
        through ``SPECKIT_PHASE_BY_COMMAND``. ``None`` for every
        other block, for skills outside that table, and for malformed
        blocks.
    """
    skill = skill_tool_use_name(block)
    if skill is None or skill not in SPECKIT_PHASE_BY_COMMAND:
        return None
    return skill


def is_apm_role_skill_tool_use(block: dict[str, Any]) -> str | None:
    """Return the APM role command an assistant Skill tool_use names, or ``None``.

    The role-table counterpart to ``is_speckit_skill_tool_use``:
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
        name in APM_KNOWN_COMMANDS or name in SPECKIT_KNOWN_COMMANDS or name in CLAUDE_CODE_BUILTINS
    )


def is_local_only_command(name: str) -> bool:
    """Return ``True`` when the command name is a local-only built-in.

    Local-only built-ins control the CLI or session and issue no model
    request, so a queued one is not a steer. Model-calling built-ins
    and every framework command return ``False``.

    Args:
        name: A command name with the leading slash already stripped.

    Returns:
        ``True`` when ``name`` is in ``LOCAL_ONLY_BUILTINS``, ``False``
        otherwise.
    """
    return name in LOCAL_ONLY_BUILTINS


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
