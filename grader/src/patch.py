#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Git operations for the patch-grading flow.

The grader applies a participant's patch on a fresh test branch
inside the eclass-mcp-server checkout, runs the phase tests, then
cleans up the branch and resets the working tree.

Build artefacts (object files, shared libraries, the C-replica
binary) are excluded from the apply so a participant who packaged
their build outputs into the patch does not have those overwrite
the grading run's own builds.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

EXCLUDE_PATTERNS: tuple[str, ...] = (
    "*.o",
    "*.obj",
    "*.a",
    "*.so",
    "*.dylib",
    "*.exe",
    "c-replica/server",
)

TEST_BRANCH_PREFIX = "grader-test-"


def apply_patch(repo_path: Path, patch_path: Path) -> tuple[bool, str, str]:
    """Create a test branch from main and apply the patch on it.

    Args:
        repo_path: Resolved path to the eclass-mcp-server checkout.
        patch_path: Resolved path to the patch file to apply.

    Returns:
        Tuple of ``(ok, summary, detail)``. ``summary`` is a short
        success or failure description; ``detail`` carries the full
        git output for diagnostics.
    """
    repo_path = Path(repo_path).resolve()
    patch_path = Path(patch_path).resolve()
    if not patch_path.exists():
        message = f"patch file not found: {patch_path}"
        return False, message, message

    test_branch = f"{TEST_BRANCH_PREFIX}{patch_path.stem}"

    ok, message = _git(repo_path, "checkout", "main")
    if not ok:
        return False, f"could not checkout main branch: {message}", message

    _git(repo_path, "branch", "-D", test_branch)

    ok, message = _git(repo_path, "checkout", "-b", test_branch)
    if not ok:
        return False, f"could not create test branch: {message}", message

    exclude_args: list[str] = []
    for pattern in EXCLUDE_PATTERNS:
        exclude_args.extend(["--exclude", pattern])

    ok, message = _git(repo_path, "apply", "--check", *exclude_args, str(patch_path))
    if not ok:
        cleanup(repo_path)
        return False, f"patch cannot be applied: {message}", message

    ok, message = _git(repo_path, "apply", *exclude_args, str(patch_path))
    if not ok:
        cleanup(repo_path)
        return False, f"patch application failed: {message}", message

    return True, f"patch applied on branch {test_branch}", message


def cleanup(repo_path: Path) -> tuple[bool, str]:
    """Restore the main branch and delete any leftover test branches.

    Idempotent: safe to call when no patch was applied. Deletes
    every branch with the test prefix.

    Args:
        repo_path: Resolved path to the eclass-mcp-server checkout.

    Returns:
        Tuple of ``(ok, summary)``. ``ok`` is ``True`` when the
        repo was successfully returned to a clean state; the
        message names the actions taken.
    """
    repo_path = Path(repo_path).resolve()
    actions: list[str] = []

    ok, _ = _git(repo_path, "checkout", "main")
    if ok:
        actions.append("switched to main")

    branches_ok, branches_out = _git(repo_path, "branch", "--list", f"{TEST_BRANCH_PREFIX}*")
    if branches_ok and branches_out:
        for line in branches_out.splitlines():
            branch = line.strip().lstrip("* ").strip()
            if not branch:
                continue
            deleted_ok, _ = _git(repo_path, "branch", "-D", branch)
            if deleted_ok:
                actions.append(f"deleted {branch}")

    _git(repo_path, "checkout", "--", ".")
    _git(repo_path, "clean", "-fd")

    return True, "; ".join(actions) if actions else "nothing to clean"


def _git(repo_path: Path, *args: str) -> tuple[bool, str]:
    """Run ``git`` with the given arguments and return ``(ok, output)``."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return False, str(error)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, result.stdout.strip()
