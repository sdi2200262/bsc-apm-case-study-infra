#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C build and tech-stack verification for the eclass-mcp-server's c-replica.

The C replica lives at ``<eclass-root>/c-replica/`` and ships a
Makefile whose ``c-server`` target builds the ``server`` binary.
Two entry points live here:

- ``compile_c_replica`` (C.1.1) runs ``make clean`` then
  ``make c-server`` and verifies the binary lands at
  ``<c-replica>/server`` with execute permission.
- ``verify_stack`` runs ``ldd`` once against the produced binary
  and derives three independent verdicts: C.1.2 (``libcurl.so``
  present), C.1.3 (``libxml2.so`` present), and C.1.4 (no SO name
  matches the JSON-parser regex
  ``^lib(json|cjson|jansson|yajl|jq|parson)``). Transitive system
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

# Specific build-failure signatures. A naive substring such as
# "curl" matches benign mentions in compiler notes or filenames and
# misattributes unrelated failures; these patterns match the actual
# missing-header and unresolved-symbol diagnostics the toolchain
# emits so the attribution is only made when it is warranted.
_LIBXML2_FAILURE_PATTERN = re.compile(
    r"libxml/[\w.]+:\s*No such file or directory|cannot find -lxml2"
)
_LIBCURL_FAILURE_PATTERN = re.compile(
    r"curl/curl\.h:\s*No such file or directory|cannot find -lcurl"
)


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
        err = (result.stderr + "\n" + result.stdout).strip()
        if not versions_ok:
            err = f"{warning}\n{err}"
        if result.returncode < 0:
            return (
                False,
                f"make c-server killed by signal {-result.returncode}",
                err,
            )
        attribution = _attribute_build_failure(err)
        if attribution is not None:
            return False, f"make c-server failed: {attribution}", err
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


def verify_stack(eclass_root: Path) -> dict[str, tuple[bool, str, str]]:
    """Verify the c-replica binary's dynamic-link tech stack.

    Runs ``ldd`` once and derives three independently-scored verdicts:

    - ``"C.1.2"``: dynamic dependencies include ``libcurl``.
    - ``"C.1.3"``: dynamic dependencies include ``libxml2``.
    - ``"C.1.4"``: dynamic dependencies exclude every JSON-parsing
      library (``libjson``, ``libcjson``, ``libjansson``, ``libyajl``,
      ``libjq``, ``libparson``).

    Each verdict is independent so a single stack defect fails only
    the row it isolates.

    Args:
        eclass_root: Resolved path to the eclass-mcp-server
            checkout containing the ``c-replica/`` subdirectory.

    Returns:
        Mapping of rubric identifier to ``(ok, summary, detail)``.
        All three rows are present even when ``ldd`` fails (each
        records the same failure in that case).
    """
    eclass_root = Path(eclass_root).resolve()
    server_binary = eclass_root / "c-replica" / "server"
    if not server_binary.exists():
        msg = f"server binary not found at {server_binary}"
        fail = (False, "server binary not found", msg)
        return {"C.1.2": fail, "C.1.3": fail, "C.1.4": fail}

    try:
        result = subprocess.run(
            ["ldd", str(server_binary)],
            capture_output=True,
            text=True,
            timeout=LDD_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        fail = (False, "ldd not on PATH", "ldd not on PATH")
        return {"C.1.2": fail, "C.1.3": fail, "C.1.4": fail}
    except subprocess.TimeoutExpired:
        msg = f"ldd timed out after {LDD_TIMEOUT_SECONDS} seconds"
        fail = (False, f"ldd timed out ({LDD_TIMEOUT_SECONDS}s)", msg)
        return {"C.1.2": fail, "C.1.3": fail, "C.1.4": fail}

    if result.returncode != 0:
        msg = (result.stderr + "\n" + result.stdout).strip()
        if result.returncode < 0:
            summary = f"ldd killed by signal {-result.returncode}"
        else:
            summary = f"ldd exit {result.returncode}"
        fail = (False, summary, msg)
        return {"C.1.2": fail, "C.1.3": fail, "C.1.4": fail}

    output = result.stdout
    so_names = _extract_so_names(output)

    has_curl = any(so.startswith("libcurl.so") for so in so_names)
    has_xml2 = any(so.startswith("libxml2.so") for so in so_names)
    forbidden = [n for n in so_names if FORBIDDEN_LIBRARY_PATTERN.match(n)]

    c12: tuple[bool, str, str] = (
        (True, "libcurl present in dynamic dependencies", output)
        if has_curl
        else (False, "libcurl not found in dynamic dependencies", output)
    )
    c13: tuple[bool, str, str] = (
        (True, "libxml2 present in dynamic dependencies", output)
        if has_xml2
        else (False, "libxml2 not found in dynamic dependencies", output)
    )
    c14: tuple[bool, str, str] = (
        (True, "no forbidden JSON-parser library in dynamic dependencies", output)
        if not forbidden
        else (False, f"forbidden JSON-parser libraries linked: {forbidden}", output)
    )
    return {"C.1.2": c12, "C.1.3": c13, "C.1.4": c14}


def _attribute_build_failure(err: str) -> str | None:
    """Attribute a build failure to a missing dev library when warranted.

    Args:
        err: Captured ``make c-server`` stderr or stdout.

    Returns:
        ``"missing libxml2-dev"`` or ``"missing libcurl-dev"`` when
        the output carries the corresponding missing-header or
        unresolved-library diagnostic; ``None`` when no specific
        signature matched, so the caller falls through to the
        generic truncated-output summary.
    """
    if _LIBXML2_FAILURE_PATTERN.search(err):
        return "missing libxml2-dev"
    if _LIBCURL_FAILURE_PATTERN.search(err):
        return "missing libcurl-dev"
    return None


def _extract_so_names(ldd_output: str) -> list[str]:
    """Return the SO names ``ldd`` reports, one entry per output line.

    Args:
        ldd_output: Captured ``ldd`` stdout.

    Returns:
        The SO-name tokens matched by ``_LDD_LINE_PATTERN``, one per
        matched line, in source order.
    """
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

    curl_cmp = _version_lt(curl_version, MIN_LIBCURL_VERSION)
    if curl_cmp is None:
        return (
            False,
            f"libcurl version {curl_version!r} is unparseable; "
            f"skipping the minimum-version check (build is authoritative)",
        )
    if curl_cmp:
        return (
            False,
            f"libcurl version {curl_version} is below minimum required {MIN_LIBCURL_VERSION}",
        )
    xml2_cmp = _version_lt(xml2_version, MIN_LIBXML2_VERSION)
    if xml2_cmp is None:
        return (
            False,
            f"libxml2 version {xml2_version!r} is unparseable; "
            f"skipping the minimum-version check (build is authoritative)",
        )
    if xml2_cmp:
        return (
            False,
            f"libxml2 version {xml2_version} is below minimum required {MIN_LIBXML2_VERSION}",
        )
    return True, (
        f"libcurl {curl_version} (>= {MIN_LIBCURL_VERSION}), "
        f"libxml2 {xml2_version} (>= {MIN_LIBXML2_VERSION})"
    )


def _version_lt(left: str, right: str) -> bool | None:
    """Return whether version ``left`` is below ``right``, defensively.

    Distribution-packaged libraries report versions with non-numeric
    suffixes (``7.81.0+dfsg``, ``2.9.13-1ubuntu1``); the leading
    dotted-numeric prefix of each component is taken and the rest of
    the component discarded. A component with no leading digits at
    all makes the whole string unparseable.

    Args:
        left: The probed version string.
        right: The documented minimum version string.

    Returns:
        ``True`` when ``left`` is strictly below ``right``,
        ``False`` when it is at or above, or ``None`` when either
        string carries no parseable leading-numeric component (the
        caller turns ``None`` into a soft warning rather than an
        uncaught error; the ``make`` outcome stays authoritative).
    """
    left_parts = _numeric_parts(left)
    right_parts = _numeric_parts(right)
    if left_parts is None or right_parts is None:
        return None
    width = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (width - len(left_parts)))
    right_parts.extend([0] * (width - len(right_parts)))
    return left_parts < right_parts


def _numeric_parts(version: str) -> list[int] | None:
    """Return the dotted version's leading-numeric components, or ``None``.

    Each dot-separated component contributes its leading run of
    digits (``81`` from ``81+dfsg``); a component with no leading
    digit aborts the parse and yields ``None``.

    Args:
        version: A version string, possibly with packaging suffixes.

    Returns:
        The parsed integer components, or ``None`` when no leading
        numeric component could be extracted from the string.
    """
    parts: list[int] = []
    for component in version.strip().split("."):
        match = re.match(r"\d+", component.strip())
        if match is None:
            return None
        parts.append(int(match.group(0)))
    return parts if parts else None
