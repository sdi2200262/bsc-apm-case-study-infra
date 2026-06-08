# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Deterministic dev-environment provisioning for the patched checkout.

Replicates the documented local-development wiring by copying the
grading environment's own ``<mock_root>/.env`` and ``<mock_root>/
certs/`` verbatim into the eclass checkout, single-sourced rather
than reconstructed. Runs after a successful patch apply (which also
avoids a ``git apply --check`` collision with a pre-created
``certs/``) and resets per submission so no wiring leaks between
runs. The ``ECLASS_*`` env-var surface parses the same ``.env``
(``grader.environment.env_file``), so both config surfaces carry
identical values by construction. When a behavioural scenario
switches principal, the principal is written to both surfaces
together (``set_dotenv_credentials`` for the on-disk ``.env``,
env-var overrides for the other), so that invariant holds across
the switch and a server reading either surface authenticates as
the scenario's principal.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from ..errors import GraderError

DOTENV_FILENAME = ".env"
CERTS_DIRNAME = "certs"
SSO_CERT_FILENAME = "sso_cert.pem"
CREDENTIAL_KEYS = ("ECLASS_USERNAME", "ECLASS_PASSWORD")


class ProvisioningError(GraderError):
    """Raised when dev-environment provisioning cannot complete.

    Triggered when the grading environment install is incomplete
    (its ``.env`` or its ``certs/`` is absent); the message names
    the missing path and the operator action that resolves it.
    """


def check_provisioning_sources(mock_root: Path) -> None:
    """Verify the grading environment carries the artefacts to copy, before any copy.

    Args:
        mock_root: Resolved grading-environment install path.

    Raises:
        ProvisioningError: When ``<mock_root>/.env`` or
            ``<mock_root>/certs/sso_cert.pem`` is absent.
    """
    mock_root = Path(mock_root).resolve()
    dotenv_source = mock_root / DOTENV_FILENAME
    cert_source = mock_root / CERTS_DIRNAME / SSO_CERT_FILENAME
    if not dotenv_source.is_file() or not cert_source.is_file():
        raise ProvisioningError(
            f"grading environment at {mock_root} is missing .env or "
            "certs/sso_cert.pem; install the bsc-apm testing env first"
        )


def provision(eclass_root: Path, mock_root: Path) -> None:
    """Check the sources, then copy the documented ``.env`` and ``certs/`` verbatim. Idempotent.

    Args:
        eclass_root: Resolved patched eclass-mcp-server checkout path.
        mock_root: Resolved grading-environment install path.

    Raises:
        ProvisioningError: When the grading environment lacks its
            ``.env`` or authoritative certificate.
    """
    check_provisioning_sources(mock_root)
    write_dotenv(eclass_root, mock_root)
    install_sso_cert(eclass_root, mock_root)


def write_dotenv(eclass_root: Path, mock_root: Path) -> Path:
    """Copy ``<mock_root>/.env`` verbatim to ``<eclass_root>/.env`` (no filtering).

    Args:
        eclass_root: Resolved patched eclass-mcp-server checkout path.
        mock_root: Resolved grading-environment install path (single source).

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
        mock_root: Resolved grading-environment install path.

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
            f"grading environment at {mock_root} is missing the certs/ "
            "directory; install the bsc-apm testing env first"
        )
    destination = eclass_root / CERTS_DIRNAME
    shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(source, destination)
    return destination


def blank_dotenv_credentials(eclass_root: Path) -> None:
    """Empty only the credential values in the checkout's ``.env``, in place.

    Every other line is preserved verbatim (comments, ordering, all
    non-credential keys) so the dotenv surface stays otherwise
    valid; only the keys in ``CREDENTIAL_KEYS`` are emptied.
    Used by the missing-credentials probes to deprive the on-disk
    surface without removing the file.

    Args:
        eclass_root: Resolved patched eclass-mcp-server checkout path.

    Raises:
        FileNotFoundError: When the checkout has no ``.env``; a
            verbatim copy must be written before blanking.
    """
    _rewrite_credentials(eclass_root, lambda _key: "")


def set_dotenv_credentials(eclass_root: Path, username: str, password: str) -> None:
    """Write a principal to the checkout's ``.env`` credentials, in place.

    Rewrites only the two ``CREDENTIAL_KEYS`` lines to the given
    principal; every other line (comments, ordering, all
    non-credential keys) is preserved verbatim, so the dotenv
    surface stays otherwise valid. A server that reads only the
    on-disk ``.env`` then authenticates as the same principal the
    env-var surface carries, so the behavioural suites test
    behaviour rather than the participant's credential-surface
    choice.

    Args:
        eclass_root: Resolved patched eclass-mcp-server checkout path.
        username: Value written for ``ECLASS_USERNAME``.
        password: Value written for ``ECLASS_PASSWORD``.

    Raises:
        FileNotFoundError: When the checkout has no ``.env``. The
            verbatim ``.env`` is written by ``provision`` before
            any principal is written, so a missing file is a real
            precondition failure surfaced loudly, not a silent
            fallback.
    """
    replacements = {
        "ECLASS_USERNAME": username,
        "ECLASS_PASSWORD": password,
    }
    _rewrite_credentials(eclass_root, replacements.__getitem__)


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


def _rewrite_credentials(eclass_root: Path, value_for: Callable[[str], str]) -> None:
    """Rewrite the ``CREDENTIAL_KEYS`` lines of the checkout's ``.env``.

    Walks the file line by line and replaces only the lines whose key
    is in ``CREDENTIAL_KEYS``; every other line (comments, blank
    lines, ordering, all non-credential keys) is preserved verbatim.
    The new value for a matched key is supplied by ``value_for``, so the
    credential-blanking and credential-writing callers share this one
    rewrite loop.

    Args:
        eclass_root: Resolved patched eclass-mcp-server checkout path.
        value_for: Callable mapping a credential key to the value
            written after the ``=``.

    Raises:
        FileNotFoundError: When the checkout has no ``.env``; the
            verbatim ``.env`` must be written by ``provision``
            before any rewrite.
    """
    eclass_root = Path(eclass_root).resolve()
    dotenv_path = eclass_root / DOTENV_FILENAME
    rewritten: list[str] = []
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in CREDENTIAL_KEYS:
                rewritten.append(f"{key}={value_for(key)}")
                continue
        rewritten.append(line)
    dotenv_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
