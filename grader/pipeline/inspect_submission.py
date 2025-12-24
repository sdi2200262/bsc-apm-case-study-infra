#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Inspect submission processing history from manifest.

Takes manifest key and displays all processing stages, statuses, and details.
Useful for debugging and understanding what happened during pipeline execution.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from manifest import (
    get_all_stages,
    load_manifest,
)
from workspace import (
    find_workspace_root,
    get_data_dir,
)

# Pipeline stages in order
PIPELINE_STAGES = [
    "validate",
    "grade",
    "parse",
    "combine",
    "add_to_dataset",
]


def parse_manifest_key(key: str) -> Optional[tuple]:
    """
    Parse manifest key to extract components.
    
    Args:
        key: Manifest key (e.g., 'P001_S1_copilot_apm').
        
    Returns:
        Tuple of (pid, session, platform, tool) or None if invalid.
    """
    parts = key.split("_")
    if len(parts) < 4:
        return None
    
    pid = parts[0]
    session = parts[1]
    platform = parts[2]
    tool = "_".join(parts[3:])  # Tool may contain hyphens
    
    return (pid, session, platform, tool)


def format_entry(entry: Dict, stage: str) -> List[str]:
    """
    Format a manifest entry for display.
    
    Args:
        entry: Manifest entry dictionary.
        stage: Stage name.
        
    Returns:
        List of formatted lines.
    """
    lines = []
    status = entry.get("status", "unknown")
    timestamp = entry.get("timestamp", "")
    
    # Status indicator
    if status == "success":
        indicator = "✓"
    elif status == "warning":
        indicator = "⚠"
    elif status == "error":
        indicator = "✗"
    else:
        indicator = "?"
    
    lines.append(f"  [{indicator}] {stage.upper()}: {status}")
    if timestamp:
        lines.append(f"      Timestamp: {timestamp}")
    
    # Show input/output files
    input_file = entry.get("input_file")
    if input_file:
        lines.append(f"      Input: {input_file}")
    
    output_file = entry.get("output_file")
    if output_file:
        lines.append(f"      Output: {output_file}")
    
    output_file_json = entry.get("output_file_json")
    output_file_txt = entry.get("output_file_txt")
    if output_file_json:
        lines.append(f"      Output JSON: {output_file_json}")
    if output_file_txt:
        lines.append(f"      Output TXT: {output_file_txt}")
    
    # Show checksums
    input_checksum = entry.get("input_checksum")
    if input_checksum:
        lines.append(f"      Input checksum: {input_checksum[:16]}...")
    
    output_checksum = entry.get("output_checksum")
    if output_checksum:
        lines.append(f"      Output checksum: {output_checksum[:16]}...")
    
    # Show warnings
    warnings = entry.get("warnings", [])
    if warnings:
        lines.append(f"      Warnings ({len(warnings)}):")
        for warning in warnings[:5]:  # Show first 5
            lines.append(f"        - {warning}")
        if len(warnings) > 5:
            lines.append(f"        ... and {len(warnings) - 5} more")
    
    # Show errors
    errors = entry.get("errors", [])
    if errors:
        lines.append(f"      Errors ({len(errors)}):")
        for error in errors:
            lines.append(f"        - {error}")
    
    # Show additional fields
    score = entry.get("score")
    if score:
        lines.append(f"      Score: {score}")
    
    dataset_row_number = entry.get("dataset_row_number")
    if dataset_row_number:
        lines.append(f"      Dataset row: {dataset_row_number}")
    
    platform = entry.get("platform")
    if platform:
        lines.append(f"      Platform: {platform}")
    
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect submission processing history from manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Takes manifest key as argument.\n"
            "Example: ./inspect_submission.py P001_S1_copilot_apm\n\n"
            "Shows all processing stages, statuses, and details from manifest.\n"
            "No zip file required - works from manifest only."
        ),
    )
    parser.add_argument(
        "manifest_key",
        help="Manifest entry key (e.g., 'P001_S1_copilot_apm')"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted text"
    )
    
    args = parser.parse_args()
    
    manifest_key = args.manifest_key
    
    # Parse manifest key to determine platform
    parsed = parse_manifest_key(manifest_key)
    if not parsed:
        print(f"Error: Invalid manifest key format: {manifest_key}", file=sys.stderr)
        print("Expected format: {PID}_{S1|2}_{Platform}_{Tool}", file=sys.stderr)
        print("Example: P001_S1_copilot_apm", file=sys.stderr)
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
    
    # Get manifest directory
    manifest_dir = get_data_dir(platform, workspace_root)
    
    # Load manifest
    manifest = load_manifest(manifest_dir)
    all_stages = get_all_stages(manifest, manifest_key)
    
    if not all_stages:
        print(f"Error: No entry found for manifest key: {manifest_key}", file=sys.stderr)
        print(f"Manifest location: {manifest_dir / 'pipeline_manifest.json'}", file=sys.stderr)
        return 1
    
    # JSON output mode
    if args.json:
        output = {
            "manifest_key": manifest_key,
            "platform": platform,
            "stages": all_stages
        }
        print(json.dumps(output, indent=2))
        return 0
    
    # Formatted text output
    print("=" * 70)
    print(f"SUBMISSION INSPECTION: {manifest_key}")
    print("=" * 70)
    print(f"Platform: {platform}")
    print(f"Manifest: {manifest_dir / 'pipeline_manifest.json'}")
    print("")
    
    # Show stages in order
    failed_stages = []
    for stage in PIPELINE_STAGES:
        if stage in all_stages:
            entry = all_stages[stage]
            lines = format_entry(entry, stage)
            print("\n".join(lines))
            print("")
            
            if entry.get("status") == "error":
                failed_stages.append(stage)
        else:
            print(f"  [ ] {stage.upper()}: Not executed")
            print("")
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    executed = [s for s in PIPELINE_STAGES if s in all_stages]
    print(f"Stages executed: {len(executed)}/{len(PIPELINE_STAGES)}")
    print(f"  Executed: {', '.join(executed) if executed else 'none'}")
    
    not_executed = [s for s in PIPELINE_STAGES if s not in all_stages]
    if not_executed:
        print(f"  Not executed: {', '.join(not_executed)}")
    
    if failed_stages:
        print(f"\nFailed stages: {', '.join(failed_stages)}")
        print("\nTo fix: Re-run pipeline from the first failed stage.")
        print("You will need the original zip file at workspace root.")
    
    # Check if all stages completed successfully
    all_success = all(
        all_stages.get(s, {}).get("status") == "success"
        for s in PIPELINE_STAGES
    )
    
    if all_success and len(executed) == len(PIPELINE_STAGES):
        print("\n✓ All stages completed successfully")
    elif failed_stages:
        print(f"\n✗ Pipeline incomplete - {len(failed_stages)} stage(s) failed")
    else:
        print(f"\n⚠ Pipeline incomplete - {len(not_executed)} stage(s) not executed")
    
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

