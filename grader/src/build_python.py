#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Python build verification for the eclass-mcp-server checkout.

The grader runs ``uv sync`` against the participant's checkout to
install the Python implementation's dependencies; ``pip install
-e .`` is the fallback when ``uv`` is not on ``PATH``. A successful
return indicates the dependencies resolved and the package is
importable inside the checkout's environment; the actual server
spawn happens in the protocol-test phase.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

BUILD_TIMEOUT_SECONDS = 120


def build(eclass_root: Path) -> tuple[bool, str, str]:
    """Install the Python implementation's dependencies.

    Args:
        eclass_root: Resolved path to the eclass-mcp-server
            checkout containing the ``pyproject.toml``.

    Returns:
        Tuple of ``(ok, summary, detail)``. ``summary`` is a short
        success or failure description suitable for a per-test row;
        ``detail`` carries the full subprocess output for the
        operator's diagnostics.
    """
    eclass_root = Path(eclass_root).resolve()
    pyproject = eclass_root / "pyproject.toml"
    if not pyproject.exists():
        message = "pyproject.toml not found in eclass-mcp-server directory"
        return False, "pyproject.toml not found", message

    env = _extended_env()

    try:
        result = subprocess.run(
            ["uv", "sync"],
            cwd=eclass_root,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT_SECONDS,
            env=env,
        )
    except FileNotFoundError:
        return _pip_fallback(eclass_root, env)
    except subprocess.TimeoutExpired:
        return False, f"uv sync timed out ({BUILD_TIMEOUT_SECONDS}s)", \
            f"uv sync timed out after {BUILD_TIMEOUT_SECONDS} seconds"

    if result.returncode == 0:
        return True, "uv sync completed successfully", result.stdout or "uv sync completed"
    return False, f"uv sync failed: {result.stderr[:300]}", result.stderr


def _pip_fallback(eclass_root: Path, env: dict[str, str]) -> tuple[bool, str, str]:
    """Install with ``pip install -e .`` when ``uv`` is unavailable."""
    try:
        result = subprocess.run(
            ["pip", "install", "-e", "."],
            cwd=eclass_root,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT_SECONDS,
            env=env,
        )
    except FileNotFoundError:
        return False, "neither uv nor pip found", "neither uv nor pip found in PATH"
    except subprocess.TimeoutExpired:
        return False, f"pip install timed out ({BUILD_TIMEOUT_SECONDS}s)", \
            f"pip install -e . timed out after {BUILD_TIMEOUT_SECONDS} seconds"
    if result.returncode == 0:
        return True, "pip install -e . completed (uv not found)", result.stdout or "pip install completed"
    return False, f"pip install failed: {result.stderr[:300]}", result.stderr


def _extended_env() -> dict[str, str]:
    """Return a copy of the OS env with ``~/.local/bin`` and ``~/.cargo/bin`` on ``PATH``."""
    env = os.environ.copy()
    home = Path.home()
    extras = [str(home / ".local" / "bin"), str(home / ".cargo" / "bin")]
    env["PATH"] = ":".join(extras + [env.get("PATH", "")])
    return env
