#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Author-curated annotations attached to metric paths.

The parser produces a clean ``metrics.json`` for each submission. A
metric value can occasionally need a free-prose annotation that
records why a number reads the way it does: a participant pasting a
handoff document after the worker refused to read the bus file, a
session whose cost is a known lower bound because of compaction, a
turn whose duration is dominated by waiting on a slow tool. The
parser does not synthesise such notes; they are the author's
judgement and are written by hand through this module's CLI.

Notes live in a YAML sidecar named ``metrics_notes.yaml`` in the
same directory as ``metrics.json``. The parser never reads or writes
the sidecar; running ``--metrics`` again does not perturb it. The
pipeline's ``combine`` stage embeds the sidecar's contents in
``combined.json`` under the ``metrics_notes`` key when the file is
present, and records the sidecar's checksum in the manifest.

Sidecar shape::

    notes:
      - path: session.process.user_input.turn_prompts_magnitude_by_bucket.standard
        note: |
          Free prose describing why this metric reads the way it
          does. Multi-line content is supported via YAML's block
          scalar; trailing whitespace is stripped on save.

A path is a dotted address into ``metrics.json``. Object keys use
``.``; array elements use ``[N]``. A path can point to any node:
a leaf scalar, a leaf wrapper (``{value, label, constructed}``), a
metric block, or even the whole session scope. The CLI's ``add``
subcommand validates that the path resolves against the current
``metrics.json`` before writing.

The CLI is invoked as ``python -m cc_chat_parser.notes <subcommand>
<metrics_dir> [...]`` where ``metrics_dir`` is the directory holding
``metrics.json``. Subcommands:

* ``add --path <dotted> --note "<prose>"``: append one entry. The
  path must resolve against the current ``metrics.json``.
* ``list``: print every note with its index and a path-resolution
  status (a path that no longer addresses an existing node after a
  re-parse is flagged ``stale`` so the author can decide whether to
  remove or rewrite the entry).
* ``remove --index <N>``: delete the entry at the given index (as
  shown by ``list``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from .errors import ParserError

NOTES_FILENAME = "metrics_notes.yaml"
METRICS_FILENAME = "metrics.json"

_PATH_TOKEN = re.compile(r"\[(\d+)\]|\.?([^.\[\]]+)")


class NotesError(ParserError):
    """Raised when a notes operation fails for a recoverable reason."""


def parse_metric_path(dotted: str) -> list[str | int]:
    """Tokenise a dotted metric path into a list of object keys and array indices.

    Args:
        dotted: A path string such as
            ``session.economic.cost_usd.value`` or
            ``turns[3].duration_seconds``.

    Returns:
        The token list. Integers represent array indices; strings
        represent object keys.

    Raises:
        NotesError: When the path is empty or contains no token.
    """
    if not dotted:
        raise NotesError("metric path is empty")
    tokens: list[str | int] = []
    for match in _PATH_TOKEN.finditer(dotted):
        index_text, key = match.group(1), match.group(2)
        if index_text is not None:
            tokens.append(int(index_text))
        elif key:
            tokens.append(key)
    if not tokens:
        raise NotesError(f"metric path {dotted!r} is malformed")
    return tokens


def resolve_metric_path(metrics: Any, tokens: list[str | int]) -> Any:
    """Walk a tokenised metric path through a metrics payload.

    Args:
        metrics: The parsed ``metrics.json`` payload.
        tokens: A token list from :func:`parse_metric_path`.

    Returns:
        The node at the resolved path.

    Raises:
        NotesError: When a token does not address an existing key or
            index in the payload.
    """
    cursor: Any = metrics
    walked: list[str] = []
    for token in tokens:
        walked.append(_render_token(token))
        if isinstance(token, int):
            if not isinstance(cursor, list):
                raise NotesError(
                    f"path .{'.'.join(walked)} expects a list at this depth, "
                    f"got {type(cursor).__name__}"
                )
            if token >= len(cursor) or token < -len(cursor):
                raise NotesError(
                    f"path .{'.'.join(walked)} index {token} is out of range"
                )
            cursor = cursor[token]
        else:
            if not isinstance(cursor, dict):
                raise NotesError(
                    f"path .{'.'.join(walked)} expects an object at this depth, "
                    f"got {type(cursor).__name__}"
                )
            if token not in cursor:
                raise NotesError(f"path .{'.'.join(walked)} not found")
            cursor = cursor[token]
    return cursor


def load_notes(directory: Path) -> list[dict[str, str]]:
    """Read the notes sidecar in ``directory``, returning the entry list.

    Args:
        directory: Directory holding ``metrics.json`` and (optionally)
            ``metrics_notes.yaml``.

    Returns:
        The parsed list of ``{path, note}`` dicts. An empty list when
        the sidecar is absent or its ``notes`` field is empty.

    Raises:
        NotesError: When the sidecar exists but is malformed.
    """
    path = directory / NOTES_FILENAME
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8") as source:
        try:
            payload = yaml.safe_load(source) or {}
        except yaml.YAMLError as error:
            raise NotesError(f"sidecar at {path} is not valid YAML: {error}") from error
    if not isinstance(payload, dict):
        raise NotesError(f"sidecar at {path} top level must be a YAML mapping")
    notes = payload.get("notes", [])
    if notes is None:
        return []
    if not isinstance(notes, list):
        raise NotesError(f"sidecar at {path} 'notes' must be a list")
    out: list[dict[str, str]] = []
    for index, entry in enumerate(notes):
        if not isinstance(entry, dict):
            raise NotesError(
                f"sidecar at {path} entry {index} must be a mapping"
            )
        path_value = entry.get("path")
        note_value = entry.get("note")
        if not isinstance(path_value, str) or not path_value:
            raise NotesError(
                f"sidecar at {path} entry {index} 'path' must be a non-empty string"
            )
        if not isinstance(note_value, str) or not note_value.strip():
            raise NotesError(
                f"sidecar at {path} entry {index} 'note' must be a non-empty string"
            )
        out.append({"path": path_value, "note": note_value.rstrip()})
    return out


def save_notes(directory: Path, notes: list[dict[str, str]]) -> None:
    """Write the entry list to the notes sidecar in ``directory``.

    The write is atomic via sibling-tempfile rename; concurrent
    readers see either the previous or the new content, never a
    partial write. An empty entry list removes the sidecar.
    Multi-line note text is serialised as a YAML literal block
    scalar (``|``) so the file stays readable when opened in a
    plain editor.

    Args:
        directory: Directory holding ``metrics.json``.
        notes: The entry list to persist.
    """
    path = directory / NOTES_FILENAME
    if not notes:
        if path.exists():
            path.unlink()
        return
    payload = {"notes": notes}
    temp_path = path.parent / f".{path.name}.tmp"
    with temp_path.open("w", encoding="utf-8") as sink:
        yaml.dump(
            payload,
            sink,
            Dumper=_LiteralBlockDumper,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        sink.flush()
    temp_path.rename(path)


class _LiteralBlockDumper(yaml.SafeDumper):
    """SafeDumper variant that emits multi-line strings as literal block scalars.

    PyYAML's default behaviour for multi-line strings is to fall back
    to single-quoted form with embedded blank-line markers, which is
    valid YAML but hard to read. The literal ``|`` style preserves
    line breaks exactly and reads cleanly in a plain editor.
    """


def _represent_str_literal_when_multiline(dumper: yaml.SafeDumper, data: str) -> Any:
    """Choose ``|`` block scalar for multi-line strings, default for the rest."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_LiteralBlockDumper.add_representer(str, _represent_str_literal_when_multiline)


def _render_token(token: str | int) -> str:
    """Format a single path token for display in error messages."""
    if isinstance(token, int):
        return f"[{token}]"
    return token


def _read_metrics(directory: Path) -> Any:
    """Load ``metrics.json`` from ``directory`` for path validation."""
    path = directory / METRICS_FILENAME
    if not path.is_file():
        raise NotesError(
            f"{METRICS_FILENAME} not found in {directory}; run the parser first"
        )
    import json

    with path.open("r", encoding="utf-8") as source:
        try:
            return json.load(source)
        except json.JSONDecodeError as error:
            raise NotesError(f"{path} is not valid JSON: {error}") from error


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` on success, ``1`` on a recoverable
        notes error, ``2`` on operator error (missing flags).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return 2
    handler = {
        "add": _cmd_add,
        "list": _cmd_list,
        "remove": _cmd_remove,
    }[args.subcommand]
    try:
        return handler(args)
    except NotesError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with three subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m cc_chat_parser.notes",
        description=(
            "Manage author-curated annotations on metric paths. "
            "Notes live in metrics_notes.yaml beside metrics.json."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand")
    add_parser = sub.add_parser(
        "add",
        help="append one note after validating its metric path",
    )
    add_parser.add_argument(
        "metrics_dir",
        type=Path,
        help="directory holding metrics.json",
    )
    add_parser.add_argument(
        "--path",
        required=True,
        help=(
            "dotted metric path (e.g. session.economic.cost_usd or "
            "turns[3].duration_seconds)"
        ),
    )
    add_parser.add_argument(
        "--note",
        required=True,
        help="free-prose note text; multi-line content can use embedded newlines",
    )
    list_parser = sub.add_parser(
        "list",
        help="print every note with its index and a freshness indicator",
    )
    list_parser.add_argument(
        "metrics_dir",
        type=Path,
        help="directory holding metrics.json",
    )
    remove_parser = sub.add_parser(
        "remove",
        help="delete the entry at the given index",
    )
    remove_parser.add_argument(
        "metrics_dir",
        type=Path,
        help="directory holding metrics.json",
    )
    remove_parser.add_argument(
        "--index",
        type=int,
        required=True,
        help="entry index as shown by `list`",
    )
    return parser


def _cmd_add(args: argparse.Namespace) -> int:
    """Append one entry to the sidecar after validating its path."""
    directory = args.metrics_dir
    note_text = args.note.strip()
    if not note_text:
        print("error: note text cannot be empty", file=sys.stderr)
        return 1

    metrics = _read_metrics(directory)
    tokens = parse_metric_path(args.path)
    resolve_metric_path(metrics, tokens)
    notes = load_notes(directory)
    notes.append({"path": args.path, "note": note_text})
    save_notes(directory, notes)
    print(f"added note at {args.path} (now {len(notes)} note(s))")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """Print every entry with its index and a freshness indicator."""
    directory = args.metrics_dir
    notes = load_notes(directory)
    if not notes:
        print(f"no notes in {directory / NOTES_FILENAME}")
        return 0
    metrics = _read_metrics(directory)
    for index, entry in enumerate(notes):
        try:
            tokens = parse_metric_path(entry["path"])
            resolve_metric_path(metrics, tokens)
            status = "ok"
        except NotesError as error:
            status = f"stale ({error})"
        print(f"[{index}] path={entry['path']}  status={status}")
        for line in entry["note"].rstrip().splitlines():
            print(f"      {line}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    """Remove the entry at the given index."""
    directory = args.metrics_dir
    notes = load_notes(directory)
    if not notes:
        raise NotesError(f"no notes to remove in {directory / NOTES_FILENAME}")
    if args.index < 0 or args.index >= len(notes):
        raise NotesError(
            f"index {args.index} out of range; sidecar has {len(notes)} entries"
        )
    removed = notes.pop(args.index)
    save_notes(directory, notes)
    print(f"removed note at {removed['path']} (now {len(notes)} note(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
