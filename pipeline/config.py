#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Pipeline configuration: paths and the ``pipeline.yaml`` loader.

Each pipeline stage requires zero or more external paths to function:
the grade stage needs the grader, the ``eclass-mcp-server`` source
tree, and the testing-environment install; the parse stage needs the
parser source tree; every other stage needs only the dataset output
root. To keep CLI invocations short, the pipeline supports a
per-output-root ``pipeline.yaml`` file that declares default paths
the operator does not have to repeat on every invocation.

Resolution order for each path: CLI flag wins over ``pipeline.yaml``
value, which wins over absent. A stage that needs an absent path
raises ``PipelineConfigError`` at use time via :func:`require_path`;
the resolver itself does not raise on absence so that stages which
do not need a path can run without it.

The YAML's top-level shape:

    paths:
      grader_root: /path/to/bsc-apm-case-study-task/grader
      eclass_root: /path/to/eclass-mcp-server
      parser_root: /path/to/bsc-apm-case-study-task/parser
      mock_root: /path/to/bsc-apm-case-study-env

A missing ``paths`` section is treated as an empty mapping; absent
keys are treated as no default. The schema is extensible: unknown
top-level keys are tolerated for forward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import PipelineConfigError

DEFAULT_CONFIG_FILENAME = "pipeline.yaml"

KEY_PATHS = "paths"
KEY_GRADER_ROOT = "grader_root"
KEY_ECLASS_ROOT = "eclass_root"
KEY_PARSER_ROOT = "parser_root"
KEY_MOCK_ROOT = "mock_root"


@dataclass(frozen=True)
class PipelineConfig:
    """Resolved configuration for a pipeline invocation.

    Attributes:
        output_root: Mandatory dataset output root. The only path
            every stage needs.
        grader_root: Path to the ``bsc-apm-case-study-task/grader``
            tree, required by the grade stage. ``None`` when not
            configured.
        eclass_root: Path to the ``eclass-mcp-server`` clone,
            required by the grade stage so the grader's
            ``--eclass-dir`` flag can be populated. ``None`` when
            not configured.
        parser_root: Path to the ``bsc-apm-case-study-task/parser``
            tree, required by the parse stage so the parser
            subprocess can resolve ``cc_chat_parser`` on
            ``PYTHONPATH``. ``None`` when not configured.
        mock_root: Path to the ``bsc-apm-case-study-env`` install
            whose endpoints the grader probes and whose reset
            script the grader invokes between grading runs.
            ``None`` when not configured.
        config_path: Absolute path of the ``pipeline.yaml`` file
            the non-CLI defaults came from, or ``None`` when no
            config file was loaded.
    """

    output_root: Path
    grader_root: Path | None
    eclass_root: Path | None
    parser_root: Path | None
    mock_root: Path | None
    config_path: Path | None


def resolve_config(
    output_root: Path,
    config_override: Path | None = None,
    grader_root_flag: Path | None = None,
    eclass_root_flag: Path | None = None,
    parser_root_flag: Path | None = None,
    mock_root_flag: Path | None = None,
) -> PipelineConfig:
    """Resolve a ``PipelineConfig`` from CLI flags and an optional YAML file.

    Args:
        output_root: Mandatory dataset output root.
        config_override: Path to a YAML config file. When ``None``,
            the resolver tries ``<output-root>/pipeline.yaml`` and
            tolerates its absence; when set, the file must exist.
        grader_root_flag: CLI override for the grader path.
        eclass_root_flag: CLI override for the eclass path.
        parser_root_flag: CLI override for the parser path.
        mock_root_flag: CLI override for the testing environment
            install path.

    Returns:
        A populated ``PipelineConfig``.

    Raises:
        PipelineConfigError: When ``config_override`` is set but
            the file does not exist; when the YAML file exists but
            is malformed; when the YAML's top-level shape is wrong.
    """
    config_path, yaml_paths = _load_yaml_paths(config_override, output_root)
    grader_root = _resolve_path(grader_root_flag, yaml_paths.get(KEY_GRADER_ROOT))
    eclass_root = _resolve_path(eclass_root_flag, yaml_paths.get(KEY_ECLASS_ROOT))
    parser_root = _resolve_path(parser_root_flag, yaml_paths.get(KEY_PARSER_ROOT))
    mock_root = _resolve_path(mock_root_flag, yaml_paths.get(KEY_MOCK_ROOT))
    return PipelineConfig(
        output_root=output_root.resolve(),
        grader_root=grader_root,
        eclass_root=eclass_root,
        parser_root=parser_root,
        mock_root=mock_root,
        config_path=config_path,
    )


def require_path(value: Path | None, role: str, stage: str) -> Path:
    """Return ``value`` resolved to an absolute path, or raise.

    Used by stages whose work requires a configured path. The
    sentinel ``None`` carries through from ``resolve_config`` for
    paths that were not supplied; this helper converts the absence
    into a clean ``PipelineConfigError`` carrying the role and
    stage so the operator sees what is missing and where.

    Args:
        value: The candidate path, possibly ``None``.
        role: Human-readable role name (``"grader root"``,
            ``"eclass root"``, ``"parser root"``).
        stage: Stage name reporting the requirement.

    Returns:
        The path, resolved to an absolute path.

    Raises:
        PipelineConfigError: When ``value`` is ``None`` or does not
            exist on disk.
    """
    if value is None:
        raise PipelineConfigError(
            f"{stage}: missing {role}; supply via CLI flag or set in pipeline.yaml"
        )
    resolved = value.resolve()
    if not resolved.exists():
        raise PipelineConfigError(
            f"{stage}: configured {role} does not exist: {resolved}"
        )
    return resolved


def _load_yaml_paths(
    config_override: Path | None,
    output_root: Path,
) -> tuple[Path | None, dict[str, str]]:
    """Load the YAML config's ``paths`` mapping.

    When ``config_override`` is set the file must exist; an absent
    file raises ``PipelineConfigError``. When no override is set,
    the resolver tries ``<output-root>/pipeline.yaml`` and tolerates
    its absence (returns an empty mapping with no config path).
    """
    if config_override is not None:
        candidate = config_override
        if not candidate.exists():
            raise PipelineConfigError(
                f"config file does not exist: {candidate}"
            )
    else:
        candidate = output_root / DEFAULT_CONFIG_FILENAME
        if not candidate.exists():
            return None, {}
    payload = _read_yaml(candidate)
    if payload is None:
        return candidate.resolve(), {}
    if not isinstance(payload, dict):
        raise PipelineConfigError(
            f"config file at {candidate} must be a YAML mapping at the top level"
        )
    paths_section = payload.get(KEY_PATHS, {})
    if not isinstance(paths_section, dict):
        raise PipelineConfigError(
            f"config file at {candidate}: '{KEY_PATHS}' must be a mapping"
        )
    return candidate.resolve(), {
        str(key): str(value) for key, value in paths_section.items()
    }


def _read_yaml(path: Path) -> Any:
    """Read a YAML file and return the parsed payload (or ``None`` for empty files)."""
    try:
        with path.open("r", encoding="utf-8") as source:
            return yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise PipelineConfigError(
            f"invalid YAML in config file at {path}: {error}"
        ) from error


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
