#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026

"""List Claude Code transcripts.

Two source modes, exactly one of which must be selected explicitly:

* ``--from-projects``: treat the positional path as a workspace
  directory Claude Code was launched in, and resolve it to the
  corresponding entry under ``~/.claude/projects/``.
* ``--from-dir``: treat the positional path as a directory of
  ``.jsonl`` transcripts and scan it directly. Used to verify a
  previously collected ``transcripts/`` directory.

In either mode, the script prints one row per transcript file with the
file name, the first record timestamp, the last record timestamp, and a
short preview of the first user message. The default output is a plain
text table; ``--json`` emits the same data as a JSON array on stdout.

Exit codes: ``0`` on success (zero or more transcripts found); ``1`` on
input errors (no source mode selected, path missing, no Claude Code
project directory, unreadable transcripts).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PREVIEW_CHARS = 120
PROJECTS_ROOT = Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class TranscriptInfo:
    """Summary of one transcript file.

    Attributes:
        path: Absolute path to the ``.jsonl`` file.
        first_timestamp: ISO timestamp of the earliest record, or empty.
        last_timestamp: ISO timestamp of the latest record, or empty.
        first_message: One-line preview of the first user message, or empty.
    """

    path: Path
    first_timestamp: str
    last_timestamp: str
    first_message: str


def encode_workspace(workspace: Path) -> str:
    """Encode an absolute workspace path the way Claude Code names project directories.

    Args:
        workspace: Resolved absolute workspace path.

    Returns:
        The encoded directory name (each ``/`` becomes ``-``, including the leading slash).
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


def extract_text(content: Any) -> str:
    """Extract a plain-text preview from a Claude Code message content field.

    Args:
        content: The ``message.content`` field of a user record. May be a
            string or a list of content blocks (each a dict with ``type`` and
            possibly ``text``).

    Returns:
        A whitespace-collapsed text preview, possibly empty.
    """
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                value = block.get("text", "")
                if isinstance(value, str):
                    parts.append(value)
        text = " ".join(parts)
    else:
        text = ""
    return " ".join(text.split())


def summarise_transcript(path: Path) -> TranscriptInfo:
    """Read a transcript file and produce its summary.

    Args:
        path: Absolute path to the ``.jsonl`` file.

    Returns:
        A populated :class:`TranscriptInfo`. Fields stay empty when the
        underlying records do not provide the corresponding data.
    """
    first_ts = ""
    last_ts = ""
    first_message = ""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = record.get("timestamp", "")
            if isinstance(timestamp, str) and timestamp:
                if not first_ts:
                    first_ts = timestamp
                last_ts = timestamp
            if not first_message and record.get("type") == "user":
                message = record.get("message", {})
                if isinstance(message, dict) and message.get("role") == "user":
                    text = extract_text(message.get("content"))
                    if text:
                        first_message = text
    return TranscriptInfo(
        path=path,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        first_message=first_message,
    )


def collect_transcripts(project_dir: Path) -> list[TranscriptInfo]:
    """Summarise every ``.jsonl`` transcript in a project directory.

    Args:
        project_dir: Resolved Claude Code project directory.

    Returns:
        List of summaries sorted by ``first_timestamp`` ascending; files with
        no parseable timestamp sort last.
    """
    summaries = [summarise_transcript(p) for p in sorted(project_dir.glob("*.jsonl"))]
    summaries.sort(key=lambda s: (s.first_timestamp == "", s.first_timestamp))
    return summaries


def render_text(summaries: list[TranscriptInfo], project_dir: Path) -> str:
    """Render the summary list as a plain text table.

    Args:
        summaries: Transcript summaries to render.
        project_dir: The project directory the summaries came from.

    Returns:
        Multi-line string ready for stdout.
    """
    if not summaries:
        return f"No transcripts found in {project_dir}.\n"
    lines = [f"Transcripts in {project_dir} ({len(summaries)} file(s)):", ""]
    for summary in summaries:
        preview = summary.first_message or "(no user message found)"
        if len(preview) > PREVIEW_CHARS:
            preview = preview[: PREVIEW_CHARS - 1] + "…"
        lines.append(f"  file:    {summary.path.name}")
        lines.append(f"  first:   {summary.first_timestamp or '(unknown)'}")
        lines.append(f"  last:    {summary.last_timestamp or '(unknown)'}")
        lines.append(f"  message: {preview}")
        lines.append("")
    return "\n".join(lines)


def render_json(summaries: list[TranscriptInfo]) -> str:
    """Render the summary list as a JSON array.

    Args:
        summaries: Transcript summaries to render.

    Returns:
        JSON-encoded string with one object per transcript.
    """
    payload = [
        {
            "file": s.path.name,
            "path": str(s.path),
            "first_timestamp": s.first_timestamp,
            "last_timestamp": s.last_timestamp,
            "first_message": s.first_message,
        }
        for s in summaries
    ]
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def resolve_dir(path: Path) -> Path:
    """Validate a directory of ``.jsonl`` transcripts supplied directly.

    Args:
        path: Directory to scan for ``.jsonl`` files.

    Returns:
        The resolved absolute path to the directory.

    Raises:
        FileNotFoundError: If the path does not exist or is not a directory.
    """
    if not path.exists():
        raise FileNotFoundError(f"path does not exist: {path}")
    if not path.is_dir():
        raise FileNotFoundError(f"path is not a directory: {path}")
    return path.resolve()


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "List Claude Code transcripts. Exactly one source mode must be "
            "selected: --from-projects resolves a workspace path to its "
            "~/.claude/projects/ entry, --from-dir scans a directory of "
            "*.jsonl transcripts directly. Prints one row per transcript "
            "with first and last timestamps and a preview of the first "
            "user message."
        ),
        epilog=(
            "Examples:\n"
            "  list-chats.py ~/work --from-projects\n"
            "  list-chats.py ~/work --from-projects --json\n"
            "  list-chats.py ~/work/transcripts --from-dir"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        type=Path,
        help=(
            "Workspace directory (with --from-projects) or directory of "
            "*.jsonl transcripts (with --from-dir)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit summaries as a JSON array on stdout instead of a text table.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--from-projects",
        action="store_true",
        help=(
            "Treat the positional path as the workspace Claude Code was "
            "launched in, and resolve it to the matching ~/.claude/projects/ "
            "entry."
        ),
    )
    source.add_argument(
        "--from-dir",
        action="store_true",
        help=(
            "Treat the positional path as a directory of *.jsonl transcripts "
            "and scan it directly."
        ),
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
        target_dir = resolve_dir(args.path) if args.from_dir else resolve_project_dir(args.path)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    summaries = collect_transcripts(target_dir)
    output = render_json(summaries) if args.json else render_text(summaries, target_dir)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
