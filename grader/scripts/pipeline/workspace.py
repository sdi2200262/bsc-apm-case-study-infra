#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Workspace detection and path resolution utilities.

Auto-detects workspace root and provides default paths for all pipeline operations.
Supports new submission format: {PID}_{S1|2}_{Platform}_{Tool}_submission.zip
"""

import re
from pathlib import Path
from typing import Optional, Tuple

# Submission format: {PID}_{S1|2}_{Platform}_{Tool}_submission.zip
# Example: P001_S1_copilot_apm_submission.zip
SUBMISSION_PATTERN = re.compile(
    r"^([Pp]\d{3})_(S[12])_([a-z]+(?:-[a-z]+)*)_([a-z]+(?:-[a-z]+)*)_submission(?:\.zip)?$"
)


def find_workspace_root(start_path: Optional[Path] = None) -> Optional[Path]:
    """
    Find workspace root by looking for required directories.
    
    Workspace should contain:
    - bsc-apm-case-study-task/
    - bsc-apm-case-study-data/
    - eclass-mcp-server/
    - openeclass/
    
    Args:
        start_path: Path to start searching from (defaults to current working directory)
        
    Returns:
        Path to workspace root or None if not found
    """
    if start_path is None:
        start_path = Path.cwd()
    
    current = Path(start_path).resolve()
    
    # Check up to 5 levels up
    for _ in range(5):
        required_dirs = [
            "bsc-apm-case-study-task",
            "bsc-apm-case-study-data",
            "eclass-mcp-server",
            "openeclass",
        ]
        
        if all((current / d).exists() for d in required_dirs):
            return current
        
        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent
    
    return None


def get_workspace_paths(workspace_root: Optional[Path] = None) -> dict:
    """
    Get all workspace paths.
    
    Args:
        workspace_root: Workspace root directory (auto-detected if None)
        
    Returns:
        Dictionary with paths:
        - workspace_root
        - data_repo: bsc-apm-case-study-data
        - grader_dir: bsc-apm-case-study-task/grader
        - eclass_dir: eclass-mcp-server
        - openeclass_dir: openeclass
    """
    if workspace_root is None:
        workspace_root = find_workspace_root()
        if workspace_root is None:
            raise RuntimeError(
                "Could not find workspace root. Ensure you're in a directory containing:\n"
                "  - bsc-apm-case-study-task/\n"
                "  - bsc-apm-case-study-data/\n"
                "  - eclass-mcp-server/\n"
                "  - openeclass/"
            )
    
    workspace_root = Path(workspace_root).resolve()
    
    return {
        "workspace_root": workspace_root,
        "data_repo": workspace_root / "bsc-apm-case-study-data",
        "grader_dir": workspace_root / "bsc-apm-case-study-task" / "grader",
        "eclass_dir": workspace_root / "eclass-mcp-server",
        "openeclass_dir": workspace_root / "openeclass",
    }


def get_data_dir(platform: str, workspace_root: Optional[Path] = None) -> Path:
    """
    Get data directory for a platform.
    
    Args:
        platform: Platform name ('copilot' or 'cursor')
        workspace_root: Workspace root (auto-detected if None)
        
    Returns:
        Path to submissions_sanitized/{platform}/
    """
    paths = get_workspace_paths(workspace_root)
    return paths["data_repo"] / "submissions_sanitized" / platform


def parse_submission_name(name: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse submission name to extract components.
    
    Supports both zip filenames and directory names:
    - {PID}_{S1|2}_{Platform}_{Tool}_submission.zip
    - {PID}_{S1|2}_{Platform}_{Tool}_submission/
    
    Args:
        name: Submission zip filename or directory name
        
    Returns:
        Tuple of (pid, session, platform, tool) or None if invalid format.
        pid is uppercase, session is uppercase (S1/S2), platform and tool are lowercase.
    """
    match = SUBMISSION_PATTERN.match(name)
    if not match:
        return None
    
    pid = match.group(1).upper()
    session = match.group(2).upper()
    platform = match.group(3).lower()
    tool = match.group(4).lower()
    
    return (pid, session, platform, tool)


def detect_platform_from_zip(zip_path: Path) -> Optional[str]:
    """
    Detect platform from submission zip file.
    
    First tries to parse filename, then falls back to inspecting zip contents.
    
    Args:
        zip_path: Path to submission zip file
        
    Returns:
        'copilot' or 'cursor' or None if cannot determine
    """
    # Try parsing filename first
    parsed = parse_submission_name(zip_path.name)
    if parsed:
        _, _, platform, _ = parsed
        return platform
    
    # Fall back to inspecting zip contents
    import zipfile
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, FileNotFoundError):
        return None
    
    # Check for chat files
    chat_files = [n for n in names if '/chats/' in n and not n.endswith('/')]
    json_chats = [f for f in chat_files if f.endswith('.json')]
    md_chats = [f for f in chat_files if f.endswith('.md')]
    
    if json_chats and not md_chats:
        return "copilot"
    elif md_chats and not json_chats:
        return "cursor"
    
    return None


def get_submission_dataset_dir(
    submission_dir: Path,
    workspace_root: Optional[Path] = None
) -> Path:
    """
    Get dataset directory path for a submission.
    
    Extracts submission components from directory name and constructs
    dataset path: submissions_sanitized/{platform}/{PID}/S{session}_{tool}/
    
    Args:
        submission_dir: Path to unpacked submission directory at workspace root
        workspace_root: Workspace root (auto-detected if None)
        
    Returns:
        Path to dataset submission directory
        
    Raises:
        ValueError: If submission directory name doesn't match expected format
    """
    parsed = parse_submission_name(submission_dir.name)
    if not parsed:
        raise ValueError(
            f"Invalid submission directory name: {submission_dir.name}\n"
            f"Expected format: {{PID}}_{{S1|2}}_{{Platform}}_{{Tool}}_submission"
        )
    
    pid, session, platform, tool = parsed
    data_dir = get_data_dir(platform, workspace_root)
    
    # Dataset structure: {platform}/{PID}/S{session}_{tool}/
    return data_dir / pid / f"S{session}_{tool}"


def get_manifest_key(submission_dir: Path) -> str:
    """
    Generate manifest entry key from submission directory name.
    
    Args:
        submission_dir: Path to unpacked submission directory
        
    Returns:
        Manifest key string (e.g., 'P001_S1_copilot_apm')
        
    Raises:
        ValueError: If submission directory name doesn't match expected format
    """
    parsed = parse_submission_name(submission_dir.name)
    if not parsed:
        raise ValueError(
            f"Invalid submission directory name: {submission_dir.name}\n"
            f"Expected format: {{PID}}_{{S1|2}}_{{Platform}}_{{Tool}}_submission"
        )
    
    pid, session, platform, tool = parsed
    return f"{pid}_{session}_{platform}_{tool}"

