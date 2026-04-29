#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
C build and tech-stack verification for the eclass-mcp-server's c-replica.

The C replica lives at ``<eclass-root>/c-replica/`` and ships a
Makefile whose ``c-server`` target builds the ``server`` binary.
Two assertions live here:

- ``compile_c_replica`` (C.1.1) runs ``make clean`` then
  ``make c-server`` and verifies the binary lands at
  ``<c-replica>/server`` with execute permission.
- ``verify_stack`` (C.1.2) runs ``ldd`` against the produced
  binary and asserts the require-plus-forbidden mechanic the
  rubric documents: ``libcurl.so`` and ``libxml2.so`` must be
  present, and no SO name may match the JSON-parser regex
  ``^lib(json|cjson|jansson|yajl|jq|parson)``. Transitive system
  dependencies of libcurl and libxml2 are unrestricted.

A pkg-config probe warns when libcurl or libxml2 are below the
documented minimums but does not fail the build on its own; the
``make`` outcome is authoritative.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

BUILD_TIMEOUT_SECONDS = 120
CLEAN_TIMEOUT_SECONDS = 30
LDD_TIMEOUT_SECONDS = 10
VERSION_PROBE_TIMEOUT_SECONDS = 5

MIN_LIBCURL_VERSION = "7.81.0"
MIN_LIBXML2_VERSION = "2.9.13"

REQUIRED_LIBRARIES: tuple[str, ...] = ("libcurl.so", "libxml2.so")
FORBIDDEN_LIBRARY_PATTERN = re.compile(
    r"^lib(json|cjson|jansson|yajl|jq|parson)"
)
_LDD_LINE_PATTERN = re.compile(r"\s*([^\s/=]+\.so[^\s]*)")


def compile_c_replica(eclass_root: Path) -> tuple[bool, str, str]:
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
        return (
            False,
            f"make c-server timed out ({BUILD_TIMEOUT_SECONDS}s)",
            f"make c-server timed out after {BUILD_TIMEOUT_SECONDS} seconds",
        )

    if result.returncode != 0:
        err = result.stderr or result.stdout
        if not versions_ok:
            err = f"{warning}\n{err}"
        if "libxml" in err:
            return False, "make c-server failed: missing libxml2-dev", err
        if "curl" in err:
            return False, "make c-server failed: missing libcurl-dev", err
        return False, f"make c-server failed: {err[:300]}", err

    server_binary = c_replica / "server"
    if not server_binary.exists():
        return (
            False,
            "compilation succeeded but 'server' binary not found",
            "make c-server completed but server binary was not created",
        )
    if not os.access(server_binary, os.X_OK):
        return (
            False,
            "'server' binary exists but is not executable",
            "server binary exists but lacks execute permission",
        )

    if not versions_ok:
        return (
            True,
            f"make c-server completed (with version warning: {versions_msg})",
            f"{warning}\n{result.stdout or 'Compilation successful'}",
        )
    return (
        True,
        "make c-server completed, server binary created",
        result.stdout or "Compilation successful",
    )


def verify_stack(eclass_root: Path) -> tuple[bool, str, str]:
    """Verify the c-replica binary's dynamic-link tech stack.

    Args:
        eclass_root: Resolved path to the eclass-mcp-server
            checkout containing the ``c-replica/`` subdirectory.

    Returns:
        Tuple of ``(ok, summary, detail)``. ``ok`` is ``True`` only
        when every required library is linked and no forbidden
        library is linked. ``detail`` carries the captured ``ldd``
        output for review.
    """
    eclass_root = Path(eclass_root).resolve()
    server_binary = eclass_root / "c-replica" / "server"
    if not server_binary.exists():
        return (
            False,
            "server binary not found",
            f"server binary not found at {server_binary}",
        )

    try:
        result = subprocess.run(
            ["ldd", str(server_binary)],
            capture_output=True,
            text=True,
            timeout=LDD_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return False, "ldd not on PATH", "ldd not on PATH"
    except subprocess.TimeoutExpired:
        return (
            False,
            f"ldd timed out ({LDD_TIMEOUT_SECONDS}s)",
            f"ldd timed out after {LDD_TIMEOUT_SECONDS} seconds",
        )

    if result.returncode != 0:
        return False, f"ldd exit {result.returncode}", result.stderr or result.stdout

    output = result.stdout
    so_names = _extract_so_names(output)

    missing_required = [
        name for name in REQUIRED_LIBRARIES
        if not any(so.startswith(name) for so in so_names)
    ]
    if missing_required:
        return (
            False,
            f"missing required libraries: {missing_required}",
            output,
        )

    forbidden = [name for name in so_names if FORBIDDEN_LIBRARY_PATTERN.match(name)]
    if forbidden:
        return (
            False,
            f"forbidden JSON-parser libraries linked: {forbidden}",
            output,
        )

    return (
        True,
        f"libcurl and libxml2 linked; no forbidden JSON-parser library present",
        output,
    )


def _extract_so_names(ldd_output: str) -> list[str]:
    """Return the SO names ``ldd`` reports, one entry per output line."""
    names: list[str] = []
    for line in ldd_output.splitlines():
        match = _LDD_LINE_PATTERN.match(line)
        if match:
            names.append(match.group(1))
    return names


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
        return (
            False,
            f"libcurl version {curl_version} is below minimum required {MIN_LIBCURL_VERSION}",
        )
    if _version_lt(xml2_version, MIN_LIBXML2_VERSION):
        return (
            False,
            f"libxml2 version {xml2_version} is below minimum required {MIN_LIBXML2_VERSION}",
        )
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
