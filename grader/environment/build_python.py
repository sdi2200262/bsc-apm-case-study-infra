# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Python build verification for the eclass-mcp-server checkout.

The grader runs ``uv sync`` against the participant's checkout to
install the Python implementation's dependencies. A successful
return indicates the dependencies resolved and the package is
importable inside the checkout's environment; the actual server
spawn happens during the protocol tests.

A failed ``uv sync`` is consequential: the orchestrator records every
Python rubric row as failed, so one transient package-index or network
blip would zero the whole Python half non-deterministically. To stop
that, the build is retried with backoff, but only on a transient
signature: a network, DNS, TLS, connection, rate-limit, or 5xx index
condition, or a resource-kill signal. A genuine lockfile or resolution
error carries none of these, so it fails on the first attempt and a
retry never masks it.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

BUILD_TIMEOUT_SECONDS = 120
MAX_BUILD_ATTEMPTS = 3
RETRY_BACKOFF_BASE_SECONDS = 2.0

# Transient-failure signatures in ``uv sync`` output. uv exits 1 for both
# a genuine resolution/lockfile error and a transient network/index
# outage, so the exit code cannot tell them apart; the combined output is
# matched instead. The patterns name the self-clearing network, DNS, TLS,
# connection, rate-limit, and 5xx conditions. A resolution or lockfile
# error matches none, so it is not retried. The fetch/download arm omits
# the word "resolve" on purpose: uv's dependency-resolution failures
# carry it and must stay deterministic, while host-resolution DNS
# failures are caught by the explicit phrases below. The numeric os-error
# codes are uv's common transient HTTP errnos.
_TRANSIENT_FAILURE = re.compile(
    r"error sending request"
    r"|failed to (?:fetch|download)"
    r"|connection (?:reset|refused|closed|aborted)"
    r"|connection error"
    r"|temporary failure in name resolution"
    r"|could not resolve host"
    r"|dns error"
    r"|timed out|operation timed out"
    r"|network is unreachable|network error"
    r"|tls error|handshake"
    r"|\b429\b|too many requests"
    r"|\b50[234]\b|service unavailable|bad gateway|gateway time-?out"
    r"|os error (?:104|110|111|11001|-3)",
    re.IGNORECASE,
)


def build(eclass_root: Path) -> tuple[bool, str, str]:
    """Install the Python implementation's dependencies.

    Args:
        eclass_root: Resolved path to the eclass-mcp-server
            checkout containing the ``pyproject.toml``.

    Retries ``uv sync`` up to ``MAX_BUILD_ATTEMPTS`` times with a growing
    backoff, but only when a failed attempt looks transient per
    ``_is_transient_failure``. The first success returns immediately, so a
    healthy build is unaffected. A missing ``uv`` and the whole-invocation
    timeout are not transient and return on the first attempt.

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

    attempt = 0
    while True:
        attempt += 1
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
            # A whole-invocation timeout is not a fast-clearing blip, and
            # retrying would multiply the wall-clock cost, so report as-is.
            return False, f"uv sync timed out ({BUILD_TIMEOUT_SECONDS}s)", \
                f"uv sync timed out after {BUILD_TIMEOUT_SECONDS} seconds"

        if result.returncode == 0:
            return True, "uv sync completed successfully", result.stdout or "uv sync completed"

        combined = (result.stderr + "\n" + result.stdout).strip()
        if result.returncode < 0:
            failure = (False, f"uv sync killed by signal {-result.returncode}", combined
                       or f"uv sync killed by signal {-result.returncode}")
        else:
            failure = (False, f"uv sync failed: {combined[:300]}", combined)

        if attempt >= MAX_BUILD_ATTEMPTS or not _is_transient_failure(
            result.returncode, combined
        ):
            return failure
        # Exponential backoff before the next attempt: 2s, then 4s.
        time.sleep(RETRY_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))


def _is_transient_failure(returncode: int, output: str) -> bool:
    """Return whether a failed ``uv sync`` attempt looks transient.

    A negative ``returncode`` is a kill-by-signal: under a loaded host an
    OOM kill can take down the resolver mid-run, which clears on a retry.
    Otherwise the combined output is matched against ``_TRANSIENT_FAILURE``;
    a genuine lockfile or resolution error matches none of them.

    Args:
        returncode: The subprocess return code, negative for a signal.
        output: The combined stderr/stdout of the failed attempt.

    Returns:
        ``True`` when the failure should be retried, ``False`` when it
        is deterministic and a retry would only repeat it.
    """
    if returncode < 0:
        return True
    return bool(_TRANSIENT_FAILURE.search(output))
