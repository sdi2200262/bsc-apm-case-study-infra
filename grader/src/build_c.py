#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
C build verification for the eclass-mcp-server's c-replica.

The C replica lives at ``<eclass-root>/c-replica/`` and ships a
Makefile whose ``c-server`` target builds the ``server`` binary.
The grader runs ``make clean`` then ``make c-server`` and verifies
the binary lands at ``<c-replica>/server`` with execute permission.
A pkg-config-based version check warns when libcurl or libxml2
are below the documented minimums but does not fail the build on
its own; the actual ``make`` outcome is authoritative.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

BUILD_TIMEOUT_SECONDS = 120
CLEAN_TIMEOUT_SECONDS = 30
VERSION_PROBE_TIMEOUT_SECONDS = 5

MIN_LIBCURL_VERSION = "7.81.0"
MIN_LIBXML2_VERSION = "2.9.13"


def build(eclass_root: Path) -> tuple[bool, str, str]:
    """Compile the C replica and verify the produced binary.

    Args:
        eclass_root: Resolved path to the eclass-mcp-server
            checkout containing the ``c-replica/`` subdirectory.

    Returns:
        Tuple of ``(ok, summary, detail)``. ``summary`` is a short
        success or failure description; ``detail`` carries the
        full make output plus any version-check warning.
    """
    eclass_root = Path(eclass_root).resolve()
    c_replica = eclass_root / "c-replica"
    if not c_replica.exists():
        message = "c-replica/ directory not found in eclass-mcp-server"
        return False, "c-replica/ directory not found", message

    if not (c_replica / "Makefile").exists():
        message = "Makefile not found in c-replica/ directory"
        return False, "Makefile not found in c-replica/", message

    versions_ok, versions_msg = _check_library_versions()
    warning = "" if versions_ok else f"WARNING: {versions_msg}. Attempting build anyway..."

    subprocess.run(
        ["make", "clean"],
        cwd=c_replica,
        capture_output=True,
        timeout=CLEAN_TIMEOUT_SECONDS,
    )

    try:
        result = subprocess.run(
            ["make", "c-server"],
            cwd=c_replica,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return False, "make command not found", "make command not found in PATH"
    except subprocess.TimeoutExpired:
        return False, f"make c-server timed out ({BUILD_TIMEOUT_SECONDS}s)", \
            f"make c-server timed out after {BUILD_TIMEOUT_SECONDS} seconds"

    if result.returncode != 0:
        err = result.stderr or result.stdout
        if not versions_ok:
            err = f"{warning}\n{err}"
        if "libxml" in err:
            return False, "make c-server failed: missing libxml2-dev", err
        if "curl" in err:
            return False, "make c-server failed: missing libcurl-dev", err
        return False, f"make c-server failed: {err[:300]}", err

    if not versions_ok:
        return (
            True,
            f"make c-server completed (with version warning: {versions_msg})",
            f"{warning}\n{result.stdout or 'Compilation successful'}",
        )

    server_binary = c_replica / "server"
    if not server_binary.exists():
        return False, "compilation succeeded but 'server' binary not found", \
            "make c-server completed but server binary was not created"
    if not os.access(server_binary, os.X_OK):
        return False, "'server' binary exists but is not executable", \
            "server binary exists but lacks execute permission"

    return True, "make c-server completed, server binary created", result.stdout or "Compilation successful"


def _check_library_versions() -> tuple[bool, str]:
    """Probe libcurl and libxml2 versions via ``pkg-config``.

    Returns:
        Tuple of ``(ok, message)``. ``ok`` is ``True`` when both
        libraries meet the documented minimums; the message names
        the versions found or the failing probe step.
    """
    try:
        curl = subprocess.run(
            ["pkg-config", "--modversion", "libcurl"],
            capture_output=True,
            text=True,
            timeout=VERSION_PROBE_TIMEOUT_SECONDS,
        )
        if curl.returncode != 0:
            return False, "libcurl not found via pkg-config"
        curl_version = curl.stdout.strip()

        xml2 = subprocess.run(
            ["pkg-config", "--modversion", "libxml-2.0"],
            capture_output=True,
            text=True,
            timeout=VERSION_PROBE_TIMEOUT_SECONDS,
        )
        if xml2.returncode != 0:
            return False, "libxml2 not found via pkg-config"
        xml2_version = xml2.stdout.strip()
    except FileNotFoundError:
        return False, "pkg-config not found, cannot verify library versions"
    except subprocess.TimeoutExpired:
        return False, "pkg-config version check timed out"

    if _version_lt(curl_version, MIN_LIBCURL_VERSION):
        return False, f"libcurl version {curl_version} is below minimum required {MIN_LIBCURL_VERSION}"
    if _version_lt(xml2_version, MIN_LIBXML2_VERSION):
        return False, f"libxml2 version {xml2_version} is below minimum required {MIN_LIBXML2_VERSION}"
    return True, (
        f"libcurl {curl_version} (>= {MIN_LIBCURL_VERSION}), "
        f"libxml2 {xml2_version} (>= {MIN_LIBXML2_VERSION})"
    )


def _version_lt(left: str, right: str) -> bool:
    """Return ``True`` when version string ``left`` is below ``right``."""
    left_parts = [int(p) for p in left.split(".")]
    right_parts = [int(p) for p in right.split(".")]
    width = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (width - len(left_parts)))
    right_parts.extend([0] * (width - len(right_parts)))
    return left_parts < right_parts
