#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Validate and extract participant submission zip files.
"""

import argparse
import re
import sys
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

from manifest import (
    add_entry,
    compute_checksum,
    create_stage_entry,
    load_manifest,
    save_manifest,
)

# Regex patterns for validation
PID_PATTERN = r"[Pp]\d{3}"
TOOL_PATTERN = r"[ab]"
ZIP_PATTERN = re.compile(rf"^({PID_PATTERN})_tool_({TOOL_PATTERN})_submission\.zip$")
PATCH_PATTERN = re.compile(rf"^({PID_PATTERN})_tool_({TOOL_PATTERN})_solution\.patch$")
LOGS_PATTERN = re.compile(rf"^({PID_PATTERN})_tool_({TOOL_PATTERN})_logs/?$")
CHAT_COPILOT_PATTERN = re.compile(rf"^({PID_PATTERN})_tool_({TOOL_PATTERN})_chat_(\d{{2}})\.json$")
CHAT_CURSOR_PATTERN = re.compile(rf"^({PID_PATTERN})_tool_({TOOL_PATTERN})_chat_(\d{{2}})\.md$")
REQUESTS_PATTERN = re.compile(rf"^({PID_PATTERN})_tool_({TOOL_PATTERN})_requests\.csv$")


def parse_zip_filename(filename: str) -> Optional[Tuple[str, str]]:
    """
    Extract participant ID and tool from zip filename.
    
    Returns:
        Tuple of (pid, tool) or None if pattern doesn't match.
    """
    match = ZIP_PATTERN.match(filename)
    if not match:
        return None
    return (match.group(1).upper(), match.group(2).lower())


def validate_zip_structure(zip_path: Path) -> Tuple[bool, List[str], str]:
    """
    Validate the structure of a submission zip file.
    
    Returns:
        Tuple of (is_valid, list of issues, detected sub_study).
    """
    issues: List[str] = []
    sub_study = "unknown"
    
    parsed = parse_zip_filename(zip_path.name)
    if not parsed:
        issues.append(f"Invalid zip filename: {zip_path.name}")
        issues.append("Expected format: {PID}_tool_{a|b}_submission.zip")
        return (False, issues, sub_study)
    
    pid, tool = parsed
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        issues.append("File is not a valid zip archive")
        return (False, issues, sub_study)
    
    # Check for patch file
    expected_patch = f"{pid}_tool_{tool}_solution.patch"
    patch_found = False
    for name in names:
        basename = Path(name).name
        if PATCH_PATTERN.match(basename):
            if basename.upper() == expected_patch.upper():
                patch_found = True
                break
    
    # More lenient patch check
    patch_candidates = [n for n in names if n.endswith('.patch') and 'solution' in n.lower()]
    if not patch_found and patch_candidates:
        patch_found = True
        if patch_candidates[0] != expected_patch:
            issues.append(f"Patch filename mismatch: found '{patch_candidates[0]}', expected '{expected_patch}'")
    
    if not patch_found:
        issues.append(f"Missing patch file: {expected_patch}")
    
    # Check for logs folder
    expected_logs = f"{pid}_tool_{tool}_logs"
    logs_found = any(name.startswith(expected_logs) for name in names)
    if not logs_found:
        # Try case-insensitive
        logs_found = any(name.lower().startswith(expected_logs.lower()) for name in names)
        if logs_found:
            issues.append(f"Logs folder has incorrect casing")
    
    if not logs_found:
        issues.append(f"Missing logs folder: {expected_logs}/")
    
    # Check for chats
    chat_files = [n for n in names if '/chats/' in n and not n.endswith('/')]
    
    json_chats = [f for f in chat_files if f.endswith('.json')]
    md_chats = [f for f in chat_files if f.endswith('.md')]
    
    if json_chats and md_chats:
        issues.append("Mixed chat formats found (both .json and .md)")
    elif json_chats:
        sub_study = "copilot"
    elif md_chats:
        sub_study = "cursor"
    else:
        issues.append("No chat files found in logs/chats/")
    
    # Validate chat naming
    for chat in json_chats:
        basename = Path(chat).name
        if not CHAT_COPILOT_PATTERN.match(basename):
            issues.append(f"Invalid chat filename: {basename}")
    
    for chat in md_chats:
        basename = Path(chat).name
        if not CHAT_CURSOR_PATTERN.match(basename):
            issues.append(f"Invalid chat filename: {basename}")
    
    # Cursor-specific: check for requests.csv
    if sub_study == "cursor":
        stats_files = [n for n in names if '/stats/' in n and n.endswith('.csv')]
        if not stats_files:
            issues.append("Missing stats/requests.csv (required for Cursor submissions)")
    
    is_valid = len(issues) == 0
    return (is_valid, issues, sub_study)


def extract_submission(zip_path: Path, output_dir: Path) -> None:
    """Extract submission zip to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and extract participant submission zip files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "zip_file",
        type=Path,
        help="Path to submission zip file"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to extract validated submission"
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=None,
        help="Directory containing pipeline manifest (defaults to output-dir parent)"
    )
    
    args = parser.parse_args()
    
    if not args.zip_file.exists():
        print(f"Error: File not found: {args.zip_file}", file=sys.stderr)
        return 2
    
    # Parse filename
    parsed = parse_zip_filename(args.zip_file.name)
    if not parsed:
        print(f"Error: Invalid zip filename: {args.zip_file.name}", file=sys.stderr)
        print("Expected format: {PID}_tool_{a|b}_submission.zip", file=sys.stderr)
        return 1
    
    pid, tool = parsed
    print(f"Validating: {pid} tool_{tool}")
    
    # Validate structure
    is_valid, issues, sub_study = validate_zip_structure(args.zip_file)
    
    if issues:
        print("\nIssues found:")
        for issue in issues:
            print(f"  - {issue}")
    
    if not is_valid:
        print("\nValidation FAILED")
        return 1
    
    print(f"\nValidation PASSED")
    print(f"Sub-study: {sub_study}")
    
    # Extract if output directory specified
    if args.output_dir:
        print(f"\nExtracting to: {args.output_dir}")
        extract_submission(args.zip_file, args.output_dir)
        
        # Update manifest
        manifest_dir = args.manifest_dir or args.output_dir.parent.parent
        manifest = load_manifest(manifest_dir)
        
        entry = create_stage_entry(
            status="success" if is_valid else "error",
            input_file=args.zip_file.name,
            input_checksum=compute_checksum(args.zip_file),
            sub_study=sub_study,
            warnings=issues if issues else [],
        )
        
        add_entry(manifest, pid, tool, "validate", entry)
        save_manifest(manifest, manifest_dir)
        print(f"Manifest updated: {manifest_dir / 'pipeline_manifest.json'}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
