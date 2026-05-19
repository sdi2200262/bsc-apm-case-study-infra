#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Pre-flight HTTP probes against the testing environment.

The grader runs against a separately-installed testing environment
that provides the openeclass instance and the mock CAS service.
Before any phase test runs, the pre-flight check verifies that
both services respond on their localhost ports. The probes are
idempotent and read-only; they do not mutate any state on either
service.

A failed probe raises ``PreflightError`` with a message naming the
failing service and pointing the operator at the testing
environment's lifecycle scripts. The grader's caller catches the
error and exits without running tests.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import requests
import urllib3

from .errors import PreflightError

OPENECLASS_URL = "http://localhost/"
MOCK_CAS_HEALTH_URL = "https://localhost:18443/health"
PROBE_TIMEOUT_SECONDS = 5

# The mcp releases the constructed handshake contract was verified
# against. The eclass-mcp-server dependency floor (mcp>=1.24.0,
# Python >=3.10) admits exactly this finite set, and the low-level
# initialize/tools-list wire serialisation is byte-identical across
# it, so the constructed contract is exact within this window.
VERIFIED_MCP_RELEASES = frozenset(
    {"1.24.0", "1.25.0", "1.26.0", "1.27.0", "1.27.1"}
)
MCP_RESOLVE_TIMEOUT_SECONDS = 60


def run_preflight() -> None:
    """Probe the testing environment's HTTP endpoints.

    Issues GET requests against both the openeclass landing page
    and the mock CAS health endpoint. Either service unreachable
    or returning a non-2xx status fails the pre-flight.

    Raises:
        PreflightError: When either probe fails. The message names
            the failing service, the URL, and the underlying error
            or status code.
    """
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    _probe(OPENECLASS_URL, "openeclass", verify=True)
    _probe(MOCK_CAS_HEALTH_URL, "mock CAS", verify=False)


def assert_mcp_release_verified(eclass_root: Path) -> None:
    """Assert the resolved ``mcp`` release is one of the verified set.

    The baseline handshake rows compare against a constructed
    initialize/tools-list contract that is byte-faithful only for
    the ``mcp`` releases in :data:`VERIFIED_MCP_RELEASES`. This is a
    read-only version resolution: it asks the eclass-mcp-server
    environment which ``mcp`` it would import and never spawns a
    server.

    Args:
        eclass_root: Resolved eclass-mcp-server checkout whose
            project environment resolves ``mcp``.

    Raises:
        PreflightError: When the version cannot be resolved, or when
            it falls outside the verified window. The message states
            the resolved version and the operator action.
    """
    try:
        completed = subprocess.run(
            [
                "uv", "run", "--project", str(eclass_root),
                "python", "-c",
                "import importlib.metadata,sys;"
                "sys.stdout.write(importlib.metadata.version('mcp'))",
            ],
            capture_output=True,
            text=True,
            timeout=MCP_RESOLVE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PreflightError(
            f"could not resolve the mcp version under {eclass_root}: "
            f"{error}; is uv installed and the eclass-mcp-server "
            "project resolvable?"
        ) from error
    if completed.returncode != 0:
        combined = (completed.stderr + " " + completed.stdout).strip()
        detail = combined.replace("\n", " ") or "no output"
        if completed.returncode < 0:
            raise PreflightError(
                f"could not resolve the mcp version under {eclass_root} "
                f"(uv killed by signal {-completed.returncode}): {detail}"
            )
        raise PreflightError(
            f"could not resolve the mcp version under {eclass_root} "
            f"(uv exited {completed.returncode}): {detail}"
        )
    version = completed.stdout.strip()
    if version not in VERIFIED_MCP_RELEASES:
        raise PreflightError(
            f"resolved mcp {version!r} is outside the verified set "
            f"{sorted(VERIFIED_MCP_RELEASES)}; the constructed "
            "initialize/tools-list expected values must be re-verified "
            "against this release before grading"
        )


def _probe(url: str, service: str, *, verify: bool) -> None:
    """Issue one GET probe and raise ``PreflightError`` on failure.

    Args:
        url: The endpoint to probe.
        service: Human-readable service name for the error message.
        verify: Whether to verify the TLS certificate. The mock
            CAS uses a self-signed certificate; verification is
            disabled for that endpoint.

    Raises:
        PreflightError: When the request fails, times out, or
            returns a non-2xx status code.
    """
    try:
        response = requests.get(
            url, timeout=PROBE_TIMEOUT_SECONDS, verify=verify
        )
    except requests.RequestException as error:
        raise PreflightError(
            f"{service} not reachable at {url}: {error}; "
            "is the testing environment running? "
            "see <mock-root>/scripts/up and <mock-root>/scripts/status"
        ) from error
    if not 200 <= response.status_code < 300:
        raise PreflightError(
            f"{service} at {url} returned HTTP {response.status_code}; "
            "see <mock-root>/scripts/status"
        )
