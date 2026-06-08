#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Spawned-server environment assembly, single-sourced from the mock.

Owns the environment block a participant MCP server is spawned
with: the ``ECLASS_*`` configuration pairs parsed from the testing
environment's own ``<mock_root>/.env`` and the grader-side TLS
trust-anchor variables that point the server's HTTP client at the
mock's SSO certificate. The env-var configuration surface and the
on-disk dotenv surface both derive from this one parsed ``.env``,
so they carry identical values by construction.
"""

from __future__ import annotations

from pathlib import Path

from ..environment.env_file import parse_env_file

DOTENV_FILENAME = ".env"
ECLASS_KEY_PREFIX = "ECLASS_"


def eclass_config_pairs(mock_root: Path) -> dict[str, str]:
    """Return the ``ECLASS_*`` configuration pairs from the mock's ``.env``.

    Parses ``<mock_root>/.env`` so that the env-var injection path
    and the dotenv provisioning path carry byte-identical values by
    construction. TLS trust-anchor keys are supplied separately by
    ``tls_trust_env``.

    Args:
        mock_root: Resolved grading environment install path.

    Returns:
        Mapping of ``ECLASS_*`` configuration keys to values.
    """
    mock_root = Path(mock_root).resolve()
    parsed = parse_env_file(mock_root / DOTENV_FILENAME)
    return {
        key: value
        for key, value in parsed.items()
        if key.startswith(ECLASS_KEY_PREFIX)
    }


def tls_trust_env(mock_root: Path) -> dict[str, str]:
    """Return the TLS trust-anchor environment for the spawned server.

    Points the participant server's HTTP client at the grader mock's
    SSO certificate. Kept separate from ``eclass_config_pairs``
    because these are grader-side plumbing, not part of the
    participant-documented configuration surface.

    Args:
        mock_root: Resolved grading environment install path.

    Returns:
        Mapping of TLS trust-anchor environment variables.
    """
    cert_path = str(mock_root / "certs" / "sso_cert.pem")
    return {
        "SSL_CERT_FILE": cert_path,
        "REQUESTS_CA_BUNDLE": cert_path,
        "CURL_CA_BUNDLE": cert_path,
        "PYTHONHTTPSVERIFY": "0",
    }


def mcp_server_env(mock_root: Path) -> dict[str, str]:
    """Return the environment variables a participant MCP server expects.

    Merges the ``ECLASS_*`` configuration pairs with the TLS
    trust-anchor keys; a server spawned with this environment is
    fully configured via environment variables alone.

    Args:
        mock_root: Resolved grading environment install path.

    Returns:
        Mapping suitable for ``env_vars`` on a ``TestContext``.
    """
    env = eclass_config_pairs(mock_root)
    env.update(tls_trust_env(mock_root))
    return env
