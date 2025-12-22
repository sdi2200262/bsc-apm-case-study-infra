#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Validate dataset integrity against manifest.
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
DATASET_FILENAME = "dataset.csv"

REQUIRED_COLUMNS = [
    "participant_id",
    "tool",
    "sub_study",
    "total_score",
    "max_score",
]


def read_dataset(dataset_path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    """
    Read dataset CSV.
    
    Returns:
        Tuple of (column names, list of row dicts)
    """
    if not dataset_path.exists():
        return ([], [])
    
    with open(dataset_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        rows = list(reader)
    
    return (columns, rows)


def validate_columns(columns: List[str]) -> List[str]:
    """Check for missing required columns."""
    missing = []
    for col in REQUIRED_COLUMNS:
        if col not in columns:
            missing.append(col)
    return missing


def find_duplicates(rows: List[Dict[str, str]]) -> List[str]:
    """Find duplicate participant+tool combinations."""
    seen: Set[str] = set()
    duplicates = []
    
    for row in rows:
        key = f"{row.get('participant_id', '')}_{row.get('tool', '')}"
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    
    return duplicates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate dataset integrity against manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Base data directory (e.g., submissions_sanitized/copilot)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed validation output"
    )
    
    args = parser.parse_args()
    
    if not args.data_dir.exists():
        print(f"Error: Directory not found: {args.data_dir}", file=sys.stderr)
        return 2
    
    print(f"Validating: {args.data_dir}")
    
    errors: List[str] = []
    warnings: List[str] = []
    
    # Load manifest
    manifest = load_manifest(args.data_dir)
    entries = manifest.get("entries", {})
    
    if not entries:
        warnings.append("Manifest has no entries")
    
    # Load dataset
    dataset_path = args.data_dir / DATASET_FILENAME
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
    
    # Build set of dataset keys
    dataset_keys: Set[str] = set()
    for row in rows:
        key = f"{row.get('participant_id', '')}_tool_{row.get('tool', '')}"
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
            
            # Parse participant ID and tool from entry key
            parts = entry_key.split("_tool_")
            if len(parts) == 2:
                pid, tool = parts
                combined_path = args.data_dir / pid / f"tool_{tool}" / combined_file
                
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
