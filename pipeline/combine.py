#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
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

When the per-participant directory carries a ``metrics_notes.yaml``
sidecar, its entry list is embedded under ``metrics_notes``. The
sidecar is hand-curated through ``python -m cc_chat_parser.notes``
and survives parser re-runs because the parser does not touch it.
The manifest's combine entry records the sidecar's checksum when
present so a downstream reader can detect edits between combine
runs.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

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
NOTES_FILENAME = "metrics_notes.yaml"


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
        notes_path = target_dir / NOTES_FILENAME
        notes_payload = _load_metrics_notes(notes_path) if notes_path.is_file() else None
        combined = _build_combined(
            submission, results_payload, metrics_payload, notes_payload
        )
        combined_path = target_dir / COMBINED_FILENAME
        write_json(combined, combined_path)
        manifest_fields: dict[str, Any] = {
            "input_files": [RESULTS_FILENAME, METRICS_FILENAME],
            "output_combined": str(combined_path.relative_to(config.output_root)),
            "output_checksum": compute_checksum(combined_path),
        }
        if notes_payload is not None:
            manifest_fields["notes_sidecar"] = str(
                notes_path.relative_to(config.output_root)
            )
            manifest_fields["notes_sidecar_checksum"] = compute_checksum(notes_path)
            manifest_fields["notes_count"] = len(notes_payload)
        manifest = add_stage(
            manifest,
            submission.manifest_key,
            STAGE_COMBINE,
            STATUS_SUCCESS,
            **manifest_fields,
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
    """Raise when an upstream artifact differs from its manifest checksum.

    A mismatch means the on-disk artifact has been edited or
    overwritten without the manifest being refreshed. The operator
    must re-run the upstream stage (which rewrites the manifest's
    recorded checksum) before combine can proceed, otherwise the
    combined artifact would record provenance that does not match
    the bytes it consumed.
    """
    submission_entry = manifest.get(submission.manifest_key)
    if submission_entry is None:
        return
    grade_entry = submission_entry.get_stage(STAGE_GRADE)
    parse_entry = submission_entry.get_stage(STAGE_PARSE)
    if grade_entry is not None:
        expected = grade_entry.fields.get("output_checksum", "")
        if expected and not validate_checksum(results_path, expected):
            raise StageExecutionError(
                f"combine: {submission.manifest_key}: {results_path.name} "
                f"checksum differs from the manifest entry recorded by the "
                f"grade stage; re-run pipeline.grade to refresh it"
            )
    if parse_entry is not None:
        expected = parse_entry.fields.get("output_checksum", "")
        if expected and not validate_checksum(metrics_path, expected):
            raise StageExecutionError(
                f"combine: {submission.manifest_key}: {metrics_path.name} "
                f"checksum differs from the manifest entry recorded by the "
                f"parse stage; re-run pipeline.parse to refresh it"
            )


def _build_combined(
    submission: SubmissionName,
    results_payload: Any,
    metrics_payload: Any,
    notes_payload: list[dict[str, str]] | None,
) -> dict[str, Any]:
    """Assemble the combined-artifact wrapper.

    Identifiers go on the wrapper; the grader's score breakdown is
    flattened into a small ``grading`` block; the parser's metrics
    artifact is nested under ``metrics`` verbatim. The processing
    timestamp is the wall-clock time the combine stage ran; it does
    not match either upstream stage's timestamp.

    When ``notes_payload`` is non-``None``, its entry list is
    embedded under ``metrics_notes``. The key is omitted entirely
    when no sidecar is present so absence is distinguishable from an
    empty list, and downstream readers can branch on the field's
    presence.
    """
    grading = _extract_grading(results_payload, submission.manifest_key)
    combined: dict[str, Any] = {
        "participant_id": submission.pid,
        "session": submission.session,
        "framework": submission.framework,
        "processing_timestamp": datetime.now(timezone.utc).isoformat(),
        "grading": grading,
        "metrics": metrics_payload,
    }
    if notes_payload is not None:
        combined["metrics_notes"] = notes_payload
    return combined


def _load_metrics_notes(path: Path) -> list[dict[str, str]]:
    """Read the metrics-notes sidecar and return its entry list.

    The sidecar's canonical writer is ``cc_chat_parser.notes``;
    pipeline.combine reads the YAML directly to keep the pipeline
    package free of in-process dependencies on the parser package.
    Each entry must carry a non-empty ``path`` string and a non-empty
    ``note`` string.

    Args:
        path: Path to ``metrics_notes.yaml``.

    Returns:
        The ordered entry list as ``[{"path": ..., "note": ...}, ...]``.

    Raises:
        StageExecutionError: When the sidecar is malformed.
    """
    with path.open("r", encoding="utf-8") as source:
        try:
            payload = yaml.safe_load(source) or {}
        except yaml.YAMLError as error:
            raise StageExecutionError(
                f"combine: notes sidecar at {path} is not valid YAML: {error}"
            ) from error
    if not isinstance(payload, dict):
        raise StageExecutionError(
            f"combine: notes sidecar at {path} top level must be a YAML mapping"
        )
    notes = payload.get("notes", [])
    if notes is None:
        return []
    if not isinstance(notes, list):
        raise StageExecutionError(
            f"combine: notes sidecar at {path} 'notes' must be a list"
        )
    out: list[dict[str, str]] = []
    for index, entry in enumerate(notes):
        if not isinstance(entry, dict):
            raise StageExecutionError(
                f"combine: notes sidecar at {path} entry {index} must be a mapping"
            )
        path_value = entry.get("path")
        note_value = entry.get("note")
        if not isinstance(path_value, str) or not path_value:
            raise StageExecutionError(
                f"combine: notes sidecar at {path} entry {index} 'path' "
                f"must be a non-empty string"
            )
        if not isinstance(note_value, str) or not note_value.strip():
            raise StageExecutionError(
                f"combine: notes sidecar at {path} entry {index} 'note' "
                f"must be a non-empty string"
            )
        out.append({"path": path_value, "note": note_value.rstrip()})
    return out


def _extract_grading(results_payload: Any, manifest_key: str) -> dict[str, Any]:
    """Flatten the grader's nested score structure into the combined wrapper.

    The grader's ``scores`` block carries Python under
    ``scores.python.{baseline,feature}`` and C under
    ``scores.c.total``, plus an overall ``scores.grand_total``.
    Every field is required; a malformed results payload raises
    ``StageExecutionError`` naming the submission and the missing
    field path.
    """
    if not isinstance(results_payload, dict):
        raise StageExecutionError(
            f"combine: {manifest_key}: results.json top level must be an object"
        )
    try:
        scores = results_payload["scores"]
        python = scores["python"]
        python_baseline = _score_pair(
            python["baseline"], manifest_key, "scores.python.baseline"
        )
        python_feature = _score_pair(
            python["feature"], manifest_key, "scores.python.feature"
        )
        c_total = _score_pair(
            scores["c"]["total"], manifest_key, "scores.c.total"
        )
        total = _score_pair(
            scores["grand_total"], manifest_key, "scores.grand_total"
        )
    except KeyError as error:
        raise StageExecutionError(
            f"combine: {manifest_key}: results.json missing required field "
            f"{error}"
        ) from error
    except TypeError as error:
        raise StageExecutionError(
            f"combine: {manifest_key}: results.json has unexpected structure: "
            f"{error}"
        ) from error
    return {
        "total": total,
        "python_baseline": python_baseline,
        "python_feature": python_feature,
        "c_replica": c_total,
    }


def _score_pair(value: Any, manifest_key: str, field_path: str) -> dict[str, int]:
    """Return ``{"score": int, "max": int}`` from a score block.

    Raises ``StageExecutionError`` when ``value`` is not an object or
    is missing either required key, naming the submission and the
    field path so the operator can locate the malformation.
    """
    if not isinstance(value, dict):
        raise StageExecutionError(
            f"combine: {manifest_key}: {field_path} must be an object, "
            f"got {type(value).__name__}"
        )
    if "score" not in value:
        raise StageExecutionError(
            f"combine: {manifest_key}: {field_path}.score is missing"
        )
    if "max" not in value:
        raise StageExecutionError(
            f"combine: {manifest_key}: {field_path}.max is missing"
        )
    return {"score": int(value["score"]), "max": int(value["max"])}


if __name__ == "__main__":
    sys.exit(main())
