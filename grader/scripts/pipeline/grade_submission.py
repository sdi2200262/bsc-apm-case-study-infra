#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Run the grader on a validated submission.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from manifest import (
    add_entry,
    compute_checksum,
    create_stage_entry,
    get_entry,
    load_manifest,
    save_manifest,
)


def find_patch_file(participant_dir: Path) -> Optional[Path]:
    """Find the patch file in a participant's tool directory."""
    for f in participant_dir.iterdir():
        if f.suffix == '.patch':
            return f
    return None


def parse_grading_results(results_path: Path) -> Tuple[int, int, dict]:
    """
    Parse grading results JSON to extract scores.
    
    Returns:
        Tuple of (total_score, max_score, breakdown_dict)
    """
    with open(results_path, 'r') as f:
        data = json.load(f)
    
    scores = data.get('scores', {})
    
    python_baseline = scores.get('python_baseline', {})
    python_feature = scores.get('python_feature', {})
    c_replica = scores.get('c_replica', {})
    
    total = (
        python_baseline.get('score', 0) +
        python_feature.get('score', 0) +
        c_replica.get('score', 0)
    )
    
    max_score = (
        python_baseline.get('max', 12) +
        python_feature.get('max', 12) +
        c_replica.get('max', 24)
    )
    
    breakdown = {
        "python_baseline": f"{python_baseline.get('score', 0)}/{python_baseline.get('max', 12)}",
        "python_feature": f"{python_feature.get('score', 0)}/{python_feature.get('max', 12)}",
        "c_replica": f"{c_replica.get('score', 0)}/{c_replica.get('max', 24)}",
    }
    
    return (total, max_score, breakdown)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the grader on a validated submission.",
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
    parser.add_argument(
        "--grader-dir",
        type=Path,
        default=None,
        help="Path to grader directory (defaults to ../../)"
    )
    
    args = parser.parse_args()
    
    pid = args.participant_id.upper()
    tool = args.tool.lower()
    
    # Locate participant directory
    participant_dir = args.data_dir / pid / f"tool_{tool}"
    if not participant_dir.exists():
        print(f"Error: Directory not found: {participant_dir}", file=sys.stderr)
        return 2
    
    # Find patch file
    patch_file = find_patch_file(participant_dir)
    if not patch_file:
        print(f"Error: No patch file found in {participant_dir}", file=sys.stderr)
        return 1
    
    print(f"Grading: {pid} tool_{tool}")
    print(f"Patch: {patch_file.name}")
    
    # Verify manifest entry exists
    manifest = load_manifest(args.data_dir)
    validate_entry = get_entry(manifest, pid, tool, "validate")
    if not validate_entry:
        print("Warning: No validation entry found in manifest", file=sys.stderr)
    
    # Locate grader
    if args.grader_dir:
        grader_path = args.grader_dir / "grade"
    else:
        script_dir = Path(__file__).parent
        grader_path = script_dir.parent.parent / "grade"
    
    if not grader_path.exists():
        print(f"Error: Grader not found: {grader_path}", file=sys.stderr)
        return 2
    
    # Run grader
    print(f"\nRunning grader...")
    result = subprocess.run(
        [str(grader_path), str(patch_file)],
        cwd=grader_path.parent,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"Grader output:\n{result.stdout}", file=sys.stderr)
        print(f"Grader errors:\n{result.stderr}", file=sys.stderr)
        print(f"\nGrading FAILED (exit code {result.returncode})")
        return 1
    
    # Find results file
    grader_results = grader_path.parent / f"results_{patch_file.stem}.json"
    if not grader_results.exists():
        print(f"Error: Results file not found: {grader_results}", file=sys.stderr)
        return 1
    
    # Copy to standardized name
    output_results = participant_dir / f"{pid}_tool_{tool}_results.json"
    shutil.copy(grader_results, output_results)
    
    # Parse scores
    total, max_score, breakdown = parse_grading_results(output_results)
    print(f"\nScore: {total}/{max_score}")
    for category, score in breakdown.items():
        print(f"  {category}: {score}")
    
    # Update manifest
    entry = create_stage_entry(
        status="success",
        input_file=patch_file.name,
        input_checksum=compute_checksum(patch_file),
        output_file=output_results.name,
        output_checksum=compute_checksum(output_results),
        score=f"{total}/{max_score}",
        score_breakdown=breakdown,
    )
    
    add_entry(manifest, pid, tool, "grade", entry)
    save_manifest(manifest, args.data_dir)
    
    print(f"\nResults saved: {output_results}")
    print("Manifest updated")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
