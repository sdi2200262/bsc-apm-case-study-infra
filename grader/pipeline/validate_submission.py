#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Validate and extract participant submission zip files.

Validates new submission format: {PID}_{S1|2}_{Platform}_{Tool}_submission.zip
Extracts to workspace root for subsequent pipeline stages.
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
from workspace import (
    find_workspace_root,
    get_data_dir,
    parse_submission_name,
    get_manifest_key,
)

# Regex patterns for validation (internal zip structure)
# Format: {PID}_{S1|2}_{Platform}_{Tool}_*
PID_PATTERN = r"[Pp]\d{3}"
SESSION_PATTERN = r"[Ss][12]"
PLATFORM_PATTERN = r"[a-z]+(?:-[a-z]+)*"
TOOL_PATTERN = r"[a-z]+(?:-[a-z]+)*"

PATCH_PATTERN = re.compile(
    rf"^({PID_PATTERN})_({SESSION_PATTERN})_({PLATFORM_PATTERN})_({TOOL_PATTERN})_solution\.patch$"
)
LOGS_PATTERN = re.compile(
    rf"^({PID_PATTERN})_({SESSION_PATTERN})_({PLATFORM_PATTERN})_({TOOL_PATTERN})_logs/?$"
)
CHAT_COPILOT_PATTERN = re.compile(
    rf"^({PID_PATTERN})_({SESSION_PATTERN})_({PLATFORM_PATTERN})_({TOOL_PATTERN})_chat_(\d{{2}})\.json$"
)


def validate_zip_structure(zip_path: Path) -> Tuple[bool, List[str], str]:
    """
    Validate the structure of a submission zip file.
    
    Args:
        zip_path: Path to submission zip file.
        
    Returns:
        Tuple of (is_valid, list of issues, detected platform).
    """
    issues: List[str] = []
    platform = "unknown"
    
    parsed = parse_submission_name(zip_path.name)
    if not parsed:
        issues.append(f"Invalid zip filename: {zip_path.name}")
        issues.append("Expected format: {PID}_{S1|2}_{Platform}_{Tool}_submission.zip")
        return (False, issues, platform)
    
    pid, session, platform, tool = parsed
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        issues.append("File is not a valid zip archive")
        return (False, issues, platform)
    
    # Check for patch file
    expected_patch = f"{pid}_{session}_{platform}_{tool}_solution.patch"
    patch_found = False
    for name in names:
        basename = Path(name).name
        if PATCH_PATTERN.match(basename):
            if basename.lower() == expected_patch.lower():
                patch_found = True
                break
    
    # More lenient patch check
    patch_candidates = [n for n in names if n.endswith('.patch') and 'solution' in n.lower()]
    if not patch_found and patch_candidates:
        patch_found = True
        if patch_candidates[0].lower() != expected_patch.lower():
            issues.append(f"Patch filename mismatch: found '{patch_candidates[0]}', expected '{expected_patch}'")
    
    if not patch_found:
        issues.append(f"Missing patch file: {expected_patch}")
    
    # Check for logs folder
    expected_logs = f"{pid}_{session}_{platform}_{tool}_logs"
    logs_found = any(name.startswith(expected_logs) or name.lower().startswith(expected_logs.lower()) for name in names)
    if not logs_found:
        issues.append(f"Missing logs folder: {expected_logs}/")
    
    # Check for chats
    chat_files = [n for n in names if '/chats/' in n and not n.endswith('/')]
    json_chats = [f for f in chat_files if f.endswith('.json')]

    if json_chats:
        platform = "copilot"
    else:
        issues.append("No chat files found in logs/chats/")

    # Validate chat naming
    for chat in json_chats:
        basename = Path(chat).name
        if not CHAT_COPILOT_PATTERN.match(basename):
            issues.append(f"Invalid chat filename: {basename}")
    
    is_valid = len(issues) == 0
    return (is_valid, issues, platform)


def extract_submission(zip_path: Path, output_dir: Path) -> None:
    """
    Extract submission zip to output directory.
    
    Args:
        zip_path: Path to submission zip file.
        output_dir: Directory to extract to (will be created if needed).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and extract participant submission zip files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Expected format: {PID}_{S1|2}_{Platform}_{Tool}_submission.zip\n"
            "Example: P001_S1_copilot_apm_submission.zip\n\n"
            "Extracts to workspace root for subsequent pipeline stages."
        ),
    )
    parser.add_argument(
        "zip_file",
        type=Path,
        help="Path to submission zip file"
    )
    
    args = parser.parse_args()
    
    if not args.zip_file.exists():
        print(f"Error: File not found: {args.zip_file}", file=sys.stderr)
        return 2
    
    # Parse filename
    parsed = parse_submission_name(args.zip_file.name)
    if not parsed:
        print(f"Error: Invalid zip filename: {args.zip_file.name}", file=sys.stderr)
        print("Expected format: {PID}_{S1|2}_{Platform}_{Tool}_submission.zip", file=sys.stderr)
        return 1
    
    pid, session, platform, tool = parsed
    print(f"Validating: {pid} {session} {platform} {tool}")
    
    # Validate structure
    is_valid, issues, detected_platform = validate_zip_structure(args.zip_file)
    
    # Use detected platform if validation succeeded, otherwise use parsed
    if detected_platform != "unknown":
        platform = detected_platform
    
    if issues:
        print("\nIssues found:")
        for issue in issues:
            print(f"  - {issue}")
    
    if not is_valid:
        print("\nValidation FAILED")
        return 1
    
    print(f"\nValidation PASSED")
    print(f"Platform: {platform}")
    
    # Auto-detect workspace and extract to workspace root
    workspace_root = find_workspace_root()
    if workspace_root is None:
        print("Error: Could not auto-detect workspace root.", file=sys.stderr)
        print("Ensure you're in a directory containing:", file=sys.stderr)
        print("  - bsc-apm-case-study-task/", file=sys.stderr)
        print("  - bsc-apm-case-study-data/", file=sys.stderr)
        print("  - eclass-mcp-server/", file=sys.stderr)
        print("  - openeclass/", file=sys.stderr)
        return 2
    
    # Extract to workspace root (unpacked submission stays at root)
    # Output directory name matches zip filename without .zip extension
    output_dir = workspace_root / args.zip_file.stem
    print(f"\nWorkspace root: {workspace_root}")
    print(f"Extracting to: {output_dir}")
    
    # Extract submission
    extract_submission(args.zip_file, output_dir)
    
    # Update manifest (manifest is at platform level in dataset repo)
    manifest_dir = get_data_dir(platform, workspace_root)
    manifest = load_manifest(manifest_dir)
    
    # Generate manifest key from submission directory name
    manifest_key = get_manifest_key(output_dir)
    
    entry = create_stage_entry(
        status="success" if is_valid else "error",
        input_file=args.zip_file.name,
        input_checksum=compute_checksum(args.zip_file),
        output_dir=str(output_dir.relative_to(workspace_root)),
        platform=platform,
        warnings=issues if issues else [],
    )
    
    add_entry(manifest, manifest_key, "validate", entry)
    save_manifest(manifest, manifest_dir)
    print(f"Manifest updated: {manifest_dir / 'pipeline_manifest.json'}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
