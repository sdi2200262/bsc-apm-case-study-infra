# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Hand-written annotations attached to grader results.

The grader produces a per-submission ``results.json`` that scores
every rubric row and carries the per-test message the assertion
emitted. Sometimes a row's outcome needs a free-prose note that
records the cause behind the score in a way the structured
message cannot: a feature path that traces leak-free under
valgrind because the participant's handler short-circuits before
allocating, a strict match that passes because the participant
matched a peripheral seed value rather than the intended
contract, an infrastructure row that fails for a reason
upstream of the participant's work.

Notes live in a YAML sidecar named ``results_notes.yaml`` in
the same directory as ``results.json``. The grader never reads
or writes the sidecar; re-running the grader does not perturb
it. The pipeline's ``combine`` stage embeds the sidecar's
contents in ``combined.json`` under the ``results_notes`` key
when the file is present, and records the sidecar's checksum in
the manifest so a downstream reader can detect edits between
combine runs.

Sidecar shape::

    notes:
      - test_ids: [C.5.1, C.5.2, C.5.3]
        note: |
          Free prose describing the one root cause shared by
          every listed rubric row. Multi-line content is
          supported via YAML's block scalar; trailing whitespace
          is stripped on save.
      - note: |
          A submission-level observation, not tied to any rubric
          row.

The ``test_ids`` field is optional and, when present, lists one
or more rubric rows that share a single root cause. The ``add``
subcommand validates every listed ID against the ``tests`` block
in the current ``results.json``. When absent, the note is a
submission-level observation about the submission as a whole.

The CLI is invoked as
``python -m grader.notes <subcommand> <results_dir> [...]``
where ``results_dir`` is the directory holding ``results.json``.
Subcommands:

* ``add --note "<prose>" [--test-id <id> ...]``: append one
  entry. ``--test-id`` may be repeated; every ID must address an
  entry in the current ``results.json``'s ``tests`` block, and
  the listed rows all share the one root cause the note states.
* ``list``: print every note with its index plus a freshness
  indicator (a ``test_ids`` entry naming a row that has
  disappeared from ``results.json`` after a re-run is flagged
  ``stale``).
* ``remove --index <N>``: delete the entry at the given index.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from . import log

NOTES_FILENAME = "results_notes.yaml"
RESULTS_FILENAME = "results.json"


class NotesError(Exception):
    """Raised when a notes operation fails for a recoverable reason."""


def load_notes(directory: Path) -> list[dict[str, Any]]:
    """Read the notes sidecar in ``directory``, returning the entry list.

    Args:
        directory: Directory holding ``results.json`` and
            (optionally) ``results_notes.yaml``.

    Returns:
        The parsed list of note entries. Each entry carries a
        non-empty ``note`` string; an entry that attaches to
        rubric rows also carries a non-empty ``test_ids`` list of
        non-empty strings. An empty list when the sidecar is
        absent or its ``notes`` field is empty.

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
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(notes):
        if not isinstance(entry, dict):
            raise NotesError(
                f"sidecar at {path} entry {index} must be a mapping"
            )
        note_value = entry.get("note")
        if not isinstance(note_value, str) or not note_value.strip():
            raise NotesError(
                f"sidecar at {path} entry {index} 'note' must be a non-empty string"
            )
        entry_out: dict[str, Any] = {"note": note_value.rstrip()}
        test_ids = entry.get("test_ids")
        if test_ids is not None:
            if (
                not isinstance(test_ids, list)
                or not test_ids
                or not all(isinstance(t, str) and t for t in test_ids)
            ):
                raise NotesError(
                    f"sidecar at {path} entry {index} 'test_ids' must be a "
                    f"non-empty list of non-empty strings when present"
                )
            entry_out["test_ids"] = list(test_ids)
        out.append(entry_out)
    return out


def save_notes(directory: Path, notes: list[dict[str, Any]]) -> None:
    """Write the entry list to the notes sidecar in ``directory``.

    The write is atomic via sibling-tempfile rename; concurrent
    readers see either the previous or the new content, never a
    partial write. An empty entry list removes the sidecar.
    Multi-line note text is serialised as a YAML literal block
    scalar (``|``) so the file stays readable when opened in a
    plain editor.

    Args:
        directory: Directory holding ``results.json``.
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
        log.error(str(error))
        return 1


class _LiteralBlockDumper(yaml.SafeDumper):
    """SafeDumper variant that emits multi-line strings as literal block scalars.

    PyYAML's default behaviour for multi-line strings is to fall back
    to single-quoted form with embedded blank-line markers, which is
    valid YAML but hard to read. The literal ``|`` style preserves
    line breaks exactly and reads cleanly in a plain editor.
    """


def _represent_str_literal_when_multiline(dumper: yaml.SafeDumper, data: str) -> Any:
    """Choose ``|`` block scalar for multi-line strings, default for the rest.

    Args:
        dumper: Active PyYAML dumper.
        data: String value being serialised.

    Returns:
        A YAML scalar node with literal style ``|`` when ``data``
        carries a newline, default scalar style otherwise.
    """
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_LiteralBlockDumper.add_representer(str, _represent_str_literal_when_multiline)


def _read_results(directory: Path) -> dict[str, Any]:
    """Load ``results.json`` from ``directory`` for test-ID validation."""
    path = directory / RESULTS_FILENAME
    if not path.is_file():
        raise NotesError(
            f"{RESULTS_FILENAME} not found in {directory}; run the grader first"
        )
    with path.open("r", encoding="utf-8") as source:
        try:
            return json.load(source)
        except json.JSONDecodeError as error:
            raise NotesError(f"{path} is not valid JSON: {error}") from error


def _known_test_ids(results: dict[str, Any]) -> set[str]:
    """Return the set of rubric IDs recorded in a results payload."""
    tests = results.get("tests")
    if not isinstance(tests, dict):
        return set()
    return set(tests.keys())


def _cmd_add(args: argparse.Namespace) -> int:
    """Append one entry to the sidecar after optional test-ID validation.

    Args:
        args: Parsed namespace carrying ``results_dir``, ``note``,
            and optional ``test_ids``.

    Returns:
        Process exit code (``0`` on success).

    Raises:
        NotesError: When the note text is empty after stripping, a
            listed test ID is absent from ``results.json``, or
            ``results.json`` is missing or malformed.
    """
    directory = args.results_dir
    note_text = args.note.rstrip()
    if not note_text:
        raise NotesError("--note must contain non-whitespace text")
    entry: dict[str, Any] = {"note": note_text}
    if args.test_ids:
        results = _read_results(directory)
        known = _known_test_ids(results)
        unknown = [tid for tid in args.test_ids if tid not in known]
        if unknown:
            raise NotesError(
                f"test_ids {unknown!r} not in {RESULTS_FILENAME}'s tests block"
            )
        entry["test_ids"] = list(args.test_ids)
    notes = load_notes(directory)
    notes.append(entry)
    save_notes(directory, notes)
    if "test_ids" in entry:
        log.info(
            f"added note for tests {', '.join(entry['test_ids'])} "
            f"(now {len(notes)} note(s))"
        )
    else:
        log.info(f"added submission-level note (now {len(notes)} note(s))")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """Print every entry with its index and a freshness indicator.

    Args:
        args: Parsed namespace carrying ``results_dir``.

    Returns:
        Process exit code (``0`` on success).

    Raises:
        NotesError: When the sidecar is malformed or
            ``results.json`` is missing or malformed.
    """
    directory = args.results_dir
    notes = load_notes(directory)
    if not notes:
        log.info(f"no notes in {directory / NOTES_FILENAME}")
        return 0
    results = _read_results(directory)
    known = _known_test_ids(results)
    for index, entry in enumerate(notes):
        test_ids = entry.get("test_ids")
        if not test_ids:
            scope = "submission-level"
        elif all(tid in known for tid in test_ids):
            scope = f"tests={','.join(test_ids)} ok"
        else:
            missing = [tid for tid in test_ids if tid not in known]
            scope = f"tests={','.join(test_ids)} stale (missing {','.join(missing)})"
        log.info(f"#{index} {scope}")
        for note_line in entry["note"].rstrip().splitlines():
            log.info(f"      {note_line}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    """Remove the entry at the given index.

    Args:
        args: Parsed namespace carrying ``results_dir`` and the
            integer ``index``.

    Returns:
        Process exit code (``0`` on success).

    Raises:
        NotesError: When the sidecar is missing or empty, or when
            ``index`` is out of range.
    """
    directory = args.results_dir
    notes = load_notes(directory)
    if not notes:
        raise NotesError(f"no notes to remove in {directory / NOTES_FILENAME}")
    if args.index < 0 or args.index >= len(notes):
        raise NotesError(
            f"index {args.index} out of range; sidecar has {len(notes)} entries"
        )
    removed = notes.pop(args.index)
    save_notes(directory, notes)
    target = (
        ", ".join(removed["test_ids"])
        if removed.get("test_ids")
        else "submission-level"
    )
    log.info(f"removed note ({target}; now {len(notes)} note(s))")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with three subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m grader.notes",
        description=(
            "Manage hand-written annotations on grader results. "
            "Notes live in results_notes.yaml beside results.json."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand")
    add_parser = sub.add_parser(
        "add",
        help="append one note, optionally tied to a rubric row",
    )
    add_parser.add_argument(
        "results_dir",
        type=Path,
        help="directory holding results.json",
    )
    add_parser.add_argument(
        "--note",
        required=True,
        help="free-prose note text; multi-line content can use embedded newlines",
    )
    add_parser.add_argument(
        "--test-id",
        dest="test_ids",
        action="append",
        default=None,
        metavar="ID",
        help=(
            "rubric ID this note attaches to (e.g. C.5.2); repeatable "
            "to bind several rows that share one root cause; every ID "
            "is validated against results.json. Omit for a "
            "submission-level note"
        ),
    )
    list_parser = sub.add_parser(
        "list",
        help="print every note with its index and a freshness indicator",
    )
    list_parser.add_argument(
        "results_dir",
        type=Path,
        help="directory holding results.json",
    )
    remove_parser = sub.add_parser(
        "remove",
        help="delete the entry at the given index",
    )
    remove_parser.add_argument(
        "results_dir",
        type=Path,
        help="directory holding results.json",
    )
    remove_parser.add_argument(
        "--index",
        type=int,
        required=True,
        help="entry index as shown by `list`",
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
