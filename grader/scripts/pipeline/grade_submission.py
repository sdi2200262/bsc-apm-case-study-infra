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
from workspace import (
    find_workspace_root,
    get_workspace_paths,
    get_data_dir,
)

# Import PatchManager for cleanup on interruption
# Add grader directory to path so we can import src modules
script_dir = Path(__file__).parent
grader_dir = script_dir.parent.parent
sys.path.insert(0, str(grader_dir))
from src.patch_manager import PatchManager


def find_patch_file(participant_dir: Path) -> Optional[Path]:
    """Find the patch file in a participant's tool directory."""
    for f in participant_dir.iterdir():
        if f.suffix == '.patch':
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
        max_score = grand_total.get('max', 48)
    else:
        total = (
            python_baseline.get('score', 0) +
            python_feature.get('score', 0) +
            c_total.get('score', 0)
        )
        max_score = (
            python_baseline.get('max', 12) +
            python_feature.get('max', 12) +
            c_total.get('max', 24)
        )
    
    breakdown = {
        "python_baseline": f"{python_baseline.get('score', 0)}/{python_baseline.get('max', 12)}",
        "python_feature": f"{python_feature.get('score', 0)}/{python_feature.get('max', 12)}",
        "c_replica": f"{c_total.get('score', 0)}/{c_total.get('max', 24)}",
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
        default=None,
        help="Base data directory (auto-detected from workspace if not specified)"
    )
    parser.add_argument(
        "--grader-dir",
        type=Path,
        default=None,
        help="Path to grader directory (auto-detected from workspace if not specified)"
    )
    parser.add_argument(
        "--eclass-dir",
        type=Path,
        default=None,
        help="Path to eclass-mcp-server directory (auto-detected from workspace if not specified)"
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
    
    # Auto-detect workspace and paths
    workspace_root = find_workspace_root(args.workspace_dir)
    if workspace_root is None:
        if args.data_dir is None:
            print("Error: Could not auto-detect workspace. Please specify --data-dir or --workspace-dir", file=sys.stderr)
            return 2
        # Use provided data-dir, but still try to find workspace for grader/eclass
        workspace_root = find_workspace_root(args.data_dir)
    
    # Determine data directory
    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
    else:
        # Get sub-study from manifest if available
        # Try to find existing manifest to determine sub-study
        if workspace_root:
            # Try both sub-studies
            for sub_study in ["copilot", "cursor"]:
                test_data_dir = get_data_dir(sub_study, workspace_root)
                manifest = load_manifest(test_data_dir)
                entry = get_entry(manifest, pid, tool, "validate")
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
    
    # Find patch file
    patch_file = find_patch_file(participant_dir)
    if not patch_file:
        print(f"Error: No patch file found in {participant_dir}", file=sys.stderr)
        return 1
    
    print(f"Grading: {pid} tool_{tool}")
    print(f"Patch: {patch_file.name}")
    
    # Verify manifest entry exists
    manifest = load_manifest(data_dir)
    validate_entry = get_entry(manifest, pid, tool, "validate")
    if not validate_entry:
        print("Warning: No validation entry found in manifest", file=sys.stderr)
    
    # Locate grader
    if args.grader_dir:
        grader_path = Path(args.grader_dir).resolve() / "grade"
    elif workspace_root:
        paths = get_workspace_paths(workspace_root)
        grader_path = paths["grader_dir"] / "grade"
    else:
        script_dir = Path(__file__).parent
        grader_path = script_dir.parent.parent / "grade"
    
    if not grader_path.exists():
        print(f"Error: Grader not found: {grader_path}", file=sys.stderr)
        return 2
    
    # Determine eclass directory
    if args.eclass_dir:
        eclass_dir = Path(args.eclass_dir).resolve()
    elif workspace_root:
        paths = get_workspace_paths(workspace_root)
        eclass_dir = paths["eclass_dir"]
    else:
        eclass_dir = None
    
    # Run grader with cleanup on interruption
    print(f"\nRunning grader...")
    grader_cmd = [str(grader_path), str(patch_file)]
    if eclass_dir:
        grader_cmd.extend(["--eclass-dir", str(eclass_dir)])
    
    # Initialize patch manager for potential cleanup
    patch_manager = None
    if eclass_dir and eclass_dir.exists():
        patch_manager = PatchManager(eclass_dir)
    
    try:
        # Use subprocess.run but ensure stdin is closed to prevent hangs
        # The key fix: close stdin (DEVNULL) so no process waits for input
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
    
    # Find results file - grade script writes to workspace_root, not grader_path.parent
    if workspace_root:
        grader_results = workspace_root / f"results_{patch_file.stem}.json"
    else:
        # Fallback to grader_path.parent if workspace_root not available
        grader_results = grader_path.parent / f"results_{patch_file.stem}.json"
    if not grader_results.exists():
        print(f"Error: Results file not found: {grader_results}", file=sys.stderr)
        return 1
    
    # Copy to standardized name
    output_results = participant_dir / f"{pid}_tool_{tool}_results.json"
    shutil.copy(grader_results, output_results)
    
    # Clean up temporary results file from workspace root
    try:
        if grader_results.exists():
            grader_results.unlink()
            # Also clean up .txt file if it exists
            txt_file = grader_results.with_suffix('.txt')
            if txt_file.exists():
                txt_file.unlink()
    except Exception as e:
        print(f"Warning: Could not clean up temporary results file: {e}", file=sys.stderr)
    
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
    save_manifest(manifest, data_dir)
    
    print(f"\nResults saved: {output_results}")
    print("Manifest updated")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
