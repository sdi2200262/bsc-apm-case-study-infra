# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Results-artifact writer: the machine-readable grading report.

The JSON report at ``<workspace>/grader_results.json`` (or the
``grader_results_compact_serialization.json`` sidecar for a compact run)
is the machine-readable artefact the inspect browser reads. Its body is
``Scorer.to_dict`` verbatim under a ``metadata`` block; this module
resolves the output path and writes it, deriving no score of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..json_io import write_json
from ..scoring.scoring import Scorer

# Fixed filename for the secondary report a compact run writes beside
# the canonical results file. Constant, not patch-derived.
COMPACT_REPORT_NAME = "grader_results_compact_serialization.json"


@dataclass(frozen=True)
class ReportPaths:
    """Output paths the report writer targets.

    Attributes:
        workspace_root: Resolved directory the reports are written
            into. The grader uses the parent of the eclass-mcp-server
            checkout so the reports sit beside the patched tree.
        patch_name: The patch's stem, carried into the report's
            ``metadata`` block; the filename is fixed and independent of
            it.
        json_path: Full path to the JSON report written for the run:
            the fixed canonical ``grader_results.json``, or the fixed
            ``grader_results_compact_serialization.json`` for a compact run.
    """

    workspace_root: Path
    patch_name: str
    json_path: Path


def report_paths(workspace_root: Path, patch_name: str, compact: bool = False) -> ReportPaths:
    """Resolve the JSON report path for a grading run.

    Args:
        workspace_root: Directory the report is written into.
        patch_name: The patch's stem, recorded in the report
            ``metadata``; it does not shape the filename.
        compact: When ``True``, target the secondary
            ``grader_results_compact_serialization.json`` instead of the
            canonical report.

    Returns:
        The resolved report paths for the run.
    """
    workspace_root = Path(workspace_root).resolve()
    filename = COMPACT_REPORT_NAME if compact else "grader_results.json"
    return ReportPaths(
        workspace_root=workspace_root,
        patch_name=patch_name,
        json_path=workspace_root / filename,
    )


def write_report(
    paths: ReportPaths,
    scorer: Scorer,
    metadata: dict | None = None,
) -> Path:
    """Write the machine-readable JSON report.

    Args:
        paths: Report path resolution from ``report_paths``.
        scorer: Populated scorer whose ``to_dict`` output is
            embedded in the report.
        metadata: Optional extra fields merged into the report's
            ``metadata`` block.

    Returns:
        The JSON path that was written.
    """
    payload = {
        "metadata": {
            "patch_name": paths.patch_name,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {}),
        },
        **scorer.to_dict(),
    }
    write_json(payload, paths.json_path)
    return paths.json_path
