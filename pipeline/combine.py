#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Combine grader and parser outputs into a single per-submission artifact.

This stage reads the per-participant ``results.json`` (produced by
the grade stage) and ``metrics.json`` (produced by the parse
stage), wraps them with submission identifiers, and writes a
single ``combined.json`` to the same per-participant directory.
The combined artifact is the input to the add-to-dataset stage and
the long-term archival record for one submission.

The wrapper carries identifiers (``participant_id``, ``session``,
``framework``, ``processing_timestamp``) plus a flat ``grading``
block extracted from the grader's results structure, plus the
parser's metrics artifact nested under ``metrics`` without
modification. Downstream consumers reach into
``metrics.session.economic.cost_usd.value`` etc. when they want
specific measurements; the combined artifact does not flatten or
rename any parser-side key.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import resolve_config
from .errors import (
    PipelineError,
    StageExecutionError,
    StageInputError,
)
from .io import compute_checksum, read_json, validate_checksum, write_json
from .manifest import (
    STAGE_COMBINE,
    STAGE_GRADE,
    STAGE_PARSE,
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

RESULTS_FILENAME = "results.json"
METRICS_FILENAME = "metrics.json"
COMBINED_FILENAME = "combined.json"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the combine stage.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` on success, ``1`` on a recovered
        error (missing input, manifest issue), ``2`` on operator
        error (missing flags).
    """
    args = _parse_args(argv)
    try:
        config = resolve_config(
            output_root=args.output_root,
            config_override=args.config,
        )
        submission = parse_submission_name(args.submission_name)
        target_dir = config.output_root / participant_subdir(submission)
        results_path = target_dir / RESULTS_FILENAME
        metrics_path = target_dir / METRICS_FILENAME
        _require_input(results_path, "grade", "results.json")
        _require_input(metrics_path, "parse", "metrics.json")
        manifest = load_manifest(config.output_root)
        _verify_upstream_checksums(manifest, submission, results_path, metrics_path)
        results_payload = read_json(results_path)
        metrics_payload = read_json(metrics_path)
        combined = _build_combined(submission, results_payload, metrics_payload)
        combined_path = target_dir / COMBINED_FILENAME
        write_json(combined, combined_path)
        manifest = add_stage(
            manifest,
            submission.manifest_key,
            STAGE_COMBINE,
            STATUS_SUCCESS,
            input_files=[RESULTS_FILENAME, METRICS_FILENAME],
            output_combined=str(combined_path.relative_to(config.output_root)),
            output_checksum=compute_checksum(combined_path),
        )
        save_manifest(manifest)
    except StageInputError as error:
        print(f"error: combine input missing: {error}", file=sys.stderr)
        return 1
    except StageExecutionError as error:
        print(f"error: combine failed: {error}", file=sys.stderr)
        return 1
    except PipelineError as error:
        print(f"error: pipeline error: {error}", file=sys.stderr)
        return 1
    print(
        f"combined: {submission.manifest_key} "
        f"score {combined['grading']['total']['score']}/"
        f"{combined['grading']['total']['max']}; "
        f"artifact at {combined_path.relative_to(config.output_root)}"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.combine",
        description=(
            "Combine grader and parser outputs into a single "
            "combined.json per submission."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "submission_name",
        help=(
            "Submission manifest key ({PID}_S{1|2}_{apm|speckit}); the grade "
            "and parse stages must have written their outputs to "
            "<output-root>/<PID>/<S{n}>_<framework>/."
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
    return parser.parse_args(argv)


def _require_input(path: Path, upstream_stage: str, name: str) -> None:
    """Raise when an upstream stage's output is missing."""
    if path.is_file():
        return
    raise StageInputError(
        f"combine: {name} not found at {path}; run pipeline.{upstream_stage} first"
    )


def _verify_upstream_checksums(
    manifest: Any,
    submission: SubmissionName,
    results_path: Path,
    metrics_path: Path,
) -> None:
    """Surface a warning when an upstream artifact differs from its manifest checksum.

    A mismatch typically means the file has been edited or a stage
    has been re-run without the manifest being updated; the
    combine stage proceeds either way (the new content is what the
    operator chose to keep) but a stale upstream is worth
    flagging.
    """
    submission_entry = manifest.get(submission.manifest_key)
    if submission_entry is None:
        return
    grade_entry = submission_entry.get_stage(STAGE_GRADE)
    parse_entry = submission_entry.get_stage(STAGE_PARSE)
    if grade_entry is not None:
        expected = grade_entry.fields.get("output_checksum", "")
        if expected and not validate_checksum(results_path, expected):
            print(
                f"warning: results.json checksum differs from manifest entry",
                file=sys.stderr,
            )
    if parse_entry is not None:
        expected = parse_entry.fields.get("output_checksum", "")
        if expected and not validate_checksum(metrics_path, expected):
            print(
                f"warning: metrics.json checksum differs from manifest entry",
                file=sys.stderr,
            )


def _build_combined(
    submission: SubmissionName,
    results_payload: Any,
    metrics_payload: Any,
) -> dict[str, Any]:
    """Assemble the combined-artifact wrapper.

    Identifiers go on the wrapper; the grader's score breakdown is
    flattened into a small ``grading`` block; the parser's metrics
    artifact is nested under ``metrics`` verbatim. The processing
    timestamp is the wall-clock time the combine stage ran; it
    does not match either upstream stage's timestamp.
    """
    grading = _extract_grading(results_payload)
    return {
        "participant_id": submission.pid,
        "session": submission.session,
        "framework": submission.framework,
        "processing_timestamp": datetime.now(timezone.utc).isoformat(),
        "grading": grading,
        "metrics": metrics_payload,
    }


def _extract_grading(results_payload: Any) -> dict[str, Any]:
    """Flatten the grader's nested score structure into the combined wrapper.

    The grader's ``scores`` block carries Python under
    ``scores.python.{baseline,feature,total}`` and C under
    ``scores.c.total``. The combined artifact's ``grading`` block
    surfaces the three rubric categories separately (so analysis
    can compare per-category) plus the overall total computed
    from ``grand_total`` when present, otherwise summed from the
    per-category fields.

    A malformed results payload raises ``StageExecutionError``.
    """
    if not isinstance(results_payload, dict):
        raise StageExecutionError(
            "combine: results.json top level must be an object"
        )
    scores = results_payload.get("scores")
    if not isinstance(scores, dict):
        raise StageExecutionError(
            "combine: results.json missing 'scores' object"
        )
    python = scores.get("python", {}) or {}
    python_baseline = _score_pair(python.get("baseline"), default_max=12)
    python_feature = _score_pair(python.get("feature"), default_max=36)
    c_total = _score_pair(scores.get("c", {}).get("total"), default_max=52)
    grand_total = scores.get("grand_total")
    if isinstance(grand_total, dict):
        total = _score_pair(grand_total, default_max=100)
    else:
        total = {
            "score": (
                python_baseline["score"]
                + python_feature["score"]
                + c_total["score"]
            ),
            "max": (
                python_baseline["max"]
                + python_feature["max"]
                + c_total["max"]
            ),
        }
    return {
        "total": total,
        "python_baseline": python_baseline,
        "python_feature": python_feature,
        "c_replica": c_total,
    }


def _score_pair(value: Any, default_max: int) -> dict[str, int]:
    """Return ``{"score": int, "max": int}`` from a possibly-missing nested score block."""
    if isinstance(value, dict):
        score = value.get("score", 0)
        maximum = value.get("max", default_max)
    else:
        score = 0
        maximum = default_max
    return {"score": int(score), "max": int(maximum)}


if __name__ == "__main__":
    sys.exit(main())
