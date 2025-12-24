#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Merge grading results with interaction metrics.

Takes unpacked submission directory, combines results and metrics, and outputs:
- Combined JSON to dataset repo: {platform}/{PID}/S{session}_{tool}/{PID}_{S1|2}_{platform}_{tool}_combined.json
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
from workspace import (
    find_workspace_root,
    get_submission_dataset_dir,
    get_manifest_key,
    parse_submission_name,
)


def load_json(path: Path) -> dict:
    """
    Load JSON file.
    
    Args:
        path: Path to JSON file.
        
    Returns:
        Parsed JSON data as dictionary.
    """
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: dict, path: Path) -> None:
    """
    Save JSON file with formatting.
    
    Args:
        data: Dictionary to save as JSON.
        path: Path to output file.
    """
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge grading results with interaction metrics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Takes unpacked submission directory path as argument.\n"
            "Example: ./combine_participant.py P001_S1_copilot_apm_submission\n\n"
            "Outputs:\n"
            "  - Combined JSON: dataset repo/{platform}/{PID}/S{session}_{tool}/{PID}_{S1|2}_{platform}_{tool}_combined.json"
        ),
    )
    parser.add_argument(
        "submission_dir",
        type=Path,
        help="Path to unpacked submission directory (at workspace root)"
    )
    
    args = parser.parse_args()
    
    submission_dir = Path(args.submission_dir).resolve()
    
    if not submission_dir.exists():
        print(f"Error: Directory not found: {submission_dir}", file=sys.stderr)
        return 2
    
    if not submission_dir.is_dir():
        print(f"Error: Not a directory: {submission_dir}", file=sys.stderr)
        return 2
    
    # Parse submission directory name
    parsed = parse_submission_name(submission_dir.name)
    if not parsed:
        print(f"Error: Invalid submission directory name: {submission_dir.name}", file=sys.stderr)
        print("Expected format: {PID}_{S1|2}_{Platform}_{Tool}_submission", file=sys.stderr)
        return 1
    
    pid, session, platform, tool = parsed
    
    # Auto-detect workspace
    workspace_root = find_workspace_root()
    if workspace_root is None:
        print("Error: Could not auto-detect workspace root.", file=sys.stderr)
        print("Ensure you're in a directory containing:", file=sys.stderr)
        print("  - bsc-apm-case-study-task/", file=sys.stderr)
        print("  - bsc-apm-case-study-data/", file=sys.stderr)
        print("  - eclass-mcp-server/", file=sys.stderr)
        print("  - openeclass/", file=sys.stderr)
        return 2
    
    # Get dataset directory for this submission
    dataset_dir = get_submission_dataset_dir(submission_dir, workspace_root)
    
    # Locate input files in dataset repo
    results_file = dataset_dir / f"{pid}_{session}_{platform}_{tool}_results.json"
    metrics_file = dataset_dir / f"{pid}_{session}_{platform}_{tool}_metrics.json"
    
    if not results_file.exists():
        print(f"Error: Results file not found: {results_file}", file=sys.stderr)
        print("Run grade_submission.py first", file=sys.stderr)
        return 1
    
    if not metrics_file.exists():
        print(f"Error: Metrics file not found: {metrics_file}", file=sys.stderr)
        print("Run parse_submission.py first", file=sys.stderr)
        return 1
    
    print(f"Combining: {pid} {session} {platform} {tool}")
    
    # Verify checksums against manifest
    manifest_dir = dataset_dir.parent.parent  # submissions_sanitized/{platform}/
    manifest = load_manifest(manifest_dir)
    manifest_key = get_manifest_key(submission_dir)
    
    grade_entry = get_entry(manifest, manifest_key, "grade")
    if grade_entry:
        expected_checksum = grade_entry.get("output_checksum", "")
        if expected_checksum and not validate_checksum(results_file, expected_checksum):
            print(f"Warning: Results file checksum mismatch", file=sys.stderr)
    
    parse_entry = get_entry(manifest, manifest_key, "parse")
    if parse_entry:
        expected_checksum = parse_entry.get("output_checksum", "")
        if expected_checksum and not validate_checksum(metrics_file, expected_checksum):
            print(f"Warning: Metrics file checksum mismatch", file=sys.stderr)
    
    # Load data
    results = load_json(results_file)
    metrics = load_json(metrics_file)
    
    # Extract grading scores
    # Results file structure:
    # {
    #   "scores": {
    #     "python": {
    #       "baseline": {"score": ..., "max": ...},
    #       "feature": {"score": ..., "max": ...},
    #       "total": {"score": ..., "max": ...}
    #     },
    #     "c": {
    #       "total": {"score": ..., "max": ...}
    #     },
    #     "grand_total": {"score": ..., "max": ...}
    #   }
    # }
    scores = results.get('scores', {})
    
    # Extract nested structure
    python = scores.get('python', {})
    python_baseline = python.get('baseline', {'score': 0, 'max': 12})
    python_feature = python.get('feature', {'score': 0, 'max': 12})
    c = scores.get('c', {})
    c_total = c.get('total', {'score': 0, 'max': 24})
    
    # Use grand_total if available, otherwise calculate
    grand_total = scores.get('grand_total', {})
    if grand_total:
        total_score = grand_total.get('score', 0)
        max_score = grand_total.get('max', 48)
    else:
        total_score = (
            python_baseline.get('score', 0) +
            python_feature.get('score', 0) +
            c_total.get('score', 0)
        )
        max_score = (
            python_baseline.get('max', 12) +
            python_feature.get('max', 12) +
            c_total.get('max', 24)
        )
    
    # Build combined structure
    combined = {
        "participant_id": pid,
        "session": session,
        "platform": platform,
        "tool": tool,
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
                "score": c_total.get('score', 0),
                "max": c_total.get('max', 24)
            }
        },
        "metrics": metrics
    }
    
    # Save combined output to dataset repo
    output_file = dataset_dir / f"{pid}_{session}_{platform}_{tool}_combined.json"
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
    
    add_entry(manifest, manifest_key, "combine", entry)
    save_manifest(manifest, manifest_dir)
    
    print("Manifest updated")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
