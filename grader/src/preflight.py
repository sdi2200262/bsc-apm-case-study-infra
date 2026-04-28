#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
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

import requests
import urllib3

from .errors import PreflightError

OPENECLASS_URL = "http://localhost/"
MOCK_CAS_HEALTH_URL = "https://localhost:8082/health"
PROBE_TIMEOUT_SECONDS = 5


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
