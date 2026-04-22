#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Extract interaction metrics and sanitize chat logs.

Takes unpacked submission directory, extracts metrics, sanitizes chats, and outputs:
- Metrics JSON to dataset repo: {platform}/{PID}/S{session}_{tool}/{PID}_{S1|2}_{platform}_{tool}_metrics.json
- TXT summary to workspace root: results_{PID}_{S1|2}_{platform}_{tool}.txt (metrics summary)
- Sanitized chats to dataset repo: {platform}/{PID}/S{session}_{tool}/chats/sanitized_*.json
"""

import argparse
import json
import os
import shutil
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
    get_submission_dataset_dir,
    get_manifest_key,
    parse_submission_name,
)


def detect_platform(chats_dir: Path) -> Tuple[str, List[Path]]:
    """
    Detect platform from chat file extensions.

    Args:
        chats_dir: Path to chats directory.

    Returns:
        Tuple of (platform, list of chat files).
    """
    if not chats_dir.exists():
        return ("unknown", [])

    json_files = list(chats_dir.glob("*.json"))

    if json_files:
        return ("copilot", json_files)

    return ("unknown", [])


def run_parser(
    scripts_dir: Path,
    chat_files: List[Path],
    output_metrics: Path,
    sanitize: bool = True
) -> Tuple[bool, str]:
    """
    Run the Copilot Chat Parser package on the submission's chat files.

    Args:
        scripts_dir: Directory that contains the ``copilot_chat_parser``
            package. Added to ``PYTHONPATH`` for the subprocess so
            ``python -m copilot_chat_parser`` resolves.
        chat_files: List of chat file paths to process.
        output_metrics: Path to output metrics JSON file.
        sanitize: Whether to sanitize chat files after metrics extraction.

    Returns:
        Tuple of (success, error_message).
    """
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{scripts_dir}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(scripts_dir)
    )

    cmd = [
        sys.executable, "-m", "copilot_chat_parser",
        *[str(f) for f in chat_files],
        "--metrics",
        "--format", "json",
        "-o", str(output_metrics)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        return (False, f"Metrics extraction failed: {result.stderr}")

    if sanitize:
        if not os.environ.get('CHAT_PARSER_SECRET'):
            return (False, "CHAT_PARSER_SECRET environment variable not set")
        cmd = [
            sys.executable, "-m", "copilot_chat_parser",
            *[str(f) for f in chat_files],
            "--sanitize"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            return (False, f"Sanitization failed: {result.stderr}")

    return (True, "")


def create_metrics_summary(metrics_path: Path) -> str:
    """
    Create human-readable summary of metrics.

    Args:
        metrics_path: Path to metrics JSON file.

    Returns:
        Summary text string.
    """
    try:
        with open(metrics_path, 'r') as f:
            metrics = json.load(f)
    except Exception as e:
        return f"Error reading metrics: {e}"

    project_meta = metrics.get('project_metadata', {})
    m = metrics.get('metrics', {})

    lines = []
    lines.append("=" * 70)
    lines.append("INTERACTION METRICS SUMMARY")
    lines.append("=" * 70)
    lines.append("")

    # Session envelope
    model_ids = project_meta.get('unique_model_ids', [])
    lines.append(f"Conversations:           {project_meta.get('file_count', 0)}")
    lines.append(f"Total requests:          {m.get('total_requests', 0)}")
    lines.append(f"Session duration (min):  {m.get('session_duration_minutes', 0.0)}")
    lines.append(f"Models:                  {', '.join(model_ids) if model_ids else 'none'}")
    lines.append("")

    # Reliability sub-metrics
    lines.append("Reliability")
    lines.append(f"  Tool success rate:     {m.get('tool_success_rate', 0.0)}")
    lines.append(f"  Tool retry rate:       {m.get('tool_retry_rate', 0.0)}")
    lines.append(f"  User edit rate:        {m.get('user_edit_rate', 0.0)}")
    lines.append("")

    # Behavior distribution (share of user inputs per bucket)
    lines.append("Behavior distribution")
    lines.append(f"  Short inputs:          {m.get('ratio_short_inputs', 0.0)}")
    lines.append(f"  Protocol inputs:       {m.get('ratio_protocol_inputs', 0.0)}")
    lines.append(f"  Standard inputs:       {m.get('ratio_standard_inputs', 0.0)}")
    lines.append("")

    # Behavior magnitude (average characters per bucket)
    lines.append("Behavior magnitude (avg chars)")
    lines.append(f"  Short inputs:          {m.get('avg_chars_short', 0.0)}")
    lines.append(f"  Protocol inputs:       {m.get('avg_chars_protocol', 0.0)}")
    lines.append(f"  Standard inputs:       {m.get('avg_chars_standard', 0.0)}")
    lines.append("")

    lines.append("=" * 70)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract interaction metrics and sanitize chat logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Takes unpacked submission directory path as argument.\n"
            "Example: ./parse_submission.py P001_S1_copilot_apm_submission\n\n"
            "Outputs:\n"
            "  - Metrics JSON: dataset repo/{platform}/{PID}/S{session}_{tool}/{PID}_{S1|2}_{platform}_{tool}_metrics.json\n"
            "  - TXT summary: workspace root/results_{PID}_{S1|2}_{platform}_{tool}.txt\n"
            "  - Sanitized chats: dataset repo/{platform}/{PID}/S{session}_{tool}/chats/sanitized_*.json"
        ),
    )
    parser.add_argument(
        "submission_dir",
        type=Path,
        help="Path to unpacked submission directory (at workspace root)"
    )
    parser.add_argument(
        "--no-sanitize",
        action="store_true",
        help="Skip sanitization (metrics only)"
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
    dataset_dir.mkdir(parents=True, exist_ok=True)
    
    # Create chats directory in dataset repo
    dataset_chats_dir = dataset_dir / "chats"
    dataset_chats_dir.mkdir(parents=True, exist_ok=True)
    
    # Find chats directory in submission
    logs_dirs = list(submission_dir.glob(f"*_logs"))
    if not logs_dirs:
        print(f"Error: No logs directory found in {submission_dir}", file=sys.stderr)
        return 1
    
    logs_dir = logs_dirs[0]
    chats_dir = logs_dir / "chats"
    
    if not chats_dir.exists():
        print(f"Error: No chats directory found: {chats_dir}", file=sys.stderr)
        return 1
    
    # Detect platform
    detected_platform, chat_files = detect_platform(chats_dir)
    
    if detected_platform == "unknown":
        print(f"Error: No chat files found in {chats_dir}", file=sys.stderr)
        return 1
    
    if detected_platform == "mixed":
        print(f"Error: Mixed chat formats found (both .json and .md)", file=sys.stderr)
        return 1
    
    # Use detected platform if it matches parsed platform
    if detected_platform != platform:
        print(f"Warning: Platform mismatch - parsed: {platform}, detected: {detected_platform}", file=sys.stderr)
        platform = detected_platform  # Use detected platform
    
    print(f"Parsing: {pid} {session} {platform} {tool}")
    print(f"Chat files: {len(chat_files)}")
    
    # Locate parser package
    script_dir = Path(__file__).parent
    scripts_dir = script_dir.parent / "scripts"
    parser_package_init = scripts_dir / "copilot_chat_parser" / "__init__.py"

    if not parser_package_init.exists():
        print(f"Error: Parser package not found at: {scripts_dir / 'copilot_chat_parser'}", file=sys.stderr)
        return 2

    # Output paths
    output_metrics = dataset_dir / f"{pid}_{session}_{platform}_{tool}_metrics.json"
    output_txt = workspace_root / f"results_{pid}_{session}_{platform}_{tool}.txt"

    # Files created by this script (for cleanup on error)
    created_files = []

    # Run parser
    print(f"\nExtracting metrics...")
    try:
        success, error = run_parser(
            scripts_dir,
            chat_files,
            output_metrics,
            sanitize=not args.no_sanitize
        )
        
        if not success:
            print(f"Error: {error}", file=sys.stderr)
            return 1
        
        created_files.append(output_metrics)
    except Exception as e:
        print(f"Error: Failed to run parser: {e}", file=sys.stderr)
        # Cleanup on error
        for f in created_files:
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass
        return 1
    
    print(f"Metrics saved: {output_metrics}")
    
    # Move sanitized files to dataset repo chats directory
    sanitized_files = []
    if not args.no_sanitize:
        for chat_file in chat_files:
            sanitized_name = f"sanitized_{chat_file.stem}.json"
            sanitized_source = chat_file.parent / sanitized_name
            sanitized_dest = dataset_chats_dir / sanitized_name
            
            if sanitized_source.exists():
                try:
                    shutil.move(str(sanitized_source), str(sanitized_dest))
                    sanitized_files.append(sanitized_name)
                    created_files.append(sanitized_dest)
                    print(f"Sanitized: {sanitized_name}")
                except Exception as e:
                    print(f"Warning: Failed to move sanitized file {sanitized_name}: {e}", file=sys.stderr)
    
    # Create TXT summary
    try:
        summary_text = create_metrics_summary(output_metrics)
        with open(output_txt, 'w') as f:
            f.write(summary_text)
        created_files.append(output_txt)
        print(f"Summary saved: {output_txt}")
    except Exception as e:
        print(f"Warning: Failed to create summary: {e}", file=sys.stderr)
    
    # Update manifest
    manifest_dir = dataset_dir.parent.parent  # submissions_sanitized/{platform}/
    manifest = load_manifest(manifest_dir)
    manifest_key = get_manifest_key(submission_dir)
    
    entry = create_stage_entry(
        status="success",
        platform=platform,
        input_files=[f.name for f in chat_files],
        output_file=output_metrics.name,
        output_checksum=compute_checksum(output_metrics),
        sanitized_files=sanitized_files,
    )
    
    add_entry(manifest, manifest_key, "parse", entry)
    save_manifest(manifest, manifest_dir)
    
    print("\nManifest updated")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
