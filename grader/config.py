# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Grader configuration: paths and the ``grader.yaml`` loader.

The grader needs two external paths to function: the eclass root (the
eclass-mcp-server clone the patch applies to) and the mock root (the
grading environment install whose endpoints the grader probes and whose
reset script it runs between grading runs). Each, plus the partial-credit
floor, can come from a CLI flag or a ``grader.yaml`` file; ``resolve_config``
owns the precedence (CLI over YAML over absent/default) and ``require_path``
turns a still-absent required path into a ``GraderConfigError`` at use time.

The YAML's top-level shape:

    paths:
      mock_root: /path/to/bsc-apm-case-study-task/installed-prefix
      eclass_root: /path/to/eclass-mcp-server
    partial:
      floor: 0.45

A missing ``paths`` or ``partial`` section is treated as an empty
mapping; absent keys are treated as no default. Unknown top-level keys
are tolerated for forward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import GraderConfigError

DEFAULT_CONFIG_FILENAME = "grader.yaml"

# Similarity floor at or above which a non-passing string row is
# credited as ``partial`` rather than ``failed``. Sits in the wide gap
# between near-misses (around 0.85) and genuine errors (around 0.18).
# Overridable via ``grader.yaml`` or the ``--partial-floor`` CLI flag.
DEFAULT_PARTIAL_FLOOR = 0.45

KEY_PATHS = "paths"
KEY_MOCK_ROOT = "mock_root"
KEY_ECLASS_ROOT = "eclass_root"
KEY_PARTIAL = "partial"
KEY_FLOOR = "floor"


@dataclass(frozen=True)
class GraderConfig:
    """Resolved configuration for a grader invocation.

    Attributes:
        mock_root: Path to the grading environment install whose
            endpoints the grader probes and whose reset script the
            grader invokes between grading runs. ``None`` when not
            configured.
        eclass_root: Path to the ``eclass-mcp-server`` clone the
            patch applies to. ``None`` when not configured.
        config_path: Absolute path of the ``grader.yaml`` file the
            non-CLI defaults came from, or ``None`` when no config
            file was loaded.
        partial_floor: Resolved similarity floor for partial credit
            (CLI over ``grader.yaml`` over ``DEFAULT_PARTIAL_FLOOR``).
    """

    mock_root: Path | None
    eclass_root: Path | None
    config_path: Path | None
    partial_floor: float


def resolve_config(
    config_override: Path | None = None,
    mock_root_flag: Path | None = None,
    eclass_root_flag: Path | None = None,
    partial_floor_flag: float | None = None,
    search_root: Path | None = None,
) -> GraderConfig:
    """Resolve a ``GraderConfig`` from CLI flags and an optional YAML file.

    Args:
        config_override: Path to a YAML config file. When ``None``,
            the resolver tries ``<search-root>/grader.yaml`` and
            tolerates its absence; when set, the file must exist.
        mock_root_flag: CLI override for the grading environment
            install path.
        eclass_root_flag: CLI override for the eclass-mcp-server
            clone path.
        partial_floor_flag: CLI override for the partial-credit
            similarity floor.
        search_root: Directory to search for a default
            ``grader.yaml``. Defaults to the current working
            directory.

    Returns:
        A populated ``GraderConfig``.

    Raises:
        GraderConfigError: When ``config_override`` is set but the
            file does not exist; when the YAML file exists but is
            malformed; when the YAML's top-level shape is wrong.
    """
    if search_root is None:
        search_root = Path.cwd()
    config_path, mapping = _load_config_mapping(config_override, search_root)
    paths = _paths_section(mapping, config_path)
    mock_root = _resolve_path(mock_root_flag, paths.get(KEY_MOCK_ROOT))
    eclass_root = _resolve_path(eclass_root_flag, paths.get(KEY_ECLASS_ROOT))
    partial_floor = _resolve_partial_floor(
        partial_floor_flag, _partial_floor_setting(mapping, config_path)
    )
    return GraderConfig(
        mock_root=mock_root,
        eclass_root=eclass_root,
        config_path=config_path,
        partial_floor=partial_floor,
    )


def require_path(value: Path | None, role: str, stage: str) -> Path:
    """Return ``value`` resolved to an absolute path, or raise.

    Used by callers whose work requires a configured path. The
    sentinel ``None`` carries through from ``resolve_config`` for
    paths that were not supplied; this helper converts the absence
    into a clean ``GraderConfigError`` carrying the role and the
    stage so the operator sees what is missing and where.

    Args:
        value: The candidate path, possibly ``None``.
        role: Human-readable role name (``"mock root"``,
            ``"eclass root"``).
        stage: Name of the step reporting the requirement.

    Returns:
        The path, resolved to an absolute path.

    Raises:
        GraderConfigError: When ``value`` is ``None`` or does not
            exist on disk.
    """
    if value is None:
        raise GraderConfigError(
            f"{stage}: missing {role}; supply via CLI flag or set in grader.yaml"
        )
    resolved = value.resolve()
    if not resolved.exists():
        raise GraderConfigError(f"{stage}: configured {role} does not exist: {resolved}")
    return resolved


def _load_config_mapping(
    config_override: Path | None,
    search_root: Path,
) -> tuple[Path | None, dict[str, Any]]:
    """Find and parse the YAML config's top-level mapping.

    When ``config_override`` is set the file must exist; an absent
    file raises ``GraderConfigError``. When no override is set, the
    resolver tries ``<search-root>/grader.yaml`` and tolerates its
    absence (an empty mapping, no config path). The file is read once
    here; ``_paths_section`` and ``_partial_floor_setting`` derive the
    individual settings from the returned mapping.

    Args:
        config_override: Explicit config path supplied by the
            caller, or ``None`` to fall back to the default search.
        search_root: Directory the default ``grader.yaml`` lookup
            uses when ``config_override`` is ``None``.

    Returns:
        ``(config_path, mapping)`` where ``config_path`` is the
        resolved YAML path (``None`` when no file was found) and
        ``mapping`` is the parsed top-level mapping (empty when no
        file or an empty file).

    Raises:
        GraderConfigError: When ``config_override`` is set but the
            file does not exist, or when the parsed YAML is not a
            mapping at the top level.
    """
    if config_override is not None:
        candidate = config_override
        if not candidate.exists():
            raise GraderConfigError(f"config file does not exist: {candidate}")
    else:
        candidate = search_root / DEFAULT_CONFIG_FILENAME
        if not candidate.exists():
            return None, {}
    parsed = _read_yaml(candidate)
    if parsed is None:
        return candidate.resolve(), {}
    if not isinstance(parsed, dict):
        raise GraderConfigError(
            f"config file at {candidate} must be a YAML mapping at the top level"
        )
    return candidate.resolve(), parsed


def _paths_section(mapping: dict[str, Any], config_path: Path | None) -> dict[str, str]:
    """Return the ``paths`` section as a string mapping (empty when absent).

    Args:
        mapping: The parsed top-level config mapping.
        config_path: The resolved config path, for error messages.

    Raises:
        GraderConfigError: When ``paths`` is present but not a mapping.
    """
    paths = mapping.get(KEY_PATHS, {})
    if not isinstance(paths, dict):
        raise GraderConfigError(f"config file at {config_path}: '{KEY_PATHS}' must be a mapping")
    return {str(key): str(value) for key, value in paths.items()}


def _partial_floor_setting(mapping: dict[str, Any], config_path: Path | None) -> float | None:
    """Return the ``partial.floor`` value, or ``None`` when absent.

    Args:
        mapping: The parsed top-level config mapping.
        config_path: The resolved config path, for error messages.

    Raises:
        GraderConfigError: When ``partial`` is not a mapping or its
            ``floor`` is not a number.
    """
    partial = mapping.get(KEY_PARTIAL, {})
    if not isinstance(partial, dict):
        raise GraderConfigError(f"config file at {config_path}: '{KEY_PARTIAL}' must be a mapping")
    floor = partial.get(KEY_FLOOR)
    if floor is None:
        return None
    if isinstance(floor, bool) or not isinstance(floor, (int, float)):
        raise GraderConfigError(
            f"config file at {config_path}: '{KEY_PARTIAL}.{KEY_FLOOR}' must be a number"
        )
    return float(floor)


def _read_yaml(path: Path) -> Any:
    """Read a YAML file and return the parsed payload (or ``None`` for empty files).

    Args:
        path: YAML file to read.

    Returns:
        The parsed payload, or ``None`` when the file is empty.

    Raises:
        GraderConfigError: When the YAML cannot be parsed.
    """
    try:
        with path.open("r", encoding="utf-8") as source:
            return yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise GraderConfigError(f"invalid YAML in config file at {path}: {error}") from error


def _resolve_path(
    flag_value: Path | None,
    yaml_value: str | None,
) -> Path | None:
    """Return the CLI flag when set, otherwise the YAML value as a Path, otherwise ``None``."""
    if flag_value is not None:
        return Path(flag_value)
    if yaml_value is not None:
        return Path(yaml_value)
    return None


def _resolve_partial_floor(
    flag_value: float | None,
    yaml_value: float | None,
) -> float:
    """Return the floor: CLI flag over ``grader.yaml`` over the module default."""
    if flag_value is not None:
        return flag_value
    if yaml_value is not None:
        return yaml_value
    return DEFAULT_PARTIAL_FLOOR
