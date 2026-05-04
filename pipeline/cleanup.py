#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Remove a fully-processed submission's staging copy.

Once every stage of the pipeline has succeeded for a submission,
its raw transcripts and patch under ``_staging/<manifest_key>/``
are no longer needed: the per-participant directory under
``<output-root>/<PID>/<S{n}>_<framework>/`` carries the durable
artifacts (results, metrics, combined, sanitised transcripts) and
the manifest carries the audit trail. This stage removes the
staging copy.

The check is strict: cleanup runs only when every one of the five
pipeline stages has a recorded ``success`` status in the manifest.
Anything else (missing stage, warning, error) leaves the staging
copy in place so a re-run can pick up where the failure happened.
The ``--force`` flag overrides the check for the rare case where
an operator decides a partial run is permanent.

Cleanup does not write the manifest. The submission's manifest
entry stays intact so the audit trail survives the staging
deletion.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import resolve_config
from .errors import (
    PipelineError,
    StageInputError,
)
from .manifest import (
    KNOWN_STAGES,
    STATUS_SUCCESS,
    SubmissionEntry,
    load_manifest,
)
from .submissions import parse_submission_name

STAGING_DIRNAME = "_staging"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for cleanup.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` on successful removal, ``1`` when
        the submission is not yet fully processed (without
        ``--force``) or the staging directory is missing,
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
            raise StageInputError(
                f"cleanup: submission {submission.manifest_key} not found in "
                f"manifest at {manifest.path}"
            )
        staging_dir = (
            config.output_root / STAGING_DIRNAME / submission.manifest_key
        )
        if not staging_dir.is_dir():
            raise StageInputError(
                f"cleanup: staging directory not found at {staging_dir}; "
                f"submission may already be cleaned"
            )
        if not args.force:
            missing = _stages_short_of_success(submission_entry)
            if missing:
                print(
                    f"error: cleanup refused; the following stages have not "
                    f"recorded success for {submission.manifest_key}: "
                    f"{', '.join(missing)}",
                    file=sys.stderr,
                )
                print(
                    "       run those stages to completion or pass --force "
                    "to remove staging anyway",
                    file=sys.stderr,
                )
                return 1
    except StageInputError as error:
        print(f"error: cleanup input missing: {error}", file=sys.stderr)
        return 1
    except PipelineError as error:
        print(f"error: pipeline error: {error}", file=sys.stderr)
        return 1
    _remove_tree(staging_dir)
    print(
        f"cleaned: {submission.manifest_key} "
        f"({staging_dir.relative_to(config.output_root)} removed)"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.cleanup",
        description=(
            "Remove a submission's _staging/ directory after every "
            "pipeline stage has recorded success."
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
        "--force",
        action="store_true",
        help=(
            "Remove the staging directory even when one or more stages "
            "have not recorded success; intended for manual cleanup of "
            "abandoned submissions."
        ),
    )
    return parser.parse_args(argv)


def _stages_short_of_success(submission_entry: SubmissionEntry) -> list[str]:
    """Return the names of stages that do not have a success entry."""
    short: list[str] = []
    for stage in KNOWN_STAGES:
        entry = submission_entry.get_stage(stage)
        if entry is None or entry.status != STATUS_SUCCESS:
            short.append(stage)
    return short


def _remove_tree(path: Path) -> None:
    """Recursively remove a directory and its contents."""
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


if __name__ == "__main__":
    sys.exit(main())
