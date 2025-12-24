#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Patch Manager - Git operations for applying and managing patch files.

Handles git operations for applying patch files to the baseline repository,
including branch management and cleanup. Supports exclusion of common build
artifacts that may be accidentally included in patches.
"""

import subprocess
from pathlib import Path
from typing import List, Tuple

# Build artifacts to exclude when applying patches.
# These are common compiled outputs that should be rebuilt, not patched.
EXCLUDE_PATTERNS: List[str] = [
    "*.o",           # Object files (C/C++)
    "*.obj",         # Object files (Windows)
    "*.a",           # Static libraries
    "*.so",          # Shared libraries (Linux)
    "*.dylib",       # Shared libraries (macOS)
    "*.exe",         # Executables (Windows)
    "c-replica/server",  # C server binary
]


class PatchManager:
    """Manages git operations for patch-based grading."""
    
    def __init__(self, repo_path: Path):
        """
        Initialize patch manager for a git repository.
        
        Args:
            repo_path: Path to the git repository (e.g., eclass-mcp-server directory).
        """
        self.repo_path = Path(repo_path).resolve()
        self.original_branch: str = ""
        self.test_branch: str = ""
    
    def _git(self, *args, check: bool = True) -> Tuple[bool, str]:
        """
        Run git command and return result.
        
        Args:
            *args: Git command arguments (e.g., "apply", "--check", "file.patch").
            check: If True, raise exception on non-zero exit. If False, return
                   failure status based on returncode.
        
        Returns:
            Tuple of (success: bool, output: str). On failure, output contains stderr.
        """
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=check
            )
            # When check=False, subprocess doesn't raise on non-zero exit
            if result.returncode != 0:
                return False, result.stderr.strip() or result.stdout.strip()
            return True, result.stdout.strip()
        except subprocess.CalledProcessError as e:
            return False, e.stderr.strip() or e.stdout.strip()
        except Exception as e:
            return False, str(e)
    
    def _build_exclude_args(self) -> List[str]:
        """
        Build git apply --exclude arguments for filtering build artifacts.
        
        Returns:
            List of arguments like ["--exclude", "*.o", "--exclude", "*.so", ...].
        """
        args = []
        for pattern in EXCLUDE_PATTERNS:
            args.extend(["--exclude", pattern])
        return args
    
    def create_branch_and_apply_patch(self, patch_path: Path) -> Tuple[bool, str]:
        """
        Create test branch and apply patch with build artifact exclusions.
        
        Creates a new branch from main/master, applies the patch excluding
        common build artifacts (object files, binaries), and reports success
        or failure with cleanup on error.
        
        Args:
            patch_path: Path to the git patch file.
        
        Returns:
            Tuple of (success, message). Message contains branch name on success
            or error description on failure.
        """
        patch_path = Path(patch_path).resolve()
        if not patch_path.exists():
            return False, f"Patch file not found: {patch_path}"
        
        # Store original branch for cleanup
        ok, self.original_branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if not ok:
            self.original_branch = "main"
        
        # Create test branch name from patch filename
        self.test_branch = f"grader-test-{patch_path.stem}"
        
        # Checkout main/master branch
        ok, msg = self._git("checkout", "main", check=False)
        if not ok:
            ok, msg = self._git("checkout", "master", check=False)
            if not ok:
                return False, f"Could not checkout main branch: {msg}"
        
        # Delete existing test branch if present
        self._git("branch", "-D", self.test_branch, check=False)
        
        # Create new test branch
        ok, msg = self._git("checkout", "-b", self.test_branch)
        if not ok:
            return False, f"Could not create test branch: {msg}"
        
        # Build exclusion arguments for build artifacts
        exclude_args = self._build_exclude_args()
        
        # Check if patch can be applied (with exclusions)
        ok, msg = self._git("apply", "--check", *exclude_args, str(patch_path), check=False)
        if not ok:
            # Try 3-way merge for patches with context mismatches
            ok, msg = self._git("apply", "--3way", "--check", *exclude_args, 
                               str(patch_path), check=False)
            if not ok:
                self.cleanup()
                return False, f"Patch cannot be applied: {msg}"
        
        # Apply patch with exclusions
        ok, msg = self._git("apply", *exclude_args, str(patch_path), check=False)
        if not ok:
            # Try 3-way merge for patches with context mismatches
            ok, msg = self._git("apply", "--3way", *exclude_args, str(patch_path), check=False)
            if not ok:
                self.cleanup()
                return False, f"Patch application failed: {msg}"
        
        return True, f"Patch applied on branch {self.test_branch}"
    
    def cleanup(self) -> Tuple[bool, str]:
        """
        Switch back to original branch and delete test branch.
        
        Returns:
            Tuple of (success: bool, message: str) describing cleanup actions.
        """
        messages = []
        
        # Switch to original branch
        if self.original_branch:
            ok, _ = self._git("checkout", self.original_branch, check=False)
            if not ok:
                self._git("checkout", "main", check=False)
            messages.append(f"Switched to {self.original_branch}")
        
        # Delete test branch
        if self.test_branch:
            ok, _ = self._git("branch", "-D", self.test_branch, check=False)
            if ok:
                messages.append(f"Deleted {self.test_branch}")
        
        # Reset any changes
        self._git("checkout", "--", ".", check=False)
        self._git("clean", "-fd", check=False)
        
        return True, "; ".join(messages)
