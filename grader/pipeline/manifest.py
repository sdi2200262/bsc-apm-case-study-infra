#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Manifest operations module for the data processing pipeline.

Provides atomic read/write operations for the pipeline manifest file,
checksum computation, and entry management with file locking.

Manifest key format: {PID}_{S1|2}_{Platform}_{Tool} (e.g., 'P001_S1_copilot_apm').
"""

import fcntl
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

MANIFEST_FILENAME = "pipeline_manifest.json"


def compute_checksum(filepath: Path) -> str:
    """
    Compute SHA256 checksum of a file.
    
    Returns:
        Checksum string with 'sha256:' prefix.
    """
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"


def validate_checksum(filepath: Path, expected: str) -> bool:
    """
    Verify file integrity against expected checksum.
    
    Args:
        filepath: Path to file to verify.
        expected: Expected checksum with 'sha256:' prefix.
        
    Returns:
        True if checksums match, False otherwise.
    """
    if not filepath.exists():
        return False
    actual = compute_checksum(filepath)
    return actual == expected


def _create_empty_manifest() -> Dict[str, Any]:
    """Create a new empty manifest structure."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "created_at": now,
        "updated_at": now,
        "entries": {}
    }


def load_manifest(path: Path) -> Dict[str, Any]:
    """
    Load manifest from file or create empty manifest if not exists.
    
    Args:
        path: Directory containing the manifest file.
        
    Returns:
        Manifest dictionary.
    """
    manifest_path = path / MANIFEST_FILENAME
    
    if not manifest_path.exists():
        return _create_empty_manifest()
    
    with open(manifest_path, 'r', encoding='utf-8') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def save_manifest(manifest: Dict[str, Any], path: Path) -> None:
    """
    Save manifest to file with atomic write and file locking.
    
    Args:
        manifest: Manifest dictionary to save.
        path: Directory to save manifest in.
    """
    manifest_path = path / MANIFEST_FILENAME
    temp_path = path / f".{MANIFEST_FILENAME}.tmp"
    
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    with open(temp_path, 'w', encoding='utf-8') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    
    temp_path.rename(manifest_path)


def add_entry(
    manifest: Dict[str, Any],
    manifest_key: str,
    stage: str,
    entry: Dict[str, Any]
) -> None:
    """
    Add or update an entry in the manifest.
    
    Args:
        manifest: Manifest dictionary to modify.
        manifest_key: Manifest entry key (e.g., 'P001_S1_copilot_apm').
        stage: Pipeline stage (validate, grade, parse, combine, add_to_dataset).
        entry: Entry data to store.
    """
    if manifest_key not in manifest["entries"]:
        manifest["entries"][manifest_key] = {}
    
    manifest["entries"][manifest_key][stage] = entry


def get_entry(
    manifest: Dict[str, Any],
    manifest_key: str,
    stage: str
) -> Optional[Dict[str, Any]]:
    """
    Retrieve an entry from the manifest.
    
    Args:
        manifest: Manifest dictionary.
        manifest_key: Manifest entry key (e.g., 'P001_S1_copilot_apm').
        stage: Pipeline stage.
        
    Returns:
        Entry dictionary or None if not found.
    """
    if manifest_key not in manifest["entries"]:
        return None
    
    return manifest["entries"][manifest_key].get(stage)


def get_all_stages(manifest: Dict[str, Any], manifest_key: str) -> Dict[str, Dict[str, Any]]:
    """
    Get all stages for a manifest entry.
    
    Args:
        manifest: Manifest dictionary.
        manifest_key: Manifest entry key (e.g., 'P001_S1_copilot_apm').
        
    Returns:
        Dictionary of all stages for the entry, or empty dict if not found.
    """
    return manifest["entries"].get(manifest_key, {})


def create_stage_entry(
    status: str,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Create a new stage entry with standard fields.
    
    Args:
        status: Status string ('success', 'warning', 'error').
        **kwargs: Additional fields to include (e.g., input_file, output_file,
                 checksums, warnings, errors, platform, etc.).
        
    Returns:
        Entry dictionary with timestamp, status, and any additional fields
        provided via kwargs.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    entry.update(kwargs)
    return entry
