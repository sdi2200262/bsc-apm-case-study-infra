#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Validate a participant submission zip and unpack it to the dataset staging area.

The submission zip contract:

* Filename matches ``{PID}_S{1|2}_{apm|speckit}.zip``.
* The zip's root contains exactly two entries: ``solution.patch``
  (the patch the grader will apply against baseline) and
  ``transcripts/``. Participants produce this layout by following
  the guide's wrap-up step: from inside the workspace directory,
  ``zip -r <name>.zip solution.patch transcripts/``.
* No other files or directories at the zip's root.
* Inside ``transcripts/``: top-level entries are either
  ``<sessionId>.jsonl`` main-session files (one per main session
  Claude Code wrote under ``~/.claude/projects/<dashed-cwd>/``) or
  ``<sessionId>/`` subdirectories carrying the auxiliary records
  Claude Code wrote alongside that session. Each
  ``<sessionId>/`` subdirectory's name must match a top-level
  ``<sessionId>.jsonl`` file (no orphan subdirectories), and its
  contents are restricted to ``subagents/agent-<agentId>.jsonl``
  files and ``tool-results/`` files. Sessions with no subagent
  dispatches and no cached tool results have no subdirectory and
  ship as a bare ``.jsonl`` only.

The validate stage:

1. Parses the zip filename into a ``SubmissionName``.
2. Inspects the zip's contents without extracting: confirms the
   exact two-entry structure at the root, the patch presence, and
   the transcripts contents (top-level ``.jsonl`` files plus
   well-formed ``<sessionId>/`` subdirectories with matching main
   files).
3. Extracts to ``<output-root>/_staging/<manifest_key>/`` when
   the zip layout is well-formed.
4. Records the validate stage entry in
   ``<output-root>/pipeline_manifest.json`` with the input zip
   checksum, the extracted staging path, the transcript file
   count, the session-subdirectory count, and any non-fatal
   warnings.

The validate stage enforces structural shape only; semantic
completeness (every ``Agent`` dispatch in a main JSONL having a
matching ``subagents/agent-<agentId>.jsonl`` sibling) is the
parser's responsibility and is enforced as a strict
``KeyError`` at parse time. A submission whose subagent files are
absent for dispatches that did happen passes validate but fails
parse with a descriptive error pointing at the missing file.

A non-zero exit code is returned on filename mismatch, on layout
violations that prevent extraction, on extraction errors, and on
manifest-write failures. A successful run prints a one-line
summary of the extracted submission to stdout for operator
feedback.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from .errors import (
    PipelineError,
    StageExecutionError,
    SubmissionFormatError,
)
from .io import compute_checksum
from .manifest import (
    STAGE_VALIDATE,
    STATUS_SUCCESS,
    add_stage,
    load_manifest,
    save_manifest,
)
from .submissions import SubmissionName, parse_submission_name

STAGING_DIRNAME = "_staging"
TRANSCRIPTS_DIRNAME = "transcripts"
PATCH_FILENAME = "solution.patch"
JSONL_SUFFIX = ".jsonl"
SUBAGENTS_DIRNAME = "subagents"
TOOL_RESULTS_DIRNAME = "tool-results"
SUBAGENT_FILENAME_PREFIX = "agent-"
SUBAGENT_META_SUFFIX = ".meta.json"
ALLOWED_SESSION_SUBDIRS = frozenset({SUBAGENTS_DIRNAME, TOOL_RESULTS_DIRNAME})


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the validate stage.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` on success, ``1`` on a recovered
        error (invalid filename or layout, manifest save failure),
        ``2`` on operator error (missing zip path).
    """
    args = _parse_args(argv)
    if not args.zip_path.exists():
        print(f"error: zip not found: {args.zip_path}", file=sys.stderr)
        return 2
    try:
        submission = parse_submission_name(args.zip_path.name)
        layout = _validate_layout(args.zip_path, submission)
        staging_dir = _extract_to_staging(args.zip_path, args.output_root, submission)
        warnings = layout.warnings
        manifest = load_manifest(args.output_root)
        manifest = add_stage(
            manifest,
            submission.manifest_key,
            STAGE_VALIDATE,
            STATUS_SUCCESS,
            input_zip=args.zip_path.name,
            input_checksum=compute_checksum(args.zip_path),
            staging_path=str(staging_dir.relative_to(args.output_root)),
            transcripts_count=layout.transcripts_count,
            session_subdirs_count=layout.session_subdirs_count,
            warnings=warnings,
        )
        save_manifest(manifest)
    except SubmissionFormatError as error:
        print(f"error: invalid submission: {error}", file=sys.stderr)
        return 1
    except StageExecutionError as error:
        print(f"error: validate failed: {error}", file=sys.stderr)
        return 1
    except PipelineError as error:
        print(f"error: pipeline error: {error}", file=sys.stderr)
        return 1
    print(
        f"validated: {submission.manifest_key} "
        f"({layout.transcripts_count} transcript file"
        f"{'s' if layout.transcripts_count != 1 else ''}, "
        f"{layout.session_subdirs_count} session subdirector"
        f"{'ies' if layout.session_subdirs_count != 1 else 'y'}); "
        f"unpacked to {staging_dir.relative_to(args.output_root)}"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse the CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.validate",
        description=(
            "Validate a participant submission zip and unpack it to the "
            "dataset staging area."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "zip_path",
        type=Path,
        help="Path to the submission zip file ({PID}_S{1|2}_{apm|speckit}.zip).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help=(
            "Dataset output root directory. Manifest and staging area live "
            "under this path; per-participant artifacts are promoted here "
            "by later stages."
        ),
    )
    return parser.parse_args(argv)


class _Layout:
    """Validated layout information about a submission zip.

    A small container rather than a dataclass because it carries
    only loop-internal state for ``main()``; the persisted shape
    of validate-stage output is the manifest entry written by
    ``add_stage``, not this class.
    """

    def __init__(
        self,
        transcripts_count: int,
        session_subdirs_count: int,
        warnings: list[str],
    ) -> None:
        self.transcripts_count = transcripts_count
        self.session_subdirs_count = session_subdirs_count
        self.warnings = warnings


def _validate_layout(zip_path: Path, _submission: SubmissionName) -> _Layout:
    """Inspect the zip's contents without extracting and confirm the contract.

    The ``_submission`` parameter is part of the function's interface contract
    for signature consistency with other validate helpers; the layout check
    operates on the zip's contents only and does not inspect the parsed name.

    Args:
        zip_path: Path to the submission zip.
        _submission: Parsed submission identifiers (reserved for interface
            consistency; not inspected by the layout check).

    Returns:
        A ``_Layout`` describing the validated transcript file
        count and any non-fatal warnings.

    Raises:
        SubmissionFormatError: When any layout invariant is
            violated.
        StageExecutionError: When the zip cannot be opened.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            entries = archive.namelist()
    except zipfile.BadZipFile as error:
        raise StageExecutionError(
            f"validate: cannot open zip {zip_path}: {error}"
        ) from error
    rooted = _normalise_entries(entries)
    _require_entry(rooted, PATCH_FILENAME, zip_path)
    transcripts_count, session_subdirs_count, warnings = _validate_transcripts(
        rooted, zip_path
    )
    _reject_unknown_top_level(rooted, zip_path)
    return _Layout(
        transcripts_count=transcripts_count,
        session_subdirs_count=session_subdirs_count,
        warnings=warnings,
    )


def _normalise_entries(entries: list[str]) -> list[str]:
    """Return zip entries with empty entries dropped.

    The submission contract places ``solution.patch`` and the
    ``transcripts/`` directory at the zip's root with no wrapping
    directory; the per-submission staging directory is created by
    the validate stage on extraction. This helper drops empty
    entries and returns the rest unchanged for downstream layout
    checks.
    """
    return [entry for entry in entries if entry]


def _require_entry(rooted: list[str], name: str, zip_path: Path) -> None:
    """Raise when a required top-level entry is absent from the zip."""
    if name in rooted:
        return
    raise SubmissionFormatError(
        f"validate: required entry {name!r} missing from {zip_path.name}"
    )


def _validate_transcripts(
    rooted: list[str],
    zip_path: Path,
) -> tuple[int, int, list[str]]:
    """Confirm the transcripts directory matches the per-session shape.

    Top-level entries inside ``transcripts/`` are either main
    ``<sessionId>.jsonl`` files or ``<sessionId>/`` subdirectories
    whose name matches a top-level main file. Inside each
    subdirectory only ``subagents/`` and ``tool-results/`` are
    accepted; ``subagents/`` may only hold ``agent-<id>.jsonl``
    files, ``tool-results/`` may hold any file. Sessions with no
    subagent dispatches and no cached tool results have no
    subdirectory.

    Returns:
        Tuple ``(transcripts_count, session_subdirs_count,
        warnings)``. ``transcripts_count`` is the number of
        top-level ``*.jsonl`` files; ``session_subdirs_count`` is
        the number of ``<sessionId>/`` subdirectories; ``warnings``
        accumulates any non-fatal observations (currently empty).

    Raises:
        SubmissionFormatError: When an entry violates the shape
            rules (non-jsonl at the top level, unexpected
            subdirectory under a session directory, malformed
            subagent filename, sub-subdirectory under
            ``subagents/`` or ``tool-results/``, orphan session
            subdirectory with no matching top-level file, or no
            top-level ``.jsonl`` files at all).
    """
    prefix = f"{TRANSCRIPTS_DIRNAME}/"
    main_jsonls: set[str] = set()
    session_subdirs: set[str] = set()
    warnings: list[str] = []
    has_dir = False
    for entry in rooted:
        if entry == TRANSCRIPTS_DIRNAME or entry == prefix:
            has_dir = True
            continue
        if not entry.startswith(prefix):
            continue
        has_dir = True
        relative = entry[len(prefix):]
        if not relative:
            continue
        is_dir_marker = relative.endswith("/")
        rel = relative.rstrip("/")
        if not rel:
            continue
        parts = rel.split("/")
        if len(parts) == 1:
            _classify_top_level(parts[0], is_dir_marker, main_jsonls, session_subdirs, zip_path)
        elif len(parts) == 2:
            _classify_session_child(parts[0], parts[1], is_dir_marker, session_subdirs, zip_path)
        elif len(parts) == 3:
            _classify_session_grandchild(
                parts[0], parts[1], parts[2], is_dir_marker, session_subdirs, zip_path
            )
        else:
            raise SubmissionFormatError(
                f"validate: unexpected deep nesting under transcripts/ in "
                f"{zip_path.name}: {relative!r}"
            )
    if not has_dir:
        raise SubmissionFormatError(
            f"validate: required directory {TRANSCRIPTS_DIRNAME}/ missing "
            f"from {zip_path.name}"
        )
    if not main_jsonls:
        raise SubmissionFormatError(
            f"validate: transcripts/ contains no top-level *.jsonl files in "
            f"{zip_path.name}; at least one main session transcript is required"
        )
    orphans = sorted(session_subdirs - main_jsonls)
    if orphans:
        raise SubmissionFormatError(
            f"validate: transcripts/ in {zip_path.name} carries session "
            f"subdirectories with no matching <sessionId>.jsonl: {orphans!r}"
        )
    return len(main_jsonls), len(session_subdirs), warnings


def _classify_top_level(
    name: str,
    is_dir_marker: bool,
    main_jsonls: set[str],
    session_subdirs: set[str],
    zip_path: Path,
) -> None:
    """Record a top-level entry under ``transcripts/`` as a main file or session subdir."""
    if is_dir_marker:
        session_subdirs.add(name)
        return
    if not name.endswith(JSONL_SUFFIX):
        raise SubmissionFormatError(
            f"validate: non-JSONL file at transcripts/ root in {zip_path.name}: "
            f"{name!r}"
        )
    main_jsonls.add(name[: -len(JSONL_SUFFIX)])


def _classify_session_child(
    session_id: str,
    child: str,
    is_dir_marker: bool,
    session_subdirs: set[str],
    zip_path: Path,
) -> None:
    """Validate an entry of the form ``transcripts/<sessionId>/<child>``.

    The only well-formed direct children of a session subdirectory
    are the ``subagents/`` and ``tool-results/`` subdirectory
    markers; stray files at the session root are rejected.
    """
    session_subdirs.add(session_id)
    if not is_dir_marker:
        raise SubmissionFormatError(
            f"validate: stray file directly under transcripts/{session_id}/ in "
            f"{zip_path.name}: {child!r}; per-session content lives under "
            f"subagents/ or tool-results/"
        )
    if child not in ALLOWED_SESSION_SUBDIRS:
        raise SubmissionFormatError(
            f"validate: unexpected subdirectory under transcripts/{session_id}/ "
            f"in {zip_path.name}: {child!r}; only "
            f"{sorted(ALLOWED_SESSION_SUBDIRS)} are permitted"
        )


def _classify_session_grandchild(
    session_id: str,
    bucket: str,
    leaf: str,
    is_dir_marker: bool,
    session_subdirs: set[str],
    zip_path: Path,
) -> None:
    """Validate an entry of the form ``transcripts/<sessionId>/<bucket>/<leaf>``.

    Inside ``subagents/``, leaves must be ``agent-<id>.jsonl``
    files; inside ``tool-results/``, any filename is permitted.
    Sub-subdirectories under either bucket are rejected.
    """
    session_subdirs.add(session_id)
    if bucket not in ALLOWED_SESSION_SUBDIRS:
        raise SubmissionFormatError(
            f"validate: unexpected nesting transcripts/{session_id}/{bucket}/ "
            f"in {zip_path.name}; only {sorted(ALLOWED_SESSION_SUBDIRS)} are "
            f"permitted under a session subdirectory"
        )
    if is_dir_marker:
        raise SubmissionFormatError(
            f"validate: unexpected sub-subdirectory under "
            f"transcripts/{session_id}/{bucket}/ in {zip_path.name}: {leaf!r}"
        )
    if bucket == SUBAGENTS_DIRNAME:
        prefix_ok = leaf.startswith(SUBAGENT_FILENAME_PREFIX)
        suffix_ok = leaf.endswith(JSONL_SUFFIX) or leaf.endswith(SUBAGENT_META_SUFFIX)
        if not (prefix_ok and suffix_ok):
            raise SubmissionFormatError(
                f"validate: unexpected file under "
                f"transcripts/{session_id}/{SUBAGENTS_DIRNAME}/ in "
                f"{zip_path.name}: {leaf!r}; expected "
                f"{SUBAGENT_FILENAME_PREFIX}<id>{JSONL_SUFFIX} or "
                f"{SUBAGENT_FILENAME_PREFIX}<id>{SUBAGENT_META_SUFFIX}"
            )


def _reject_unknown_top_level(rooted: list[str], zip_path: Path) -> None:
    """Raise when the zip carries top-level entries beyond the patch and transcripts.

    The submission contract is exactly two top-level entries:
    ``solution.patch`` and ``transcripts/`` (with its file
    contents). Anything else is unexpected and rejected so the
    submission shape stays disciplined.
    """
    allowed = {PATCH_FILENAME, TRANSCRIPTS_DIRNAME, f"{TRANSCRIPTS_DIRNAME}/"}
    unexpected: list[str] = []
    for entry in rooted:
        head = entry.split("/", 1)[0]
        if head in allowed or entry in allowed:
            continue
        if head == TRANSCRIPTS_DIRNAME:
            continue
        if head == PATCH_FILENAME and entry == PATCH_FILENAME:
            continue
        unexpected.append(entry)
    if unexpected:
        sample = ", ".join(sorted(set(unexpected))[:5])
        raise SubmissionFormatError(
            f"validate: unexpected top-level entries in {zip_path.name}: "
            f"{sample}; only {PATCH_FILENAME} and {TRANSCRIPTS_DIRNAME}/ "
            f"are permitted"
        )


def _extract_to_staging(
    zip_path: Path,
    output_root: Path,
    submission: SubmissionName,
) -> Path:
    """Extract the zip's contents to ``<output-root>/_staging/<manifest_key>/``.

    The destination directory is removed first when it exists so
    the validation is idempotent: a re-validated submission
    overwrites a prior staging copy without leaving stale files.

    Returns:
        The absolute path of the staging directory.

    Raises:
        StageExecutionError: When the destination cannot be
            created or the extraction fails.
    """
    staging_root = output_root / STAGING_DIRNAME
    destination = staging_root / submission.manifest_key
    try:
        staging_root.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            _remove_tree(destination)
        destination.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(destination)
    except OSError as error:
        raise StageExecutionError(
            f"validate: extraction failed for {zip_path.name}: {error}"
        ) from error
    return destination


def _remove_tree(path: Path) -> None:
    """Recursively remove ``path`` and its contents."""
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


if __name__ == "__main__":
    sys.exit(main())
