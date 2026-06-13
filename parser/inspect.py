#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Render emitted parser artifacts in a human-readable form.

The parser's per-session artifacts are nested JSON documents suited for
downstream consumers but unwieldy for direct inspection. This module reads
the data artifact (and, when given, the metrics artifact) and prints a
scope-by-scope view: the identity header, the run-input metadata, every
measurement scope (session, each phase, each role for APM submissions) with
its data leaves and, when the metrics artifact is supplied, its metric
leaves, and a per-call and per-turn summary.

Leaves are bare ``name: value``; the kind, label, and formula of each
measurement live in the schema artifact (``--schema``), not inline.

Invoked as ``python -m parser.inspect <parser_data.json>
[<parser_metrics.json>]``; the two positional arguments are documented on
``main``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import log
from .data.jsonl import read_json

_BUCKET_KEYS = ("protocol", "short", "standard")


def render_artifacts(data: dict[str, Any], metrics: dict[str, Any] | None) -> None:
    """Print a scope-by-scope readable view of the data and metrics artifacts."""
    _print_identity(data["identity"])
    _print_mapping("metadata", data["metadata"])
    metric_scopes = metrics["scopes"] if metrics is not None else {}
    _print_scope("session", data["scopes"]["session"], metric_scopes.get("session"))
    for phase, block in data["scopes"]["phases"].items():
        _print_scope(f"phase: {phase}", block, metric_scopes.get("phases", {}).get(phase))
    for role, block in data["scopes"].get("roles", {}).items():
        _print_scope(f"role: {role}", block, metric_scopes.get("roles", {}).get(role))
    _print_calls_summary(data["calls"])
    _print_turns_summary(data["turns"])


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` on success, non-zero on error.
    """
    parser = argparse.ArgumentParser(
        prog="python -m parser.inspect",
        description="Render the parser's data and metrics artifacts in a human-readable form.",
    )
    parser.add_argument(
        "data_file",
        type=Path,
        help="Path to the parser_data.json artifact emitted by --metrics.",
    )
    parser.add_argument(
        "metrics_file",
        type=Path,
        nargs="?",
        default=None,
        help="Optional path to the matching parser_metrics.json artifact.",
    )
    args = parser.parse_args(argv)
    data = _load_artifact(args.data_file)
    if data is None:
        return 1
    if not isinstance(data, dict) or "identity" not in data:
        log.error(
            f"{args.data_file} does not look like a data artifact "
            "(missing 'identity' top-level key)"
        )
        return 1
    metrics: dict[str, Any] | None = None
    if args.metrics_file is not None:
        metrics = _load_artifact(args.metrics_file)
        if metrics is None:
            return 1
    render_artifacts(data, metrics)
    return 0


def _load_artifact(path: Path) -> dict[str, Any] | None:
    """Read a JSON artifact, logging and returning ``None`` on failure."""
    if not path.exists():
        log.error(f"file not found: {path}")
        return None
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        log.error(f"cannot read {path}: {error}")
        return None


def _print_identity(identity: dict[str, Any]) -> None:
    """Render the identity header."""
    _heading("identity")
    log.info(f"  model:                       {identity['model']!r}")
    log.info(f"  cc_version:                  {identity['cc_version']!r}")
    log.info(f"  session_start:               {identity['session_start']}")
    log.info(f"  session_end:                 {identity['session_end']}")
    conversations = identity["conversations"]
    log.info(f"  conversations: {len(conversations)}")
    for conv in conversations:
        log.info(
            f"    - {conv['role_key']:18} "
            f"session_id={(conv['session_id'] or '')[:8]} "
            f"records={conv['record_count']:>5} "
            f"first_command={conv['first_command']!r}"
        )


def _print_mapping(label: str, mapping: dict[str, Any]) -> None:
    """Render a flat key-value block such as metadata."""
    _heading(label)
    for key, value in mapping.items():
        log.info(f"  {key}: {value}")


def _print_scope(
    label: str, data_block: dict[str, Any], metric_block: dict[str, Any] | None
) -> None:
    """Render one scope's data leaves and, when present, its metric leaves."""
    _heading(f"scope: {label}")
    log.info("  data:")
    _print_leaves(data_block, indent="    ")
    if metric_block is not None:
        log.info("  metrics:")
        _print_leaves(metric_block, indent="    ")


def _print_leaves(block: dict[str, Any], indent: str) -> None:
    """Render the bare leaves of a scope block, one line per entry."""
    name_width = max((len(name) for name in block), default=0)
    for name, value in block.items():
        log.info(f"{indent}{name:<{name_width}}  {_render_value(value):>22}")


def _render_value(value: Any) -> str:
    """Return a compact string representation of a leaf's value."""
    if isinstance(value, dict):
        if set(value.keys()) >= set(_BUCKET_KEYS):
            return " ".join(f"{bucket}={value[bucket]:.4f}" for bucket in _BUCKET_KEYS)
        return ", ".join(f"{k}={v}" for k, v in value.items())
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _print_calls_summary(calls: list[dict[str, Any]]) -> None:
    """Render a one-line summary of the per-call series."""
    _heading(f"calls ({len(calls)} total)")
    if not calls:
        log.info("  (no calls)")
        return
    by_model: dict[str, int] = {}
    for call in calls:
        by_model[call["model"]] = by_model.get(call["model"], 0) + 1
    for model, count in sorted(by_model.items(), key=lambda item: item[1], reverse=True):
        log.info(f"    {model:30} {count:>6}")


def _print_turns_summary(turns: list[dict[str, Any]]) -> None:
    """Render a compact per-turn summary table."""
    _heading(f"turns ({len(turns)} total)")
    if not turns:
        log.info("  (no turns)")
        return
    log.info(
        f"  {'#':>4}  {'role_key':<18} {'phase':<14} "
        f"{'duration_s':>11} {'steers':>7}  start_timestamp"
    )
    for index, turn in enumerate(turns, start=1):
        log.info(
            f"  {index:>4}  "
            f"{(turn['role_key'] or ''):<18} "
            f"{(turn['phase'] or ''):<14} "
            f"{turn['duration_seconds']:>11.2f} "
            f"{turn['steer_count']:>7}  "
            f"{turn['start_timestamp']}"
        )


def _heading(label: str) -> None:
    """Emit a section heading framed by the logging module's separator rule."""
    log.blank()
    log.line()
    log.info(label.upper())
    log.line()


if __name__ == "__main__":
    sys.exit(main())
