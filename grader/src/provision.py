#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Deterministic dev-environment provisioning for the patched checkout.

Replicates the documented local-development wiring by copying the
testing environment's own ``<mock_root>/.env`` and ``<mock_root>/
certs/`` verbatim into the eclass checkout, single-sourced rather
than reconstructed. Runs after a successful patch apply (which also
avoids a ``git apply --check`` collision with a pre-created
``certs/``) and resets per submission so no wiring leaks between
runs. The ``ECLASS_*`` env-var surface parses the same ``.env``
(:mod:`grader.src.env_file`), so both config surfaces carry
identical values by construction.
"""

from __future__ import annotations

import shutil
from pathlib import Path

DOTENV_FILENAME = ".env"
CERTS_DIRNAME = "certs"
SSO_CERT_FILENAME = "sso_cert.pem"


def preflight_provisioning(mock_root: Path) -> None:
    """Verify the testing environment carries the artefacts to copy, before any copy.

    Args:
        mock_root: Resolved testing-environment install path.

    Raises:
        ProvisioningError: When ``<mock_root>/.env`` or
            ``<mock_root>/certs/sso_cert.pem`` is absent.
    """
    mock_root = Path(mock_root).resolve()
    dotenv_source = mock_root / DOTENV_FILENAME
    cert_source = mock_root / CERTS_DIRNAME / SSO_CERT_FILENAME
    if not dotenv_source.is_file() or not cert_source.is_file():
        raise ProvisioningError(
            f"testing environment at {mock_root} is missing .env or "
            "certs/sso_cert.pem; install the bsc-apm testing env first"
        )


def provision(eclass_root: Path, mock_root: Path) -> None:
    """Preflight, then copy the documented ``.env`` and ``certs/`` verbatim. Idempotent.

    Args:
        eclass_root: Resolved patched eclass-mcp-server checkout path.
        mock_root: Resolved testing-environment install path.

    Raises:
        ProvisioningError: When the testing environment lacks its
            ``.env`` or authoritative certificate.
    """
    preflight_provisioning(mock_root)
    write_dotenv(eclass_root, mock_root)
    install_sso_cert(eclass_root, mock_root)


def write_dotenv(eclass_root: Path, mock_root: Path) -> Path:
    """Copy ``<mock_root>/.env`` verbatim to ``<eclass_root>/.env`` (no filtering).

    Args:
        eclass_root: Resolved patched eclass-mcp-server checkout path.
        mock_root: Resolved testing-environment install path (single source).

    Returns:
        The path of the ``.env`` file written.
    """
    eclass_root = Path(eclass_root).resolve()
    mock_root = Path(mock_root).resolve()
    source = mock_root / DOTENV_FILENAME
    destination = eclass_root / DOTENV_FILENAME
    shutil.copyfile(source, destination)
    return destination


def install_sso_cert(eclass_root: Path, mock_root: Path) -> Path:
    """Replace ``<eclass_root>/certs/`` with a verbatim copy of the mock's ``certs/``.

    The directory is replaced wholesale so TLS trust is pinned to
    the grader mock's authoritative self-signed certificate,
    overwriting any certificate the patch shipped, and so the copied
    ``.env``'s relative ``./certs/sso_cert.pem`` reference resolves
    on disk.

    Args:
        eclass_root: Resolved patched eclass-mcp-server checkout path.
        mock_root: Resolved testing-environment install path.

    Returns:
        The destination ``certs/`` directory path.

    Raises:
        ProvisioningError: When the mock has no ``certs/`` directory.
    """
    eclass_root = Path(eclass_root).resolve()
    mock_root = Path(mock_root).resolve()
    source = mock_root / CERTS_DIRNAME
    if not source.is_dir():
        raise ProvisioningError(
            f"testing environment at {mock_root} is missing the certs/ "
            "directory; install the bsc-apm testing env first"
        )
    destination = eclass_root / CERTS_DIRNAME
    shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(source, destination)
    return destination


def reset_provisioning(eclass_root: Path) -> None:
    """Remove the provisioned ``.env`` and ``certs/`` per-submission (idempotent).

    The gitignored ``.env`` is removed explicitly since ``git clean
    -fd`` would miss it, so no config leaks into the next run.

    Args:
        eclass_root: Resolved eclass-mcp-server checkout path.
    """
    eclass_root = Path(eclass_root).resolve()
    dotenv_path = eclass_root / DOTENV_FILENAME
    dotenv_path.unlink(missing_ok=True)
    certs_dir = eclass_root / CERTS_DIRNAME
    shutil.rmtree(certs_dir, ignore_errors=True)


class ProvisioningError(Exception):
    """Raised when dev-environment provisioning cannot complete.

    Triggered when the testing environment install is incomplete
    (its ``.env`` or its ``certs/`` is absent); the message names
    the missing path and the operator action that resolves it.
    """
