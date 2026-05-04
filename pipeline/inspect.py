#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Render the manifest history for one submission.

This is the operator's audit view for a single submission: which
stages have run, when, with what status, and which artifacts each
stage produced. It is the pipeline-side counterpart to the
parser's ``cc_chat_parser.inspect`` (which renders an emitted
metrics artifact) and the grader's ``inspect.py`` (which renders
an emitted grading results JSON).

Two output modes:

* Default: a human-readable rendering with one block per stage
  showing timestamp, status, input and output paths, checksums,
  and stage-specific fields (score breakdown for grade,
  framework + sanitised file count for parse, dataset row number
  for add-to-dataset). Stages that have not yet run are listed
  with a placeholder marker.
* ``--json``: the same content as a single JSON object, suitable
  for piping into downstream tools.

The command exits non-zero only when the submission is unknown to
the manifest; a partially-processed submission is a normal state
and prints what is known.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import resolve_config
from .errors import (
    ManifestError,
    PipelineError,
)
from .manifest import (
    KNOWN_STAGES,
    STATUS_ERROR,
    STATUS_SUCCESS,
    STATUS_WARNING,
    StageEntry,
    SubmissionEntry,
    load_manifest,
)
from .submissions import parse_submission_name


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for inspect.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` when the manifest entry exists,
        ``1`` when the submission is unknown to the manifest,
        ``2`` on operator error.
    """
    args = _parse_args(argv)
    try:
        config = resolve_config(
            output_root=args.output_root,
            config_override=args.config,
        )
        submission = parse_submission_name(args.submission_name)
        manifest = load_manifest(config.output_root)
        submission_entry = manifest.get(submission.manifest_key)
        if submission_entry is None:
            print(
                f"error: submission {submission.manifest_key} not found in "
                f"manifest at {manifest.path}",
                file=sys.stderr,
            )
            return 1
    except ManifestError as error:
        print(f"error: manifest issue: {error}", file=sys.stderr)
        return 1
    except PipelineError as error:
        print(f"error: pipeline error: {error}", file=sys.stderr)
        return 1
    if args.json:
        _emit_json(submission.manifest_key, submission_entry)
    else:
        _emit_text(submission.manifest_key, submission_entry, manifest.path)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.inspect",
        description=(
            "Render the manifest history for one submission as text or "
            "as JSON."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "submission_name",
        help="Submission manifest key ({PID}_S{1|2}_{apm|speckit}).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Dataset output root directory.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional pipeline.yaml path; defaults to <output-root>/pipeline.yaml.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the manifest entry as JSON instead of text.",
    )
    return parser.parse_args(argv)


def _emit_json(manifest_key: str, submission_entry: SubmissionEntry) -> None:
    """Write the submission entry as a JSON object to stdout."""
    payload = {
        "manifest_key": manifest_key,
        "stages": submission_entry.to_dict(),
    }
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _emit_text(
    manifest_key: str,
    submission_entry: SubmissionEntry,
    manifest_path: Path,
) -> None:
    """Render the submission entry as a human-readable summary."""
    rule = "=" * 70
    print(rule)
    print(f"  SUBMISSION: {manifest_key}")
    print(rule)
    print(f"  manifest:   {manifest_path}")
    print()
    executed_count = 0
    failed_count = 0
    for stage_name in KNOWN_STAGES:
        entry = submission_entry.get_stage(stage_name)
        if entry is None:
            print(f"  [ ] {stage_name}: not executed")
            print()
            continue
        executed_count += 1
        if entry.status == STATUS_ERROR:
            failed_count += 1
        _render_stage_block(stage_name, entry)
    print(rule)
    print("  SUMMARY")
    print(rule)
    print(
        f"  stages executed: {executed_count}/{len(KNOWN_STAGES)}; "
        f"failures: {failed_count}"
    )


def _render_stage_block(stage_name: str, entry: StageEntry) -> None:
    """Render one stage's block in the text output."""
    indicator = _status_indicator(entry.status)
    print(f"  [{indicator}] {stage_name}: {entry.status}")
    if entry.timestamp:
        print(f"      timestamp:        {entry.timestamp}")
    for key, value in sorted(entry.fields.items()):
        _render_field(key, value)
    print()


def _render_field(key: str, value: Any) -> None:
    """Render one stage-specific field with consistent indent."""
    if isinstance(value, list):
        if not value:
            print(f"      {key}:")
            return
        print(f"      {key}:")
        for item in value:
            print(f"        - {item}")
        return
    if isinstance(value, dict):
        print(f"      {key}:")
        for sub_key, sub_value in value.items():
            print(f"        {sub_key}: {sub_value}")
        return
    text = str(value)
    if key.endswith("_checksum") and len(text) > 24:
        text = f"{text[:24]}..."
    print(f"      {key}: {text}")


def _status_indicator(status: str) -> str:
    """Return a single-character status indicator."""
    if status == STATUS_SUCCESS:
        return "+"
    if status == STATUS_WARNING:
        return "!"
    if status == STATUS_ERROR:
        return "x"
    return "?"


if __name__ == "__main__":
    sys.exit(main())
