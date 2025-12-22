#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Merge grading results with interaction metrics.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from manifest import (
    add_entry,
    compute_checksum,
    create_stage_entry,
    get_entry,
    load_manifest,
    save_manifest,
    validate_checksum,
)


def load_json(path: Path) -> dict:
    """Load JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: dict, path: Path) -> None:
    """Save JSON file with formatting."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge grading results with interaction metrics.",
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
        required=True,
        help="Base data directory (e.g., submissions_sanitized/copilot)"
    )
    
    args = parser.parse_args()
    
    pid = args.participant_id.upper()
    tool = args.tool.lower()
    
    # Locate participant directory
    participant_dir = args.data_dir / pid / f"tool_{tool}"
    if not participant_dir.exists():
        print(f"Error: Directory not found: {participant_dir}", file=sys.stderr)
        return 2
    
    # Locate input files
    results_file = participant_dir / f"{pid}_tool_{tool}_results.json"
    metrics_file = participant_dir / f"{pid}_tool_{tool}_metrics.json"
    
    if not results_file.exists():
        print(f"Error: Results file not found: {results_file}", file=sys.stderr)
        print("Run grade_submission.py first", file=sys.stderr)
        return 1
    
    if not metrics_file.exists():
        print(f"Error: Metrics file not found: {metrics_file}", file=sys.stderr)
        print("Run parse_submission.py first", file=sys.stderr)
        return 1
    
    print(f"Combining: {pid} tool_{tool}")
    
    # Verify checksums against manifest
    manifest = load_manifest(args.data_dir)
    
    grade_entry = get_entry(manifest, pid, tool, "grade")
    if grade_entry:
        expected_checksum = grade_entry.get("output_checksum", "")
        if expected_checksum and not validate_checksum(results_file, expected_checksum):
            print(f"Warning: Results file checksum mismatch", file=sys.stderr)
    
    parse_entry = get_entry(manifest, pid, tool, "parse")
    if parse_entry:
        expected_checksum = parse_entry.get("output_checksum", "")
        if expected_checksum and not validate_checksum(metrics_file, expected_checksum):
            print(f"Warning: Metrics file checksum mismatch", file=sys.stderr)
    
    # Determine sub-study
    sub_study = "unknown"
    if parse_entry:
        sub_study = parse_entry.get("sub_study", "unknown")
    
    # Load data
    results = load_json(results_file)
    metrics = load_json(metrics_file)
    
    # Extract grading scores
    scores = results.get('scores', {})
    python_baseline = scores.get('python_baseline', {'score': 0, 'max': 12})
    python_feature = scores.get('python_feature', {'score': 0, 'max': 12})
    c_replica = scores.get('c_replica', {'score': 0, 'max': 24})
    
    total_score = (
        python_baseline.get('score', 0) +
        python_feature.get('score', 0) +
        c_replica.get('score', 0)
    )
    max_score = (
        python_baseline.get('max', 12) +
        python_feature.get('max', 12) +
        c_replica.get('max', 24)
    )
    
    # Build combined structure
    combined = {
        "participant_id": pid,
        "tool": tool,
        "sub_study": sub_study,
        "processing_timestamp": datetime.now(timezone.utc).isoformat(),
        "grading": {
            "total_score": total_score,
            "max_score": max_score,
            "python_baseline": {
                "score": python_baseline.get('score', 0),
                "max": python_baseline.get('max', 12)
            },
            "python_feature": {
                "score": python_feature.get('score', 0),
                "max": python_feature.get('max', 12)
            },
            "c_replica": {
                "score": c_replica.get('score', 0),
                "max": c_replica.get('max', 24)
            }
        },
        "metrics": metrics
    }
    
    # Save combined output
    output_file = participant_dir / f"{pid}_tool_{tool}_combined.json"
    save_json(combined, output_file)
    
    print(f"\nCombined output: {output_file}")
    print(f"Score: {total_score}/{max_score}")
    
    # Update manifest
    entry = create_stage_entry(
        status="success",
        input_files=[results_file.name, metrics_file.name],
        output_file=output_file.name,
        output_checksum=compute_checksum(output_file),
    )
    
    add_entry(manifest, pid, tool, "combine", entry)
    save_manifest(manifest, args.data_dir)
    
    print("Manifest updated")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
