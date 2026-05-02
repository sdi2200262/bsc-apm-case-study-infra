#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026

"""Delete every Claude Code transcript for a workspace.

Resolves the workspace path to its corresponding entry under
``~/.claude/projects/`` and deletes every ``.jsonl`` transcript inside.
The Claude Code project directory itself is left in place; only the
transcript files are removed. Other files inside the project directory
(if any) are left untouched.

This action is destructive. By default it lists the files it would
delete and prompts for confirmation. Pass ``--force`` to skip the
prompt; the listing still prints so the action stays observable.

Exit codes: ``0`` on a successful deletion or a confirmed no-op; ``1``
on input errors; ``2`` when the user declines the prompt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECTS_ROOT = Path.home() / ".claude" / "projects"


def encode_workspace(workspace: Path) -> str:
    """Encode an absolute workspace path the way Claude Code names project directories.

    Args:
        workspace: Resolved absolute workspace path.

    Returns:
        The encoded directory name (each ``/`` becomes ``-``).
    """
    return str(workspace).replace("/", "-")


def resolve_project_dir(workspace: Path) -> Path:
    """Resolve a workspace path to its Claude Code project directory.

    Args:
        workspace: Workspace path supplied by the participant.

    Returns:
        Absolute path to ``~/.claude/projects/<encoded>``.

    Raises:
        FileNotFoundError: If the workspace path does not exist or the
            corresponding project directory does not exist.
    """
    if not workspace.exists():
        raise FileNotFoundError(f"workspace path does not exist: {workspace}")
    if not workspace.is_dir():
        raise FileNotFoundError(f"workspace path is not a directory: {workspace}")
    encoded = encode_workspace(workspace.resolve())
    project_dir = PROJECTS_ROOT / encoded
    if not project_dir.exists():
        raise FileNotFoundError(
            f"no Claude Code project directory found at {project_dir}; "
            f"has Claude Code been launched in {workspace}?"
        )
    return project_dir


def list_transcripts(project_dir: Path) -> list[Path]:
    """List every ``.jsonl`` transcript in a project directory.

    Args:
        project_dir: Resolved Claude Code project directory.

    Returns:
        Paths sorted by file name.
    """
    return sorted(project_dir.glob("*.jsonl"))


def confirm(prompt: str) -> bool:
    """Prompt for an interactive yes/no confirmation.

    Args:
        prompt: Text shown to the user.

    Returns:
        ``True`` if the user answers ``y``/``yes``, ``False`` otherwise.
    """
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def delete_transcripts(transcripts: list[Path]) -> int:
    """Delete each transcript file, reporting per-file outcomes.

    Args:
        transcripts: Files to delete.

    Returns:
        Count of files successfully deleted.
    """
    deleted = 0
    for path in transcripts:
        try:
            path.unlink()
            print(f"  deleted {path.name}")
            deleted += 1
        except OSError as exc:
            print(f"  failed  {path.name} ({exc})", file=sys.stderr)
    return deleted


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Delete every Claude Code transcript for a workspace. Resolves "
            "the workspace path to its ~/.claude/projects/ entry and "
            "removes every .jsonl file inside. Destructive: prompts for "
            "confirmation by default; pass --force to skip the prompt."
        ),
        epilog=(
            "Examples:\n"
            "  reset-chats.py ~/work/eclass-mcp-server\n"
            "  reset-chats.py ~/work/eclass-mcp-server --force"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "workspace",
        type=Path,
        help="Absolute path to the workspace directory Claude Code was launched in.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete without the interactive confirmation prompt.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Optional argument vector for testing.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    try:
        project_dir = resolve_project_dir(args.workspace)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    transcripts = list_transcripts(project_dir)
    if not transcripts:
        print(f"No transcripts to delete in {project_dir}.")
        return 0
    print(f"About to delete {len(transcripts)} transcript(s) from {project_dir}:")
    for path in transcripts:
        print(f"  {path.name}")
    if not args.force and not confirm("Proceed?"):
        print("Aborted; no files were deleted.")
        return 2
    deleted = delete_transcripts(transcripts)
    print(f"Done: {deleted} of {len(transcripts)} deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
