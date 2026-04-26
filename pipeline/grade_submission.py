#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Run the grader on a validated submission.

Takes unpacked submission directory, applies patch, runs grader, and outputs:
- JSON results to dataset repo: {platform}/{PID}/S{session}_{tool}/{PID}_{S1|2}_{platform}_{tool}_results.json
- TXT report to workspace root: results_{PID}_{S1|2}_{platform}_{tool}.txt
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
from workspace import (
    find_workspace_root,
    get_workspace_paths,
    get_submission_dataset_dir,
    get_manifest_key,
    parse_submission_name,
)

# Import PatchManager for cleanup on interruption
# Add grader directory to path so we can import src modules
script_dir = Path(__file__).parent
grader_dir = script_dir.parent
sys.path.insert(0, str(grader_dir))
from src.patch_manager import PatchManager


def find_patch_file(submission_dir: Path) -> Optional[Path]:
    """
    Find the patch file in submission directory.
    
    Args:
        submission_dir: Path to unpacked submission directory.
        
    Returns:
        Path to patch file or None if not found.
    """
    for f in submission_dir.iterdir():
        if f.suffix == '.patch' and 'solution' in f.name.lower():
            return f
    return None


def parse_grading_results(results_path: Path) -> Tuple[int, int, dict]:
    """
    Parse grading results JSON to extract scores.
    
    The results file structure is:
    {
        "scores": {
            "python": {
                "baseline": {"score": ..., "max": ...},
                "feature": {"score": ..., "max": ...},
                "total": {"score": ..., "max": ...}
            },
            "c": {
                "total": {"score": ..., "max": ...}
            },
            "grand_total": {"score": ..., "max": ...}
        }
    }
    
    Returns:
        Tuple of (total_score, max_score, breakdown_dict)
    """
    with open(results_path, 'r') as f:
        data = json.load(f)
    
    scores = data.get('scores', {})
    
    # Extract nested structure
    python = scores.get('python', {})
    python_baseline = python.get('baseline', {})
    python_feature = python.get('feature', {})
    c = scores.get('c', {})
    c_total = c.get('total', {})
    grand_total = scores.get('grand_total', {})
    
    # Use grand_total if available, otherwise calculate
    if grand_total:
        total = grand_total.get('score', 0)
        max_score = grand_total.get('max', 100)
    else:
        total = (
            python_baseline.get('score', 0) +
            python_feature.get('score', 0) +
            c_total.get('score', 0)
        )
        max_score = (
            python_baseline.get('max', 12) +
            python_feature.get('max', 36) +
            c_total.get('max', 52)
        )

    breakdown = {
        "python_baseline": f"{python_baseline.get('score', 0)}/{python_baseline.get('max', 12)}",
        "python_feature": f"{python_feature.get('score', 0)}/{python_feature.get('max', 36)}",
        "c_replica": f"{c_total.get('score', 0)}/{c_total.get('max', 52)}",
    }
    
    return (total, max_score, breakdown)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the grader on a validated submission.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Takes unpacked submission directory path as argument.\n"
            "Example: ./grade_submission.py P001_S1_copilot_apm_submission\n\n"
            "Outputs:\n"
            "  - JSON: dataset repo/{platform}/{PID}/S{session}_{tool}/{PID}_{S1|2}_{platform}_{tool}_results.json\n"
            "  - TXT: workspace root/results_{PID}_{S1|2}_{platform}_{tool}.txt"
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
    
    # Verify submission directory is at workspace root
    if submission_dir.parent != workspace_root:
        print(f"Warning: Submission directory is not at workspace root: {submission_dir}", file=sys.stderr)
        print(f"Expected location: {workspace_root / submission_dir.name}", file=sys.stderr)
    
    # Get dataset directory for this submission
    dataset_dir = get_submission_dataset_dir(submission_dir, workspace_root)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    
    # Find patch file
    patch_file = find_patch_file(submission_dir)
    if not patch_file:
        print(f"Error: No patch file found in {submission_dir}", file=sys.stderr)
        return 1
    
    print(f"Grading: {pid} {session} {platform} {tool}")
    print(f"Patch: {patch_file.name}")
    
    # Verify manifest entry exists
    manifest_dir = dataset_dir.parent.parent  # submissions_sanitized/{platform}/
    manifest = load_manifest(manifest_dir)
    manifest_key = get_manifest_key(submission_dir)
    validate_entry = get_entry(manifest, manifest_key, "validate")
    if not validate_entry:
        print("Warning: No validation entry found in manifest", file=sys.stderr)
    
    # Locate grader and eclass directory
    paths = get_workspace_paths(workspace_root)
    grader_path = paths["grader_dir"] / "grade"
    eclass_dir = paths["eclass_dir"]
    
    if not grader_path.exists():
        print(f"Error: Grader not found: {grader_path}", file=sys.stderr)
        return 2
    
    # Run grader with cleanup on interruption
    print(f"\nRunning grader...")
    grader_cmd = [str(grader_path), str(patch_file)]
    if eclass_dir.exists():
        grader_cmd.extend(["--eclass-dir", str(eclass_dir)])
    
    # Initialize patch manager for potential cleanup
    patch_manager = None
    if eclass_dir.exists():
        patch_manager = PatchManager(eclass_dir)
    
    # Files created by this script (for cleanup on error)
    created_files = []
    
    try:
        # Use subprocess.run but ensure stdin is closed to prevent hangs
        result = subprocess.run(
            grader_cmd,
            cwd=grader_path.parent,
            stdin=subprocess.DEVNULL,  # Critical: close stdin to prevent hangs
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"Grader output:\n{result.stdout}", file=sys.stderr)
            print(f"Grader errors:\n{result.stderr}", file=sys.stderr)
            print(f"\nGrading FAILED (exit code {result.returncode})")
            return 1
            
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Cleaning up...", file=sys.stderr)
        # Always attempt cleanup on interruption - grade script applies patch early
        if patch_manager:
            try:
                cleanup_success, cleanup_msg = patch_manager.cleanup()
                print(f"Cleanup: {cleanup_msg}", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Cleanup failed: {e}", file=sys.stderr)
        return 130  # Standard exit code for SIGINT
    
    # Find results files - grade script writes to workspace_root
    # Format: results_{patch_stem}.json and results_{patch_stem}.txt
    patch_stem = patch_file.stem
    grader_results_json = workspace_root / f"results_{patch_stem}.json"
    grader_results_txt = workspace_root / f"results_{patch_stem}.txt"
    
    if not grader_results_json.exists():
        print(f"Error: Results file not found: {grader_results_json}", file=sys.stderr)
        return 1
    
    # Generate output filenames
    output_results_json = dataset_dir / f"{pid}_{session}_{platform}_{tool}_results.json"
    output_results_txt = workspace_root / f"results_{pid}_{session}_{platform}_{tool}.txt"
    
    # Copy JSON to dataset repo
    try:
        shutil.copy(grader_results_json, output_results_json)
        created_files.append(output_results_json)
    except Exception as e:
        print(f"Error: Failed to copy results JSON: {e}", file=sys.stderr)
        return 1
    
    # Copy TXT to workspace root (keep for review)
    if grader_results_txt.exists():
        try:
            shutil.copy(grader_results_txt, output_results_txt)
            created_files.append(output_results_txt)
        except Exception as e:
            print(f"Warning: Failed to copy results TXT: {e}", file=sys.stderr)
    
    # Clean up temporary results files from workspace root
    try:
        if grader_results_json.exists():
            grader_results_json.unlink()
        if grader_results_txt.exists():
            grader_results_txt.unlink()
    except Exception as e:
        print(f"Warning: Could not clean up temporary results files: {e}", file=sys.stderr)
    
    # Parse scores (if this fails, we still have the files for debugging)
    try:
        total, max_score, breakdown = parse_grading_results(output_results_json)
    except Exception as e:
        print(f"Error: Failed to parse grading results: {e}", file=sys.stderr)
        print("Results files were created but parsing failed.", file=sys.stderr)
        return 1
    print(f"\nScore: {total}/{max_score}")
    for category, score in breakdown.items():
        print(f"  {category}: {score}")
    
    # Update manifest
    entry = create_stage_entry(
        status="success",
        input_file=patch_file.name,
        input_checksum=compute_checksum(patch_file),
        output_file_json=output_results_json.name,
        output_file_txt=output_results_txt.name if output_results_txt.exists() else None,
        output_checksum=compute_checksum(output_results_json),
        score=f"{total}/{max_score}",
        score_breakdown=breakdown,
    )
    
    add_entry(manifest, manifest_key, "grade", entry)
    save_manifest(manifest, manifest_dir)
    
    print(f"\nResults saved:")
    print(f"  JSON: {output_results_json}")
    if output_results_txt.exists():
        print(f"  TXT: {output_results_txt}")
    print("Manifest updated")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
