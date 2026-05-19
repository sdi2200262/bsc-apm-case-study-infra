#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Git operations for the patch-grading flow.

The grader applies a participant's patch on a fresh test branch
created from the pinned eclass-mcp-server commit
(``PATCH_BASELINE_PIN``). The participant's instructions check the
same commit out before they begin work, so grader and participant
share a byte-identical baseline regardless of where the upstream
``main`` branch has advanced. After the phase tests run, the
cleanup helper deletes the test branch and returns the working
tree to the pinned commit (detached HEAD).

Build artefacts (object files, shared libraries, the C-replica
binary) are excluded from the apply so a participant who packaged
their build outputs into the patch does not have those overwrite
the grading run's own builds.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Commit the participant applies their patch against, per the
# participant guide's setup steps. Embedding the pin here means a
# stale or advanced ``main`` on the operator's local clone cannot
# silently change the grading baseline; rebasing the pin requires
# updating this constant in lock-step with the participant package
# and SCORING.md.
PATCH_BASELINE_PIN = "dbd2d16"

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
    """Create a test branch from the pinned baseline commit and apply the patch.

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

    ok, message = _git(repo_path, "checkout", PATCH_BASELINE_PIN)
    if not ok:
        return (
            False,
            f"could not checkout patch baseline pin {PATCH_BASELINE_PIN}: {message}",
            message,
        )

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
    """Return the working tree to the pinned baseline and delete test branches.

    Idempotent: safe to call when no patch was applied. Checks out
    the patch baseline pin (detached HEAD) so the next grading run
    starts from the same commit, then deletes every branch with
    the test prefix.

    Args:
        repo_path: Resolved path to the eclass-mcp-server checkout.

    Returns:
        Tuple of ``(ok, summary)``. ``ok`` is ``True`` when the
        repo was successfully returned to a clean state; the
        message names the actions taken.
    """
    repo_path = Path(repo_path).resolve()
    actions: list[str] = []

    ok, _ = _git(repo_path, "checkout", PATCH_BASELINE_PIN)
    if ok:
        actions.append(f"checked out patch baseline pin {PATCH_BASELINE_PIN}")

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
    """Run ``git`` with the given arguments and return ``(ok, output)``.

    Args:
        repo_path: Working directory the git invocation runs in.
        *args: Argument tokens passed to ``git`` after the program name.

    Returns:
        ``(True, stdout)`` on a clean exit; ``(False, detail)`` when
        ``git`` could not be launched, was killed by a signal, or
        exited non-zero. The failure detail combines both child
        streams and names the signal on a negative return code.
    """
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
    if result.returncode < 0:
        return False, (
            f"git {args[0] if args else ''} killed by signal "
            f"{-result.returncode}: "
            f"{(result.stderr + result.stdout).strip()}"
        )
    if result.returncode != 0:
        return False, (result.stderr + result.stdout).strip()
    return True, result.stdout.strip()
