#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Append one row to the aggregated dataset CSV.

This stage reads the per-submission ``combined.json`` (produced by
the combine stage) and appends one flat row to
``<output-root>/dataset.csv``. The CSV header is written on first
append; subsequent appends append rows only.

Column families, in order: identifiers, session metadata,
grading, economic (session scope), time (session scope), user
input (session scope), reliability, supplementary, diagnostics.
Phase-scope and role-scope decompositions stay in
``combined.json`` for downstream analysis; the CSV is the
session-scope-only summary.

Bucket-share dicts are flattened into per-bucket columns
(``turn_prompts_share_protocol`` etc.) so downstream statistics
software does not have to parse JSON inside a CSV cell.
``invariant_failures`` is the count of failed invariant checks;
the failure names live in ``combined.json.metrics.diagnostics``.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from .config import resolve_config
from .errors import (
    PipelineError,
    StageExecutionError,
    StageInputError,
)
from .io import compute_checksum, read_json, validate_checksum
from .manifest import (
    STAGE_ADD_TO_DATASET,
    STAGE_COMBINE,
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

DATASET_FILENAME = "dataset.csv"
COMBINED_FILENAME = "combined.json"

CSV_COLUMNS: tuple[str, ...] = (
    # Identifiers
    "participant_id",
    "session",
    "framework",
    "processing_timestamp",
    # Session metadata
    "cc_version",
    "model",
    "model_drift",
    "entrypoint",
    "auth_mode_indicator",
    "service_tier",
    "session_start_timestamp",
    "session_end_timestamp",
    # Grading
    "total_score",
    "max_score",
    "python_baseline_score",
    "python_feature_score",
    "c_replica_score",
    # Economic (session scope)
    "cost_usd",
    "total_input_tokens",
    "total_output_tokens",
    "total_cache_read_tokens",
    "total_cache_5m_tokens",
    "total_cache_1h_tokens",
    "total_prompt_tokens",
    "main_input_tokens",
    "main_output_tokens",
    "delegated_input_tokens",
    "delegated_output_tokens",
    # Time (session scope)
    "duration",
    "turn_time",
    "turn_time_solo",
    "turn_time_concurrent",
    "inter_turn_time",
    "turn_count",
    "mean_turn_duration",
    "turn_duration_p50",
    "turn_duration_p95",
    "turn_duration_stdev",
    # User input (session scope)
    "turn_prompt_count",
    "steer_delivered_count",
    "steer_abandoned_count",
    "steer_attempted_count",
    "turn_prompts_share_protocol",
    "turn_prompts_share_short",
    "turn_prompts_share_standard",
    "all_inputs_share_protocol",
    "all_inputs_share_short",
    "all_inputs_share_standard",
    # Reliability
    "tool_success_rate",
    # Supplementary
    "subagent_count",
    "subagent_tool_count",
    "reasoning_token_share",
    # Diagnostics
    "compaction_events_total",
    "cost_excludes_compaction_synthesis",
    "synthetic_assistant_records_excluded",
    "agent_dispatches_without_usage",
    "entrypoint_valid",
    "auth_mode_valid",
    "invariant_failures",
)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the add-to-dataset stage.

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
        combined_path = target_dir / COMBINED_FILENAME
        if not combined_path.is_file():
            raise StageInputError(
                f"add_to_dataset: {COMBINED_FILENAME} not found at "
                f"{combined_path}; run pipeline.combine first"
            )
        manifest = load_manifest(config.output_root)
        _verify_combined_checksum(manifest, submission, combined_path)
        combined = read_json(combined_path)
        row = _build_row(combined)
        dataset_path = config.output_root / DATASET_FILENAME
        before_checksum = (
            compute_checksum(dataset_path) if dataset_path.exists() else ""
        )
        row_number = _append_row(dataset_path, row)
        after_checksum = compute_checksum(dataset_path)
        manifest = add_stage(
            manifest,
            submission.manifest_key,
            STAGE_ADD_TO_DATASET,
            STATUS_SUCCESS,
            input_combined=COMBINED_FILENAME,
            input_checksum=compute_checksum(combined_path),
            output_file=DATASET_FILENAME,
            dataset_row_number=row_number,
            dataset_checksum_before=before_checksum,
            dataset_checksum_after=after_checksum,
        )
        save_manifest(manifest)
    except StageInputError as error:
        print(f"error: add_to_dataset input missing: {error}", file=sys.stderr)
        return 1
    except StageExecutionError as error:
        print(f"error: add_to_dataset failed: {error}", file=sys.stderr)
        return 1
    except PipelineError as error:
        print(f"error: pipeline error: {error}", file=sys.stderr)
        return 1
    print(
        f"added: {submission.manifest_key} "
        f"row {row_number} appended to {DATASET_FILENAME}"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.add_to_dataset",
        description=(
            "Append a participant row to the aggregated dataset CSV."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "submission_name",
        help=(
            "Submission manifest key ({PID}_S{1|2}_{apm|speckit}); the "
            "combine stage must have produced combined.json under "
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


def _verify_combined_checksum(
    manifest: Any,
    submission: SubmissionName,
    combined_path: Path,
) -> None:
    """Surface a warning when combined.json differs from its manifest checksum."""
    submission_entry = manifest.get(submission.manifest_key)
    if submission_entry is None:
        return
    combine_entry = submission_entry.get_stage(STAGE_COMBINE)
    if combine_entry is None:
        return
    expected = combine_entry.fields.get("output_checksum", "")
    if expected and not validate_checksum(combined_path, expected):
        print(
            f"warning: combined.json checksum differs from manifest entry",
            file=sys.stderr,
        )


def _build_row(combined: dict[str, Any]) -> dict[str, Any]:
    """Project the combined artifact into the flat per-submission CSV row.

    Reads only session-scope leaves from the metrics artifact;
    phase and role decompositions stay in combined.json. Missing
    keys default to the empty string so the row stays valid even
    on a malformed upstream (the row's truthiness can be inspected
    by validate_dataset later).
    """
    metrics = combined.get("metrics", {}) or {}
    metadata = metrics.get("session_metadata", {}) or {}
    grading = combined.get("grading", {}) or {}
    session = metrics.get("session", {}) or {}
    economic = session.get("economic", {}) or {}
    process = session.get("process", {}) or {}
    time_block = process.get("time", {}) or {}
    user_input = process.get("user_input", {}) or {}
    reliability = process.get("reliability", {}) or {}
    supplementary = session.get("supplementary", {}) or {}
    diagnostics = metrics.get("diagnostics", {}) or {}
    invariants = diagnostics.get("invariant_checks", {}) or {}
    failure_count = sum(
        1
        for entry in invariants.values()
        if isinstance(entry, dict) and entry.get("status") != "ok"
    )
    turn_prompts_shares = _leaf_value(user_input.get("turn_prompts_bucket_shares"), {}) or {}
    all_inputs_shares = _leaf_value(user_input.get("all_inputs_bucket_shares"), {}) or {}
    return {
        "participant_id": combined.get("participant_id", ""),
        "session": combined.get("session", ""),
        "framework": combined.get("framework", ""),
        "processing_timestamp": combined.get("processing_timestamp", ""),
        "cc_version": metadata.get("cc_version", ""),
        "model": metadata.get("model", ""),
        "model_drift": metadata.get("model_drift", ""),
        "entrypoint": metadata.get("entrypoint", ""),
        "auth_mode_indicator": metadata.get("auth_mode_indicator", ""),
        "service_tier": metadata.get("service_tier", ""),
        "session_start_timestamp": metadata.get("session_start_timestamp", ""),
        "session_end_timestamp": metadata.get("session_end_timestamp", ""),
        "total_score": grading.get("total", {}).get("score", ""),
        "max_score": grading.get("total", {}).get("max", ""),
        "python_baseline_score": grading.get("python_baseline", {}).get("score", ""),
        "python_feature_score": grading.get("python_feature", {}).get("score", ""),
        "c_replica_score": grading.get("c_replica", {}).get("score", ""),
        "cost_usd": _leaf_value(economic.get("cost_usd"), ""),
        "total_input_tokens": _leaf_value(economic.get("total_input_tokens"), ""),
        "total_output_tokens": _leaf_value(economic.get("total_output_tokens"), ""),
        "total_cache_read_tokens": _leaf_value(economic.get("total_cache_read_tokens"), ""),
        "total_cache_5m_tokens": _leaf_value(economic.get("total_cache_5m_tokens"), ""),
        "total_cache_1h_tokens": _leaf_value(economic.get("total_cache_1h_tokens"), ""),
        "total_prompt_tokens": _leaf_value(economic.get("total_prompt_tokens"), ""),
        "main_input_tokens": _leaf_value(economic.get("main_input_tokens"), ""),
        "main_output_tokens": _leaf_value(economic.get("main_output_tokens"), ""),
        "delegated_input_tokens": _leaf_value(economic.get("delegated_input_tokens"), ""),
        "delegated_output_tokens": _leaf_value(economic.get("delegated_output_tokens"), ""),
        "duration": _leaf_value(time_block.get("duration"), ""),
        "turn_time": _leaf_value(time_block.get("turn_time"), ""),
        "turn_time_solo": _leaf_value(time_block.get("turn_time_solo"), ""),
        "turn_time_concurrent": _leaf_value(time_block.get("turn_time_concurrent"), ""),
        "inter_turn_time": _leaf_value(time_block.get("inter_turn_time"), ""),
        "turn_count": _leaf_value(time_block.get("turn_count"), ""),
        "mean_turn_duration": _leaf_value(time_block.get("mean_turn_duration"), ""),
        "turn_duration_p50": _leaf_value(time_block.get("turn_duration_p50"), ""),
        "turn_duration_p95": _leaf_value(time_block.get("turn_duration_p95"), ""),
        "turn_duration_stdev": _leaf_value(time_block.get("turn_duration_stdev"), ""),
        "turn_prompt_count": _leaf_value(user_input.get("turn_prompt_count"), ""),
        "steer_delivered_count": _leaf_value(user_input.get("steer_delivered_count"), ""),
        "steer_abandoned_count": _leaf_value(user_input.get("steer_abandoned_count"), ""),
        "steer_attempted_count": _leaf_value(user_input.get("steer_attempted_count"), ""),
        "turn_prompts_share_protocol": turn_prompts_shares.get("protocol", ""),
        "turn_prompts_share_short": turn_prompts_shares.get("short", ""),
        "turn_prompts_share_standard": turn_prompts_shares.get("standard", ""),
        "all_inputs_share_protocol": all_inputs_shares.get("protocol", ""),
        "all_inputs_share_short": all_inputs_shares.get("short", ""),
        "all_inputs_share_standard": all_inputs_shares.get("standard", ""),
        "tool_success_rate": _leaf_value(reliability.get("tool_success_rate"), ""),
        "subagent_count": _leaf_value(supplementary.get("subagent_count"), ""),
        "subagent_tool_count": _leaf_value(supplementary.get("subagent_tool_count"), ""),
        "reasoning_token_share": _leaf_value(supplementary.get("reasoning_token_share"), ""),
        "compaction_events_total": diagnostics.get("compaction_events_total", ""),
        "cost_excludes_compaction_synthesis": diagnostics.get("cost_excludes_compaction_synthesis", ""),
        "synthetic_assistant_records_excluded": diagnostics.get("synthetic_assistant_records_excluded", ""),
        "agent_dispatches_without_usage": diagnostics.get("agent_dispatches_without_usage", ""),
        "entrypoint_valid": diagnostics.get("entrypoint_valid", ""),
        "auth_mode_valid": diagnostics.get("auth_mode_valid", ""),
        "invariant_failures": failure_count,
    }


def _leaf_value(leaf: Any, default: Any) -> Any:
    """Unwrap a measurement leaf's ``value`` field, or return ``default``.

    Every parser-side measurement is wrapped in a
    ``{value, anchor, constructed}`` triple. The dataset CSV
    captures the value only; anchor and constructed flags travel
    with combined.json for downstream consumers that want them.
    """
    if isinstance(leaf, dict) and "value" in leaf:
        return leaf["value"]
    return default


def _append_row(dataset_path: Path, row: dict[str, Any]) -> int:
    """Append one row to the dataset CSV; write the header on first append.

    Returns the 1-indexed row number (excluding header) of the
    appended row.
    """
    write_header = not dataset_path.exists()
    existing_rows = 0
    if not write_header:
        with dataset_path.open("r", newline="", encoding="utf-8") as source:
            for line_number, _ in enumerate(source):
                existing_rows = line_number
    with dataset_path.open("a", newline="", encoding="utf-8") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(CSV_COLUMNS))
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return existing_rows + 1


if __name__ == "__main__":
    sys.exit(main())
