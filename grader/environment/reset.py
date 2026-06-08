# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Subprocess invocation of the grading environment's reset script.

The grader calls ``<mock-root>/scripts/reset`` once at the start
of each grading run to guarantee a deterministic starting state:
fresh database volume, cleared mock CAS in-memory state, dropped
PHP opcache and session storage. The grader invokes it
unparameterised; it is the environment's all-or-nothing reset.

A non-zero exit from the reset script raises ``ResetError`` with
the captured output tail so the operator sees the failing step
without further introspection.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..errors import ResetError

RESET_SCRIPT_RELATIVE = "scripts/reset"
RESET_TIMEOUT_SECONDS = 300


def run_reset(mock_root: Path) -> None:
    """Run the grading environment's reset script.

    Args:
        mock_root: Resolved path to the grading environment install.

    Raises:
        ResetError: When the script does not exist at
            ``<mock-root>/scripts/reset``, when it cannot be
            executed, when it times out, or when it returns a
            non-zero exit code.
    """
    script = mock_root / RESET_SCRIPT_RELATIVE
    if not script.exists():
        raise ResetError(
            f"reset script not found at {script}; "
            "is mock_root pointing at a valid grading environment install?"
        )
    try:
        result = subprocess.run(
            [str(script)],
            capture_output=True,
            text=True,
            timeout=RESET_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ResetError(
            f"reset script at {script} timed out after {RESET_TIMEOUT_SECONDS}s"
        ) from error
    except OSError as error:
        raise ResetError(f"reset script at {script} could not be executed: {error}") from error
    if result.returncode != 0:
        combined = (result.stderr + "\n" + result.stdout).strip().splitlines()
        snippet = "\n  ".join(combined[-10:]) if combined else "(no output)"
        if result.returncode < 0:
            raise ResetError(
                f"reset script at {script} killed by signal "
                f"{-result.returncode}; tail:\n  {snippet}"
            )
        raise ResetError(
            f"reset script at {script} exited with code {result.returncode}; tail:\n  {snippet}"
        )
