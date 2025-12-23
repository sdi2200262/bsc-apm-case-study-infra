#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Append a participant row to the aggregated dataset.
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from manifest import (
    add_entry,
    compute_checksum,
    create_stage_entry,
    get_entry,
    load_manifest,
    save_manifest,
    validate_checksum,
)
from workspace import (
    find_workspace_root,
    get_data_dir,
)

DATASET_FILENAME = "dataset.csv"

# CSV column order
CSV_COLUMNS = [
    "participant_id",
    "tool",
    "sub_study",
    "total_score",
    "max_score",
    "python_baseline_score",
    "python_feature_score",
    "c_replica_score",
    "file_count",
    "chat_ids",
    "model_ids",
    "session_start",
    "session_end",
    "session_duration_minutes",
    "total_requests",
    "tool_success_rate",
    "tool_retry_rate",
    "user_edit_rate",
    "ratio_short",
    "ratio_protocol",
    "ratio_standard",
    "avg_chars_short",
    "avg_chars_protocol",
    "avg_chars_standard",
    "processing_timestamp",
]


def load_json(path: Path) -> dict:
    """Load JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def combined_to_row(combined: Dict[str, Any]) -> Dict[str, Any]:
    """Convert combined JSON structure to CSV row."""
    grading = combined.get("grading", {})
    metrics = combined.get("metrics", {})
    project_meta = metrics.get("project_metadata", {})
    m = metrics.get("metrics", metrics)  # Handle both nested and flat structures
    
    row = {
        "participant_id": combined.get("participant_id", ""),
        "tool": combined.get("tool", ""),
        "sub_study": combined.get("sub_study", ""),
        "total_score": grading.get("total_score", 0),
        "max_score": grading.get("max_score", 48),
        "python_baseline_score": grading.get("python_baseline", {}).get("score", 0),
        "python_feature_score": grading.get("python_feature", {}).get("score", 0),
        "c_replica_score": grading.get("c_replica", {}).get("score", 0),
        "file_count": project_meta.get("file_count", 0),
        "chat_ids": ";".join(project_meta.get("chat_ids", [])),
        "model_ids": ";".join(project_meta.get("unique_model_ids", [])),
        "session_start": project_meta.get("global_start", ""),
        "session_end": project_meta.get("global_end", ""),
        "session_duration_minutes": m.get("session_duration_minutes", ""),
        "total_requests": m.get("total_requests", 0),
        "tool_success_rate": m.get("tool_success_rate", ""),
        "tool_retry_rate": m.get("tool_retry_rate", ""),
        "user_edit_rate": m.get("user_edit_rate", ""),
        "ratio_short": m.get("ratio_short_inputs", ""),
        "ratio_protocol": m.get("ratio_protocol_inputs", ""),
        "ratio_standard": m.get("ratio_standard_inputs", ""),
        "avg_chars_short": m.get("avg_chars_short", ""),
        "avg_chars_protocol": m.get("avg_chars_protocol", ""),
        "avg_chars_standard": m.get("avg_chars_standard", ""),
        "processing_timestamp": combined.get("processing_timestamp", ""),
    }
    
    return row


def read_existing_rows(dataset_path: Path) -> List[Dict[str, Any]]:
    """Read existing dataset rows."""
    if not dataset_path.exists():
        return []
    
    rows = []
    with open(dataset_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def write_dataset(dataset_path: Path, rows: List[Dict[str, Any]]) -> None:
    """Write dataset with all rows."""
    with open(dataset_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append a participant row to the aggregated dataset.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "participant_id",
        help="Participant ID (e.g., P001)"
    )
    parser.add_argument(
        "tool",
        choices=['a', 'b'],
        help="Tool identifier"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Base data directory (auto-detected from workspace if not specified)"
    )
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=None,
        help="Workspace root directory (auto-detected if not specified)"
    )
    
    args = parser.parse_args()
    
    pid = args.participant_id.upper()
    tool = args.tool.lower()
    
    # Auto-detect workspace and data directory
    workspace_root = find_workspace_root(args.workspace_dir)
    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
    elif workspace_root:
        # Get sub-study from manifest
        for sub_study in ["copilot", "cursor"]:
            test_data_dir = get_data_dir(sub_study, workspace_root)
            manifest = load_manifest(test_data_dir)
            entry = get_entry(manifest, pid, tool, "combine")
            if entry:
                data_dir = test_data_dir
                break
        else:
            print("Error: Could not determine sub-study. Please specify --data-dir", file=sys.stderr)
            return 2
    else:
        print("Error: Could not auto-detect workspace. Please specify --data-dir or --workspace-dir", file=sys.stderr)
        return 2
    
    # Locate participant directory
    participant_dir = data_dir / pid / f"tool_{tool}"
    if not participant_dir.exists():
        print(f"Error: Directory not found: {participant_dir}", file=sys.stderr)
        return 2
    
    # Locate combined file
    combined_file = participant_dir / f"{pid}_tool_{tool}_combined.json"
    if not combined_file.exists():
        print(f"Error: Combined file not found: {combined_file}", file=sys.stderr)
        print("Run combine_participant.py first", file=sys.stderr)
        return 1
    
    print(f"Adding to dataset: {pid} tool_{tool}")
    
    # Verify checksum against manifest
    manifest = load_manifest(data_dir)
    combine_entry = get_entry(manifest, pid, tool, "combine")
    if combine_entry:
        expected_checksum = combine_entry.get("output_checksum", "")
        if expected_checksum and not validate_checksum(combined_file, expected_checksum):
            print(f"Warning: Combined file checksum mismatch", file=sys.stderr)
    
    # Load combined data
    combined = load_json(combined_file)
    row = combined_to_row(combined)
    
    # Override processing_timestamp with current timestamp (when adding to dataset)
    processing_timestamp = datetime.now(timezone.utc).isoformat()
    row["processing_timestamp"] = processing_timestamp
    
    # Load existing dataset
    dataset_path = data_dir / DATASET_FILENAME
    existing_rows = read_existing_rows(dataset_path)
    
    dataset_checksum_before = ""
    if dataset_path.exists():
        dataset_checksum_before = compute_checksum(dataset_path)
    
    # Calculate row number (1-indexed for CSV)
    row_number = len(existing_rows) + 1
    
    # Append row to dataset
    existing_rows.append(row)
    
    # Write updated dataset
    write_dataset(dataset_path, existing_rows)
    
    dataset_checksum_after = compute_checksum(dataset_path)
    
    print(f"\nDataset updated: {dataset_path}")
    print(f"Total rows: {len(existing_rows)}")
    print(f"Added at row: {row_number}")
    
    # Update manifest
    entry = create_stage_entry(
        status="success",
        input_file=combined_file.name,
        input_checksum=compute_checksum(combined_file),
        output_file=DATASET_FILENAME,
        dataset_row_number=row_number,
        dataset_checksum_before=dataset_checksum_before,
        dataset_checksum_after=dataset_checksum_after,
    )
    
    add_entry(manifest, pid, tool, "add_to_dataset", entry)
    save_manifest(manifest, data_dir)
    
    print("Manifest updated")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
