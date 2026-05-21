#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C configuration-surface phase aggregator: C.1.5 and C.1.6.

Runs the two positive configuration-surface probes in order
(env-var, then verbatim documented ``.env``) and, regardless of
either outcome, leaves the eclass tree dual-provisioned for the
downstream functional and memory suites by restoring the verbatim
``.env`` and ``certs/`` in ``finally``. A surface probe failure does
not gate the suite; only a C.1.1 compile failure cascade-skips.
"""

from __future__ import annotations

from pathlib import Path

from ..provision import provision
from . import config_surface


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str, str | None]]:
    """Run the two configuration-surface probes and restore provisioning.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail,
        mode)`` for ``C.1.5`` and ``C.1.6``. ``mode`` is ``None``: a
        configuration-surface probe is a login-succeeded verdict,
        not a string match.
    """
    results: dict[str, tuple[bool, str, str, str | None]] = {}
    try:
        env_ok, env_msg, env_detail = config_surface.test_env_var_config_surface(
            eclass_dir, mock_root, debug
        )
        results["C.1.5"] = (env_ok, env_msg, env_detail, None)
        dot_ok, dot_msg, dot_detail = config_surface.test_dotenv_config_surface(
            eclass_dir, mock_root, debug
        )
        results["C.1.6"] = (dot_ok, dot_msg, dot_detail, None)
    finally:
        provision(eclass_dir, mock_root)
    return results
