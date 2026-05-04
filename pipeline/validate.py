#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Validate a participant submission zip and unpack it to the dataset staging area.

The submission zip contract:

* Filename matches ``{PID}_S{1|2}_{apm|speckit}.zip``.
* The zip's root contains exactly two entries: ``solution.patch``
  (the patch the grader will apply against baseline) and
  ``transcripts/`` (a flat directory of one or more
  ``<sessionId>.jsonl`` files copied from
  ``~/.claude/projects/<dashed-cwd>/``). Participants produce this
  layout by following the guide's wrap-up step: from inside the
  workspace directory, ``zip -r <name>.zip solution.patch
  transcripts/``.
* No other files or directories at the zip's root.
* Inside ``transcripts/``: every entry is a ``*.jsonl`` file at
  the top level, no subdirectories. The guide instructs
  participants to omit the sibling ``<sessionId>/`` directories
  (``subagents/`` and ``tool-results/`` content Claude Code writes
  alongside the JSONL files); the validate stage rejects them so
  their content stays out of the dataset's measurement scope.

The validate stage:

1. Parses the zip filename into a ``SubmissionName``.
2. Inspects the zip's contents without extracting: confirms the
   exact two-entry structure, the patch presence, and the
   transcripts contents.
3. Extracts to ``<output-root>/_staging/<manifest_key>/`` when
   the zip layout is well-formed.
4. Records the validate stage entry in
   ``<output-root>/pipeline_manifest.json`` with the input zip
   checksum, the extracted staging path, the transcript file
   count, and any non-fatal warnings.

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
        f"{'s' if layout.transcripts_count != 1 else ''}); "
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

    def __init__(self, transcripts_count: int, warnings: list[str]) -> None:
        self.transcripts_count = transcripts_count
        self.warnings = warnings


def _validate_layout(zip_path: Path, submission: SubmissionName) -> _Layout:
    """Inspect the zip's contents without extracting and confirm the contract.

    Args:
        zip_path: Path to the submission zip.
        submission: Parsed submission identifiers.

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
    transcripts_count, warnings = _validate_transcripts(rooted, zip_path)
    _reject_unknown_top_level(rooted, zip_path)
    return _Layout(transcripts_count=transcripts_count, warnings=warnings)


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
) -> tuple[int, list[str]]:
    """Confirm the transcripts directory contains only ``*.jsonl`` files.

    Returns the number of JSONL files found and a list of
    non-fatal warnings (empty-file warnings, future-extension
    warnings if any). Non-jsonl files inside ``transcripts/`` are
    fatal.
    """
    prefix = f"{TRANSCRIPTS_DIRNAME}/"
    count = 0
    warnings: list[str] = []
    has_dir = False
    for entry in rooted:
        if entry == prefix or entry == TRANSCRIPTS_DIRNAME:
            has_dir = True
            continue
        if not entry.startswith(prefix):
            continue
        has_dir = True
        relative = entry[len(prefix):]
        if relative.endswith("/"):
            raise SubmissionFormatError(
                f"validate: nested directory under transcripts/ in "
                f"{zip_path.name}: {relative!r}; the parser does not consume "
                f"subagent or tool-result subdirectories"
            )
        if "/" in relative:
            raise SubmissionFormatError(
                f"validate: nested file under transcripts/ in {zip_path.name}: "
                f"{relative!r}; transcripts must be flat"
            )
        if not relative.endswith(JSONL_SUFFIX):
            raise SubmissionFormatError(
                f"validate: non-JSONL file in transcripts/ of "
                f"{zip_path.name}: {relative!r}"
            )
        count += 1
    if not has_dir:
        raise SubmissionFormatError(
            f"validate: required directory {TRANSCRIPTS_DIRNAME}/ missing "
            f"from {zip_path.name}"
        )
    if count == 0:
        raise SubmissionFormatError(
            f"validate: transcripts/ directory empty in {zip_path.name}; "
            f"at least one .jsonl file is required"
        )
    return count, warnings


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
