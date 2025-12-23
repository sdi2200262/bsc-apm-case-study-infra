#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Workspace detection and path resolution utilities.

Auto-detects workspace root and provides default paths for all pipeline operations.
"""

from pathlib import Path
from typing import Optional, Tuple


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


def get_data_dir(sub_study: str, workspace_root: Optional[Path] = None) -> Path:
    """
    Get data directory for a sub-study.
    
    Args:
        sub_study: Sub-study name ('copilot' or 'cursor')
        workspace_root: Workspace root (auto-detected if None)
        
    Returns:
        Path to submissions_sanitized/{sub_study}/
    """
    paths = get_workspace_paths(workspace_root)
    return paths["data_repo"] / "submissions_sanitized" / sub_study


def detect_sub_study_from_zip(zip_path: Path) -> Optional[str]:
    """
    Detect sub-study from submission zip file.
    
    Args:
        zip_path: Path to submission zip file
        
    Returns:
        'copilot' or 'cursor' or None if cannot determine
    """
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


def get_participant_dir(pid: str, tool: str, sub_study: str, workspace_root: Optional[Path] = None) -> Path:
    """
    Get participant directory path.
    
    Args:
        pid: Participant ID (e.g., 'P001')
        tool: Tool identifier ('a' or 'b')
        sub_study: Sub-study name ('copilot' or 'cursor')
        workspace_root: Workspace root (auto-detected if None)
        
    Returns:
        Path to {data_dir}/{pid}/tool_{tool}/
    """
    data_dir = get_data_dir(sub_study, workspace_root)
    return data_dir / pid / f"tool_{tool}"

