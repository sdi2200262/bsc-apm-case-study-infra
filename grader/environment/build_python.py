# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Python build verification for the eclass-mcp-server checkout.

The grader runs ``uv sync`` against the participant's checkout to
install the Python implementation's dependencies. A successful
return indicates the dependencies resolved and the package is
importable inside the checkout's environment; the actual server
spawn happens in the protocol-test phase.
"""

from __future__ import annotations

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

    try:
        result = subprocess.run(
            ["uv", "sync"],
            cwd=eclass_root,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return False, "uv not found on PATH", "uv not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"uv sync timed out ({BUILD_TIMEOUT_SECONDS}s)", \
            f"uv sync timed out after {BUILD_TIMEOUT_SECONDS} seconds"

    if result.returncode == 0:
        return True, "uv sync completed successfully", result.stdout or "uv sync completed"
    combined = (result.stderr + "\n" + result.stdout).strip()
    if result.returncode < 0:
        summary = f"uv sync killed by signal {-result.returncode}"
        return False, summary, combined or summary
    return False, f"uv sync failed: {combined[:300]}", combined
