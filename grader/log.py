# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Terminal logging: the grader's single human-facing output channel.

Every human-facing line the grader emits (progress, warnings, errors,
the score summary, the review and warning notices) goes through this
module; JSON is the only file artefact. The module owns the level
vocabulary, the bracket-token rendering, the stdout/stderr split, the
debug gate, and the structural separators, so output is uniform across
every layer that imports it.

Each level emits ``[LEVEL] message`` with the bracket token left-padded
to a common width and ANSI colour applied to the token only, and only
when the destination stream is a TTY. ``error`` writes to stderr; every
other level writes to stdout. ``debug`` emits only when the environment
variable named by ``DEBUG_ENV_VAR`` is set (the ``--debug`` flag turns
it on via ``enable_debug``). ``line`` and ``blank`` are structural:
``line`` is the only separator rule, replacing raw banner constants,
and ``blank`` is an empty line. There are no emojis.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from typing import TextIO

# Environment variable that gates debug output. The --debug CLI flag
# sets it via enable_debug() so the flag and the module share one gate.
DEBUG_ENV_VAR = "GRADER_DEBUG"

# Width of the structural separator rule emitted by line().
RULE_WIDTH = 72

# ANSI colour applied to the bracket token only (never the message),
# and only on a TTY. Keyed by the rendered token text.
_TOKEN_COLOURS: dict[str, str] = {
    "INFO": "\033[34m",  # blue
    "WARN": "\033[33m",  # yellow
    "ERROR": "\033[31m",  # red
    "SUCCESS": "\033[32m",  # green
    "DEBUG": "\033[90m",  # grey
    "DIM": "\033[90m",  # grey
    "REVIEW": "\033[36m",  # cyan
    "WARNING": "\033[33m",  # yellow
}
_RESET = "\033[0m"

# Common width every bracket token is padded to, so messages align in a
# column regardless of level. Derived from the widest token in use.
_TOKEN_WIDTH = max(len(f"[{name}]") for name in _TOKEN_COLOURS)


def _render_token(name: str, stream: TextIO, pad: bool = True) -> str:
    """Return the bracket token for ``name``, coloured on a TTY.

    Args:
        name: Level or tag name, e.g. ``"INFO"`` or ``"WARNING"``.
        stream: Destination stream; colour is applied only when it is a
            TTY.
        pad: When true, left-pad the token to the common column width so
            inline messages align. A token that sits alone on its line
            (a notice tag) passes false to avoid a trailing space.

    Returns:
        The token ``[name]``, padded to the common width when ``pad`` is
        set, wrapped in the level's ANSI colour when the stream is a TTY.
    """
    plain = f"[{name}]"
    trailing = " " * (_TOKEN_WIDTH - len(plain)) if pad else ""
    if stream.isatty() and name in _TOKEN_COLOURS:
        return f"{_TOKEN_COLOURS[name]}{plain}{_RESET}{trailing}"
    return f"{plain}{trailing}"


def _emit(name: str, message: str, stream: TextIO) -> None:
    """Write ``[name] message`` to ``stream`` with the padded token."""
    print(f"{_render_token(name, stream)} {message}", file=stream)


def info(message: str) -> None:
    """Emit an informational line to stdout."""
    _emit("INFO", message, sys.stdout)


def warn(message: str) -> None:
    """Emit a warning line to stdout."""
    _emit("WARN", message, sys.stdout)


def error(message: str) -> None:
    """Emit an error line to stderr."""
    _emit("ERROR", message, sys.stderr)


def success(message: str) -> None:
    """Emit a success line to stdout."""
    _emit("SUCCESS", message, sys.stdout)


def debug(message: str) -> None:
    """Emit a debug line to stdout, only when the debug gate is set."""
    if os.environ.get(DEBUG_ENV_VAR):
        _emit("DEBUG", message, sys.stdout)


def dim(message: str) -> None:
    """Emit a de-emphasised line to stdout."""
    _emit("DIM", message, sys.stdout)


def line() -> None:
    """Emit the structural separator rule to stdout."""
    print("-" * RULE_WIDTH, file=sys.stdout)


def blank() -> None:
    """Emit a blank line to stdout."""
    print("", file=sys.stdout)


def enable_debug() -> None:
    """Turn on debug output for this process by setting the debug gate."""
    os.environ[DEBUG_ENV_VAR] = "1"


def notice_block(notices: Iterable[tuple[str, str, str, str]]) -> None:
    """Render attention-signal notices to stdout.

    Emits one blank line before the block, then each notice as a
    ``[TAG]`` token on its own line followed by the label, summary, and
    each line of the detail, all two-space indented. Emits nothing when
    ``notices`` is empty.

    Args:
        notices: Sequence of ``(tag, label, summary, detail)`` tuples,
            already in render order. ``tag`` is a bare name such as
            ``"REVIEW"`` or ``"WARNING"``; ``detail`` may contain
            embedded newlines.
    """
    notices = list(notices)
    if not notices:
        return
    blank()
    for tag, label, summary, detail in notices:
        print(_render_token(tag, sys.stdout, pad=False))
        print(f"  label: {label}")
        print(f"  {summary}")
        for detail_line in detail.split("\n"):
            print(f"  {detail_line}")
