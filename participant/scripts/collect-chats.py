#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026

"""Copy Claude Code transcripts within a time range into a workspace folder.

Resolves the workspace path to its corresponding entry under
``~/.claude/projects/``, selects every ``.jsonl`` transcript whose first
record timestamp falls in the inclusive range ``[--from, --to]``, and
copies each into ``<workspace>/transcripts/``. The destination folder is
created if missing.

Bad timestamps in ``--from`` or ``--to`` produce a clear error and a non
zero exit code without touching the filesystem. The destination directory
is never deleted; existing files inside it are kept (a per-file overwrite
prompt asks before replacement, unless ``--force`` is given).

Exit codes: ``0`` on success; ``1`` on input errors; ``2`` when the user
declines an overwrite prompt.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_ROOT = Path.home() / ".claude" / "projects"
DEST_DIRNAME = "transcripts"


@dataclass(frozen=True)
class TimeRange:
    """Inclusive time range used to filter transcripts.

    Attributes:
        start: Lower bound, timezone-aware UTC.
        end: Upper bound, timezone-aware UTC.
    """

    start: datetime
    end: datetime


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


def parse_iso(value: str, label: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware UTC ``datetime``.

    Accepts naive timestamps (treated as UTC), trailing ``Z``, and explicit
    offsets. Date-only inputs are accepted.

    Args:
        value: User-supplied timestamp string.
        label: Argument name used in the error message.

    Returns:
        Timezone-aware ``datetime`` in UTC.

    Raises:
        ValueError: If the input cannot be parsed as an ISO timestamp.
    """
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(
            f"{label}: not a valid ISO-8601 timestamp: {value!r} ({exc})"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_timestamp(path: Path) -> datetime | None:
    """Read the first parseable record timestamp from a transcript file.

    Args:
        path: Absolute path to a ``.jsonl`` file.

    Returns:
        Timezone-aware UTC ``datetime``, or ``None`` if no usable timestamp
        was found.
    """
    import json

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            value = record.get("timestamp")
            if isinstance(value, str) and value:
                try:
                    return parse_iso(value, "transcript")
                except ValueError:
                    continue
    return None


def select_in_range(project_dir: Path, window: TimeRange) -> list[Path]:
    """Select transcripts whose first timestamp falls in ``window``.

    Args:
        project_dir: Resolved Claude Code project directory.
        window: Inclusive UTC time range.

    Returns:
        Paths sorted by first timestamp ascending.
    """
    selected: list[tuple[datetime, Path]] = []
    for path in sorted(project_dir.glob("*.jsonl")):
        ts = first_timestamp(path)
        if ts is None:
            continue
        if window.start <= ts <= window.end:
            selected.append((ts, path))
    selected.sort(key=lambda pair: pair[0])
    return [path for _, path in selected]


def confirm_overwrite(target: Path) -> bool:
    """Prompt the user before overwriting an existing destination file.

    Args:
        target: Destination path that already exists.

    Returns:
        ``True`` if the user confirms (``y``/``yes``), ``False`` otherwise.
    """
    answer = input(f"  overwrite existing {target.name}? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def copy_into_workspace(
    sources: list[Path],
    workspace: Path,
    force: bool,
) -> tuple[int, int, int]:
    """Copy transcripts into ``<workspace>/transcripts/``.

    Args:
        sources: Source transcript paths.
        workspace: Workspace path the participant supplied.
        force: When ``True``, overwrite without prompting.

    Returns:
        Tuple ``(copied, skipped, declined)``: counts of files newly written,
        files unchanged because the source equalled the destination, and
        files the user declined to overwrite.
    """
    dest_dir = workspace / DEST_DIRNAME
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    declined = 0
    for source in sources:
        target = dest_dir / source.name
        if target.exists():
            if not force and not confirm_overwrite(target):
                print(f"  skipped {source.name}")
                declined += 1
                continue
        shutil.copy2(source, target)
        print(f"  copied  {source.name}")
        copied += 1
    return copied, skipped, declined


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Copy Claude Code transcripts whose first record timestamp falls "
            "in [--from, --to] from ~/.claude/projects/<encoded>/ into "
            "<workspace>/transcripts/. The destination directory is created "
            "if it does not exist; existing files prompt for overwrite "
            "unless --force is given."
        ),
        epilog=(
            "Examples:\n"
            "  collect-chats.py ~/work/eclass-mcp-server \\\n"
            "      --from 2026-05-01T09:00 --to 2026-05-01T12:30\n"
            "  collect-chats.py ~/work/eclass-mcp-server \\\n"
            "      --from 2026-05-01 --to 2026-05-02 --force"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "workspace",
        type=Path,
        help="Absolute path to the workspace directory Claude Code was launched in.",
    )
    parser.add_argument(
        "--from",
        dest="from_ts",
        required=True,
        help="Inclusive start of the time range (ISO-8601, naive treated as UTC).",
    )
    parser.add_argument(
        "--to",
        dest="to_ts",
        required=True,
        help="Inclusive end of the time range (ISO-8601, naive treated as UTC).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in the destination without prompting.",
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
        start = parse_iso(args.from_ts, "--from")
        end = parse_iso(args.to_ts, "--to")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if start > end:
        print(
            f"error: --from ({start.isoformat()}) is after --to ({end.isoformat()})",
            file=sys.stderr,
        )
        return 1
    try:
        project_dir = resolve_project_dir(args.workspace)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    window = TimeRange(start=start, end=end)
    selected = select_in_range(project_dir, window)
    if not selected:
        print(
            f"No transcripts in {project_dir} with first timestamp in "
            f"[{start.isoformat()}, {end.isoformat()}].",
            file=sys.stderr,
        )
        return 0
    print(f"Copying {len(selected)} transcript(s) into {args.workspace / DEST_DIRNAME}:")
    copied, _, declined = copy_into_workspace(selected, args.workspace, args.force)
    print(f"Done: {copied} copied, {declined} declined.")
    return 2 if declined and copied == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
