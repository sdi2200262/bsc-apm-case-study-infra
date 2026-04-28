#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Run the grader on a validated submission and promote the results JSON.

This stage takes the unpacked submission from
``<output-root>/_staging/<manifest_key>/`` (produced by the
validate stage), invokes ``python -m grader`` against the
submission's ``solution.patch``, the participant's
``eclass-mcp-server`` checkout, and the testing-environment
install, and copies the resulting ``results_<patch_stem>.json``
into the per-participant directory at
``<output-root>/<PID>/<S{n}>_<framework>/results.json``. The
grade-stage entry in the manifest carries the patch checksum, the
output checksum, the score breakdown, and the timestamps.

The grader writes its own ``results_*.json`` and ``results_*.txt``
to the parent directory of the eclass checkout. The pipeline
picks up the JSON from that location and promotes it; the TXT is
left in place for ad-hoc grader review and is not part of the
dataset.

The testing environment must be up (its endpoints reachable and
its reset script available) before this stage executes; the
grader's pre-flight catches the absence and reports a clear
error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import resolve_config, require_path
from .errors import (
    PipelineError,
    StageExecutionError,
    StageInputError,
)
from .io import compute_checksum
from .manifest import (
    STAGE_GRADE,
    STATUS_SUCCESS,
    add_stage,
    load_manifest,
    save_manifest,
)
from .submissions import (
    SubmissionName,
    parse_submission_name,
    participant_subdir,
)

PATCH_FILENAME = "solution.patch"
RESULTS_FILENAME = "results.json"
STAGING_DIRNAME = "_staging"
GRADER_PACKAGE_NAME = "grader"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the grade stage.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` on success, ``1`` on a recovered
        error (missing input, grader failure, manifest issue),
        ``2`` on operator error (missing flags, missing paths).
    """
    args = _parse_args(argv)
    try:
        config = resolve_config(
            output_root=args.output_root,
            config_override=args.config,
            grader_root_flag=args.grader_root,
            eclass_root_flag=args.eclass_root,
            mock_root_flag=args.mock_root,
        )
        grader_root = require_path(config.grader_root, "grader root", "grade")
        eclass_root = require_path(config.eclass_root, "eclass root", "grade")
        mock_root = require_path(config.mock_root, "mock root", "grade")
        submission = parse_submission_name(args.submission_name)
        patch_path = _require_validated_patch(config.output_root, submission)
        grader_package_dir = grader_root / "__init__.py"
        if not grader_package_dir.exists():
            raise StageInputError(
                f"grade: grader package not found at {grader_root}"
            )
        target_dir = config.output_root / participant_subdir(submission)
        target_dir.mkdir(parents=True, exist_ok=True)
        results_target = target_dir / RESULTS_FILENAME
        _invoke_grader(grader_root, patch_path, eclass_root, mock_root)
        results_source = _locate_results(eclass_root, patch_path)
        shutil.copyfile(results_source, results_target)
        breakdown = _read_score_breakdown(results_target)
        manifest = load_manifest(config.output_root)
        manifest = add_stage(
            manifest,
            submission.manifest_key,
            STAGE_GRADE,
            STATUS_SUCCESS,
            input_patch=PATCH_FILENAME,
            input_checksum=compute_checksum(patch_path),
            output_results=str(results_target.relative_to(config.output_root)),
            output_checksum=compute_checksum(results_target),
            score=breakdown["score"],
            score_breakdown=breakdown["breakdown"],
        )
        save_manifest(manifest)
    except StageInputError as error:
        print(f"error: grade input missing: {error}", file=sys.stderr)
        return 1
    except StageExecutionError as error:
        print(f"error: grade failed: {error}", file=sys.stderr)
        return 1
    except PipelineError as error:
        print(f"error: pipeline error: {error}", file=sys.stderr)
        return 1
    print(
        f"graded: {submission.manifest_key} "
        f"score {breakdown['score']}; "
        f"results at {results_target.relative_to(config.output_root)}"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.grade",
        description=(
            "Apply a validated submission's patch and run the grader; "
            "promote the results JSON to the per-participant directory."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "submission_name",
        help=(
            "Submission manifest key ({PID}_S{1|2}_{apm|speckit}); the "
            "validate stage must have unpacked this submission to "
            "<output-root>/_staging/<manifest_key>/."
        ),
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
        "--grader-root",
        type=Path,
        default=None,
        help="Path to the grader directory (overrides pipeline.yaml).",
    )
    parser.add_argument(
        "--eclass-root",
        type=Path,
        default=None,
        help="Path to the eclass-mcp-server checkout (overrides pipeline.yaml).",
    )
    parser.add_argument(
        "--mock-root",
        type=Path,
        default=None,
        help="Path to the testing-environment install (overrides pipeline.yaml).",
    )
    return parser.parse_args(argv)


def _require_validated_patch(
    output_root: Path,
    submission: SubmissionName,
) -> Path:
    """Return the staged ``solution.patch`` path for a submission, or raise."""
    staging = output_root / STAGING_DIRNAME / submission.manifest_key
    patch = staging / PATCH_FILENAME
    if not patch.is_file():
        raise StageInputError(
            f"grade: staged patch not found at {patch}; run pipeline.validate first"
        )
    return patch


def _invoke_grader(
    grader_root: Path,
    patch_path: Path,
    eclass_root: Path,
    mock_root: Path,
) -> None:
    """Run the grader subprocess on the patch.

    The grader writes ``results_<patch_stem>.json`` and a sibling
    ``.txt`` to ``eclass_root.parent``; this helper does not
    relocate those files. ``stdin`` is closed to prevent the
    grader from hanging on prompts when invoked
    non-interactively.

    Args:
        grader_root: Path to the ``grader`` package directory.
            The grader is invoked as ``python -m grader`` with the
            package's parent on the working directory.
        patch_path: Path to the participant's solution patch.
        eclass_root: Path to the eclass-mcp-server checkout the
            patch applies to.
        mock_root: Path to the testing-environment install whose
            endpoints the grader probes and whose reset script
            runs between phases.
    """
    cmd = [
        sys.executable,
        "-m",
        GRADER_PACKAGE_NAME,
        str(patch_path),
        "--eclass-dir",
        str(eclass_root),
        "--mock-root",
        str(mock_root),
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=grader_root.parent,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise StageExecutionError(
            f"grade: cannot invoke grader package at {grader_root}: {error}"
        ) from error
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "").strip().splitlines()[-1:] or [""]
        raise StageExecutionError(
            f"grade: grader exited {completed.returncode}: {stderr_tail[0]}"
        )


def _locate_results(eclass_root: Path, patch_path: Path) -> Path:
    """Return the path the grader wrote its results JSON to."""
    candidate = eclass_root.parent / f"results_{patch_path.stem}.json"
    if not candidate.is_file():
        raise StageExecutionError(
            f"grade: grader did not produce expected results JSON at {candidate}"
        )
    return candidate


def _read_score_breakdown(results_path: Path) -> dict[str, Any]:
    """Return ``{"score": "<n>/<m>", "breakdown": {...}}`` from a results JSON.

    The grader's results structure groups Python and C scores under
    nested categories; this helper flattens the breakdown into the
    three rubric categories the dataset row reports
    (``python_baseline``, ``python_feature``, ``c_replica``) and
    computes the overall score string. A malformed results file
    raises ``StageExecutionError``.
    """
    try:
        with results_path.open("r", encoding="utf-8") as source:
            data = json.load(source)
    except json.JSONDecodeError as error:
        raise StageExecutionError(
            f"grade: results JSON at {results_path} is malformed: {error}"
        ) from error
    scores = data.get("scores", {})
    python = scores.get("python", {})
    python_baseline = python.get("baseline", {})
    python_feature = python.get("feature", {})
    c_total = scores.get("c", {}).get("total", {})
    grand_total = scores.get("grand_total", {})
    if grand_total:
        score = grand_total.get("score", 0)
        max_score = grand_total.get("max", 100)
    else:
        score = (
            python_baseline.get("score", 0)
            + python_feature.get("score", 0)
            + c_total.get("score", 0)
        )
        max_score = (
            python_baseline.get("max", 12)
            + python_feature.get("max", 36)
            + c_total.get("max", 52)
        )
    return {
        "score": f"{score}/{max_score}",
        "breakdown": {
            "python_baseline": (
                f"{python_baseline.get('score', 0)}/"
                f"{python_baseline.get('max', 12)}"
            ),
            "python_feature": (
                f"{python_feature.get('score', 0)}/"
                f"{python_feature.get('max', 36)}"
            ),
            "c_replica": (
                f"{c_total.get('score', 0)}/{c_total.get('max', 52)}"
            ),
        },
    }


if __name__ == "__main__":
    sys.exit(main())
