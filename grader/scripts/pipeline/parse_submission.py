#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Extract interaction metrics and sanitize chat logs.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional

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
    get_data_dir,
)


def detect_sub_study(chats_dir: Path) -> Tuple[str, List[Path]]:
    """
    Detect sub-study from chat file extensions.
    
    Returns:
        Tuple of (sub_study, list of chat files)
    """
    if not chats_dir.exists():
        return ("unknown", [])
    
    json_files = list(chats_dir.glob("*.json"))
    md_files = list(chats_dir.glob("*.md"))
    
    if json_files and not md_files:
        return ("copilot", json_files)
    elif md_files and not json_files:
        return ("cursor", md_files)
    elif json_files and md_files:
        return ("mixed", json_files + md_files)
    else:
        return ("unknown", [])


def run_parser(
    parser_script: Path,
    chat_files: List[Path],
    output_metrics: Path,
    sanitize: bool = True
) -> Tuple[bool, str]:
    """
    Run the appropriate parser script.
    
    Returns:
        Tuple of (success, error_message)
    """
    # Extract metrics
    cmd = [
        sys.executable, str(parser_script),
        *[str(f) for f in chat_files],
        "--metrics",
        "--format", "json",
        "-o", str(output_metrics)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return (False, f"Metrics extraction failed: {result.stderr}")
    
    # Sanitize
    if sanitize:
        if not os.environ.get('CHAT_PARSER_SECRET'):
            return (False, "CHAT_PARSER_SECRET environment variable not set")
        
        cmd = [
            sys.executable, str(parser_script),
            *[str(f) for f in chat_files],
            "--sanitize"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return (False, f"Sanitization failed: {result.stderr}")
    
    return (True, "")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract interaction metrics and sanitize chat logs.",
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
        "--workspace-dir",
        type=Path,
        default=None,
        help="Workspace root directory (auto-detected if not specified)"
    )
    parser.add_argument(
        "--no-sanitize",
        action="store_true",
        help="Skip sanitization (metrics only)"
    )
    
    args = parser.parse_args()
    
    pid = args.participant_id.upper()
    tool = args.tool.lower()
    
    # Auto-detect workspace and data directory
    workspace_root = find_workspace_root(args.workspace_dir)
    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
    elif workspace_root:
        # Get sub-study from manifest
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
    
    # Find chats directory
    logs_dirs = list(participant_dir.glob(f"*_logs"))
    if not logs_dirs:
        print(f"Error: No logs directory found in {participant_dir}", file=sys.stderr)
        return 1
    
    logs_dir = logs_dirs[0]
    chats_dir = logs_dir / "chats"
    
    if not chats_dir.exists():
        print(f"Error: No chats directory found: {chats_dir}", file=sys.stderr)
        return 1
    
    # Detect sub-study
    sub_study, chat_files = detect_sub_study(chats_dir)
    
    if sub_study == "unknown":
        print(f"Error: No chat files found in {chats_dir}", file=sys.stderr)
        return 1
    
    if sub_study == "mixed":
        print(f"Error: Mixed chat formats found (both .json and .md)", file=sys.stderr)
        return 1
    
    print(f"Parsing: {pid} tool_{tool}")
    print(f"Sub-study: {sub_study}")
    print(f"Chat files: {len(chat_files)}")
    
    # Locate parser script
    script_dir = Path(__file__).parent
    if sub_study == "copilot":
        parser_script = script_dir.parent / "copilot_chat_parser.py"
    else:
        parser_script = script_dir.parent / "cursor_chat_parser.py"
    
    if not parser_script.exists():
        print(f"Error: Parser not found: {parser_script}", file=sys.stderr)
        return 2
    
    # Output paths
    output_metrics = participant_dir / f"{pid}_tool_{tool}_metrics.json"
    
    # Run parser
    print(f"\nExtracting metrics...")
    success, error = run_parser(
        parser_script,
        chat_files,
        output_metrics,
        sanitize=not args.no_sanitize
    )
    
    if not success:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    
    print(f"Metrics saved: {output_metrics}")
    
    # Move sanitized files to chats directory
    sanitized_files = []
    if not args.no_sanitize:
        for chat_file in chat_files:
            sanitized_name = f"sanitized_{chat_file.stem}.json"
            sanitized_path = chat_file.parent / sanitized_name
            if sanitized_path.exists():
                sanitized_files.append(sanitized_name)
                print(f"Sanitized: {sanitized_name}")
        
        # Remove original chat files after sanitization
        for chat_file in chat_files:
            sanitized_path = chat_file.parent / f"sanitized_{chat_file.stem}.json"
            if sanitized_path.exists():
                chat_file.unlink()
                print(f"Removed original: {chat_file.name}")
    
    # Update manifest
    manifest = load_manifest(data_dir)
    
    entry = create_stage_entry(
        status="success",
        sub_study=sub_study,
        input_files=[f.name for f in chat_files],
        output_file=output_metrics.name,
        output_checksum=compute_checksum(output_metrics),
        sanitized_files=sanitized_files,
    )
    
    add_entry(manifest, pid, tool, "parse", entry)
    save_manifest(manifest, data_dir)
    
    print("\nManifest updated")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
