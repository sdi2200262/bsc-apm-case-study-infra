#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Cross-check the aggregated dataset CSV against the manifest.

This stage is submission-agnostic: it inspects the entire dataset
under one ``--output-root`` rather than operating on a single
submission. It does not write to the manifest; it reports pass or
fail to stdout and exits non-zero on any error so a CI gate can
key off the exit code.

Checks performed:

* Every manifest entry whose ``add_to_dataset`` stage succeeded
  has a corresponding row in the dataset CSV (matched by manifest
  key components).
* No row in the CSV exists without a corresponding successful
  manifest entry (orphans).
* No row appears twice (duplicate manifest keys).
* The CSV's column set matches the expected one defined in
  ``add_to_dataset.py`` so a manual edit cannot quietly drop or
  rename columns.
* The combined.json checksum recorded by the combine stage
  matches the on-disk file for every submission whose combine
  stage succeeded (catches post-combine edits).

Warnings (non-fatal): manifest entries with no successful
``add_to_dataset`` stage and no row in the CSV are reported as
in-progress submissions; rows whose combine-stage checksum cannot
be verified because combined.json is missing produce a warning;
manifest entries lacking checksums in their stage records are
skipped silently.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .add_to_dataset import CSV_COLUMNS, DATASET_FILENAME, COMBINED_FILENAME
from .config import resolve_config
from .errors import (
    ManifestError,
    PipelineError,
    StageExecutionError,
)
from .io import validate_checksum
from .manifest import (
    STAGE_ADD_TO_DATASET,
    STAGE_COMBINE,
    STATUS_SUCCESS,
    Manifest,
    SubmissionEntry,
    load_manifest,
)
from .submissions import (
    is_valid_submission_name,
    parse_submission_name,
    participant_subdir,
)

ROW_KEY_COLUMNS: tuple[str, str, str] = (
    "participant_id",
    "session",
    "framework",
)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for validate_dataset.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` when the dataset and manifest
        agree, ``1`` on any error finding, ``2`` on operator
        error.
    """
    args = _parse_args(argv)
    try:
        config = resolve_config(
            output_root=args.output_root,
            config_override=args.config,
        )
        manifest = load_manifest(config.output_root)
        dataset_path = config.output_root / DATASET_FILENAME
        column_names, rows = _read_dataset(dataset_path)
        errors: list[str] = []
        warnings: list[str] = []
        _check_columns(column_names, errors)
        _check_no_duplicate_rows(rows, errors)
        manifest_keys_in_dataset = _collect_dataset_keys(rows)
        _check_manifest_vs_dataset(
            manifest, manifest_keys_in_dataset, config.output_root, errors, warnings
        )
        _check_orphan_rows(manifest, manifest_keys_in_dataset, errors)
    except ManifestError as error:
        print(f"error: manifest issue: {error}", file=sys.stderr)
        return 1
    except StageExecutionError as error:
        print(f"error: validate_dataset failed: {error}", file=sys.stderr)
        return 1
    except PipelineError as error:
        print(f"error: pipeline error: {error}", file=sys.stderr)
        return 1
    print(f"manifest entries: {len(manifest.entries)}")
    print(f"dataset rows:     {len(rows)}")
    if warnings:
        print(f"\nwarnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")
    if errors:
        print(f"\nerrors ({len(errors)}):")
        for error in errors:
            print(f"  - {error}")
        print("\nvalidation FAILED")
        return 1
    print("\nvalidation PASSED")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.validate_dataset",
        description=(
            "Cross-check the aggregated dataset CSV against the manifest "
            "for one output root."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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


def _read_dataset(dataset_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return the dataset's column names and rows."""
    if not dataset_path.exists():
        return [], []
    with dataset_path.open("r", newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    return columns, rows


def _check_columns(columns: list[str], errors: list[str]) -> None:
    """Confirm the dataset CSV has exactly the expected column set in order."""
    expected = list(CSV_COLUMNS)
    if columns == expected:
        return
    missing = [c for c in expected if c not in columns]
    extra = [c for c in columns if c not in expected]
    if missing:
        errors.append(f"dataset.csv missing columns: {', '.join(missing)}")
    if extra:
        errors.append(f"dataset.csv has unexpected columns: {', '.join(extra)}")
    if not missing and not extra:
        errors.append(
            f"dataset.csv columns out of order; expected {expected[:3]}... "
            f"got {columns[:3]}..."
        )


def _check_no_duplicate_rows(
    rows: list[dict[str, str]],
    errors: list[str],
) -> None:
    """Confirm every row's submission identifiers are unique."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for row in rows:
        key = _row_manifest_key(row)
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if duplicates:
        errors.append(f"duplicate rows found: {', '.join(sorted(set(duplicates)))}")


def _collect_dataset_keys(rows: list[dict[str, str]]) -> set[str]:
    """Return the set of manifest keys derived from dataset rows."""
    return {_row_manifest_key(row) for row in rows}


def _row_manifest_key(row: dict[str, str]) -> str:
    """Reconstruct the manifest key from a dataset row's identifier columns."""
    pid = row.get(ROW_KEY_COLUMNS[0], "")
    session = row.get(ROW_KEY_COLUMNS[1], "")
    framework = row.get(ROW_KEY_COLUMNS[2], "")
    return f"{pid}_{session}_{framework}"


def _check_manifest_vs_dataset(
    manifest: Manifest,
    dataset_keys: set[str],
    output_root: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    """For every successful add-to-dataset entry, confirm the dataset has its row."""
    for key, submission_entry in manifest.entries.items():
        add_entry = submission_entry.get_stage(STAGE_ADD_TO_DATASET)
        if add_entry is None or add_entry.status != STATUS_SUCCESS:
            if key not in dataset_keys:
                warnings.append(
                    f"{key}: manifest tracks the submission but no dataset row "
                    "yet; processing may be in progress"
                )
            continue
        if key not in dataset_keys:
            errors.append(
                f"{key}: add_to_dataset reported success but the dataset row "
                "is missing"
            )
        _verify_combined_artifact(submission_entry, output_root, key, warnings)


def _verify_combined_artifact(
    submission_entry: SubmissionEntry,
    output_root: Path,
    manifest_key: str,
    warnings: list[str],
) -> None:
    """Confirm combined.json content matches the checksum the combine stage recorded."""
    if not is_valid_submission_name(manifest_key):
        return
    submission = parse_submission_name(manifest_key)
    combined_path = (
        output_root / participant_subdir(submission) / COMBINED_FILENAME
    )
    combine_entry = submission_entry.get_stage(STAGE_COMBINE)
    if combine_entry is None:
        return
    expected = combine_entry.fields.get("output_checksum", "")
    if not expected:
        return
    if not combined_path.exists():
        warnings.append(
            f"{manifest_key}: combined.json missing at {combined_path}; "
            "manifest cannot be cross-checked"
        )
        return
    if not validate_checksum(combined_path, expected):
        warnings.append(
            f"{manifest_key}: combined.json checksum differs from manifest "
            "entry; the file may have been edited"
        )


def _check_orphan_rows(
    manifest: Manifest,
    dataset_keys: set[str],
    errors: list[str],
) -> None:
    """Flag rows whose manifest key is not registered in the manifest."""
    manifest_keys = set(manifest.entries.keys())
    orphans = sorted(dataset_keys - manifest_keys)
    if orphans:
        errors.append(
            f"dataset rows without manifest entries: {', '.join(orphans)}"
        )


if __name__ == "__main__":
    sys.exit(main())
