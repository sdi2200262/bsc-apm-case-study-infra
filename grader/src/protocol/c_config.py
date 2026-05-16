#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C configuration-surface phase aggregator: C.1.3 and C.1.4.

Runs the two configuration-surface probes in order (env-var, then
verbatim documented ``.env``) and, regardless of either outcome,
leaves the eclass tree dual-provisioned for the downstream
functional and memory suites: the testing environment's own
``.env`` and ``certs/`` copied verbatim into the checkout, with
``mcp_server_env`` (the ``ECLASS_*`` values plus the TLS trust
anchors) additionally injected on every spawn by the runner. A
server is therefore measured by C.2 through C.5 whichever surface
it reads, and a C.1.3 or C.1.4 failure does not gate the suite;
only a C.1.1 compile failure cascade-skips. Restoring here keeps
the surface decoupling local to this module.
"""

from __future__ import annotations

from pathlib import Path

from ..provision import provision
from . import config_surface


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str]]:
    """Run the two configuration-surface probes and restore provisioning.

    The env-var probe runs first (it removes ``.env`` for its
    isolation), then the verbatim-``.env`` probe (it copies the
    testing environment's ``.env`` and ``certs/`` in). After both,
    the verbatim ``.env`` and ``certs/`` are restored
    unconditionally so the dual-provisioned on-disk state holds for
    the functional and memory phases even when a probe failed or
    raised. The per-spawn ``ECLASS_*``-plus-TLS injection is the
    runner's responsibility and happens for every spawned server
    regardless.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail)``
        for C.1.3 and C.1.4.
    """
    results: dict[str, tuple[bool, str, str]] = {}
    try:
        results["C.1.3"] = config_surface.test_env_var_config_surface(
            eclass_dir, mock_root, debug
        )
        results["C.1.4"] = config_surface.test_dotenv_config_surface(
            eclass_dir, mock_root, debug
        )
    finally:
        provision(eclass_dir, mock_root)
    return results
