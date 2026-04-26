#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Validate dataset integrity against manifest.

Submission-agnostic validation script that checks dataset CSV against manifest
for a given platform. Does not log to manifest.
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

from manifest import (
    MANIFEST_FILENAME,
    compute_checksum,
    load_manifest,
    validate_checksum,
)
from workspace import (
    find_workspace_root,
    get_data_dir,
)

DATASET_FILENAME = "dataset.csv"

REQUIRED_COLUMNS = [
    "participant_id",
    "session",
    "platform",
    "tool",
    "total_score",
    "max_score",
]


def read_dataset(dataset_path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    """
    Read dataset CSV.
    
    Args:
        dataset_path: Path to dataset CSV file.
        
    Returns:
        Tuple of (column names, list of row dicts).
    """
    if not dataset_path.exists():
        return ([], [])
    
    with open(dataset_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        rows = list(reader)
    
    return (columns, rows)


def validate_columns(columns: List[str]) -> List[str]:
    """
    Check for missing required columns.
    
    Args:
        columns: List of column names from dataset.
        
    Returns:
        List of missing required column names.
    """
    missing = []
    for col in REQUIRED_COLUMNS:
        if col not in columns:
            missing.append(col)
    return missing


def find_duplicates(rows: List[Dict[str, str]]) -> List[str]:
    """
    Find duplicate participant+session+platform+tool combinations.
    
    Args:
        rows: List of dataset row dictionaries.
        
    Returns:
        List of duplicate key strings.
    """
    seen: Set[str] = set()
    duplicates = []
    
    for row in rows:
        # Key format: {PID}_{S1|2}_{Platform}_{Tool}
        key = f"{row.get('participant_id', '')}_{row.get('session', '')}_{row.get('platform', '')}_{row.get('tool', '')}"
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    
    return duplicates


def build_dataset_key(row: Dict[str, str]) -> str:
    """
    Build manifest key from dataset row.
    
    Args:
        row: Dataset row dictionary.
        
    Returns:
        Manifest key string (e.g., 'P001_S1_copilot_apm').
    """
    return f"{row.get('participant_id', '')}_{row.get('session', '')}_{row.get('platform', '')}_{row.get('tool', '')}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate dataset integrity against manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Validates dataset CSV against manifest for a given platform.\n"
            "Example: ./validate_dataset.py --platform copilot\n\n"
            "This script is submission-agnostic and does not log to manifest."
        ),
    )
    parser.add_argument(
        "--platform",
        choices=["copilot"],
        required=True,
        help="Platform name (required)"
    )
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=None,
        help="Workspace root directory (auto-detected if not specified)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed validation output"
    )
    
    args = parser.parse_args()
    
    # Auto-detect workspace and get data directory
    workspace_root = find_workspace_root(args.workspace_dir)
    if workspace_root is None:
        print("Error: Could not auto-detect workspace root.", file=sys.stderr)
        print("Ensure you're in a directory containing:", file=sys.stderr)
        print("  - bsc-apm-case-study-task/", file=sys.stderr)
        print("  - bsc-apm-case-study-data/", file=sys.stderr)
        print("  - eclass-mcp-server/", file=sys.stderr)
        print("  - openeclass/", file=sys.stderr)
        return 2
    
    data_dir = get_data_dir(args.platform, workspace_root)
    
    if not data_dir.exists():
        print(f"Error: Directory not found: {data_dir}", file=sys.stderr)
        return 2
    
    print(f"Validating platform: {args.platform}")
    print(f"Data directory: {data_dir}")
    
    errors: List[str] = []
    warnings: List[str] = []
    
    # Load manifest
    manifest = load_manifest(data_dir)
    entries = manifest.get("entries", {})
    
    if not entries:
        warnings.append("Manifest has no entries")
    
    # Load dataset
    dataset_path = data_dir / DATASET_FILENAME
    columns, rows = read_dataset(dataset_path)
    
    if not rows:
        if entries:
            errors.append("Dataset is empty but manifest has entries")
    else:
        # Validate columns
        missing_cols = validate_columns(columns)
        if missing_cols:
            errors.append(f"Missing required columns: {', '.join(missing_cols)}")
        
        # Check for duplicates
        duplicates = find_duplicates(rows)
        if duplicates:
            errors.append(f"Duplicate rows found: {', '.join(duplicates)}")
    
    # Build set of dataset keys (new format: {PID}_{S1|2}_{Platform}_{Tool})
    dataset_keys: Set[str] = set()
    for row in rows:
        key = build_dataset_key(row)
        dataset_keys.add(key)
    
    # Cross-check manifest entries against dataset
    for entry_key, entry_data in entries.items():
        add_entry = entry_data.get("add_to_dataset")
        
        if add_entry and add_entry.get("status") == "success":
            # Should have a dataset row
            if entry_key not in dataset_keys:
                errors.append(f"{entry_key}: In manifest but missing from dataset")
        
        # Verify combined file exists and checksum matches
        combine_entry = entry_data.get("combine")
        if combine_entry:
            combined_file = combine_entry.get("output_file", "")
            expected_checksum = combine_entry.get("output_checksum", "")
            
            # Parse manifest key: {PID}_{S1|2}_{Platform}_{Tool}
            # Find combined file in dataset structure: {platform}/{PID}/S{session}_{tool}/{combined_file}
            parts = entry_key.split("_")
            if len(parts) >= 4:
                pid = parts[0]
                session = parts[1]
                platform_key = parts[2]
                tool = "_".join(parts[3:])  # Tool may contain hyphens
                
                combined_path = data_dir / pid / f"S{session}_{tool}" / combined_file
                
                if not combined_path.exists():
                    errors.append(f"{entry_key}: Combined file missing: {combined_file}")
                elif expected_checksum and not validate_checksum(combined_path, expected_checksum):
                    errors.append(f"{entry_key}: Combined file checksum mismatch")
                    if args.verbose:
                        actual = compute_checksum(combined_path)
                        print(f"  Expected: {expected_checksum}")
                        print(f"  Actual:   {actual}")
    
    # Check for orphan dataset rows (in dataset but not in manifest)
    manifest_keys = set(entries.keys())
    for key in dataset_keys:
        if key not in manifest_keys:
            warnings.append(f"{key}: In dataset but not in manifest")
    
    # Report results
    print(f"\nManifest entries: {len(entries)}")
    print(f"Dataset rows: {len(rows)}")
    
    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")
    
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
        print("\nValidation FAILED")
        return 1
    
    print("\nValidation PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
