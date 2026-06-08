# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Grader configuration: paths and the ``grader.yaml`` loader.

The grader requires two external paths to function:
- the eclass root: the eclass-mcp-server clone the patch applies to.
- the mock root: the grading environment install whose endpoints the
  grader probes and whose reset script it runs between grading runs.

Each path can be supplied via a CLI flag or a ``grader.yaml`` file
colocated with the invocation. Resolution order: CLI flag wins over the
``grader.yaml`` value, which wins over absent. A consumer that needs an
absent path raises ``GraderConfigError`` at use time via
``require_path``; the resolver itself does not raise on absence, so a
caller that does not need a path can run without it.

The YAML's top-level shape:

    paths:
      mock_root: /path/to/bsc-apm-case-study-task/installed-prefix
      eclass_root: /path/to/eclass-mcp-server

A missing ``paths`` section is treated as an empty mapping; absent
keys are treated as no default. Unknown top-level keys are
tolerated for forward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import GraderConfigError

DEFAULT_CONFIG_FILENAME = "grader.yaml"

KEY_PATHS = "paths"
KEY_MOCK_ROOT = "mock_root"
KEY_ECLASS_ROOT = "eclass_root"


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
    """

    mock_root: Path | None
    eclass_root: Path | None
    config_path: Path | None


def resolve_config(
    config_override: Path | None = None,
    mock_root_flag: Path | None = None,
    eclass_root_flag: Path | None = None,
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
    config_path, yaml_paths = _load_yaml_paths(config_override, search_root)
    mock_root = _resolve_path(mock_root_flag, yaml_paths.get(KEY_MOCK_ROOT))
    eclass_root = _resolve_path(eclass_root_flag, yaml_paths.get(KEY_ECLASS_ROOT))
    return GraderConfig(
        mock_root=mock_root,
        eclass_root=eclass_root,
        config_path=config_path,
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


def _load_yaml_paths(
    config_override: Path | None,
    search_root: Path,
) -> tuple[Path | None, dict[str, str]]:
    """Load the YAML config's ``paths`` mapping.

    When ``config_override`` is set the file must exist; an absent
    file raises ``GraderConfigError``. When no override is set,
    the resolver tries ``<search-root>/grader.yaml`` and tolerates
    its absence (returns an empty mapping with no config path).

    Args:
        config_override: Explicit config path supplied by the
            caller, or ``None`` to fall back to the default search.
        search_root: Directory the default ``grader.yaml`` lookup
            uses when ``config_override`` is ``None``.

    Returns:
        ``(config_path, paths_mapping)`` where ``config_path`` is the
        resolved YAML path (``None`` when no default file was found)
        and ``paths_mapping`` is the parsed ``paths`` section.

    Raises:
        GraderConfigError: When ``config_override`` is set but the
            file does not exist, or when the parsed YAML is not a
            mapping or its ``paths`` section is not a mapping.
    """
    if config_override is not None:
        candidate = config_override
        if not candidate.exists():
            raise GraderConfigError(f"config file does not exist: {candidate}")
    else:
        candidate = search_root / DEFAULT_CONFIG_FILENAME
        if not candidate.exists():
            return None, {}
    payload = _read_yaml(candidate)
    if payload is None:
        return candidate.resolve(), {}
    if not isinstance(payload, dict):
        raise GraderConfigError(
            f"config file at {candidate} must be a YAML mapping at the top level"
        )
    paths_section = payload.get(KEY_PATHS, {})
    if not isinstance(paths_section, dict):
        raise GraderConfigError(f"config file at {candidate}: '{KEY_PATHS}' must be a mapping")
    return candidate.resolve(), {str(key): str(value) for key, value in paths_section.items()}


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
