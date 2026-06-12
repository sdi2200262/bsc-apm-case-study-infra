#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Render an emitted metrics artifact in a human-readable form.

The canonical metrics artifact is a single nested JSON document
suited for downstream consumers but unwieldy for direct inspection.
This module reads such an artifact and prints a scope-by-scope
view to standard output, with the session-metadata header, the
parameters block, every measurement scope (session, each phase,
each role for APM submissions), the per-turn record-level
summary, and the diagnostics block.

Each measurement leaf is rendered with its value, label, and
constructed flag so the reader can tell at a glance which metrics
drive research-question claims (Primary), which support or
decompose them (Secondary), and which are descriptive only
(Supplementary). The constructed flag distinguishes metrics
defined for this study (true) from metrics that map directly onto
a JSONL, API, or grader field with aggregation as the only
study-author degree of freedom (false).

Invocation:
    python -m parser.inspect <metrics.json>

The single positional argument is the path to a metrics JSON file
the parser previously emitted via ``--metrics --output``.
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


def render_artifact(artifact: dict[str, Any]) -> None:
    """Print a scope-by-scope readable view of a metrics artifact."""
    _print_metadata(artifact["session_metadata"])
    _print_parameters(artifact["parameters"])
    _print_scope("session", artifact["session"])
    for phase, block in artifact["phases"].items():
        _print_scope(f"phase: {phase}", block)
    if "roles" in artifact:
        for role, block in artifact["roles"].items():
            _print_scope(f"role: {role}", block)
    _print_turns_summary(artifact["turns"])
    _print_diagnostics(artifact["diagnostics"])


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
        description="Render a metrics artifact JSON file in a human-readable form.",
    )
    parser.add_argument(
        "metrics_file",
        type=Path,
        help="Path to a metrics JSON file emitted by the parser's --metrics mode.",
    )
    args = parser.parse_args(argv)
    if not args.metrics_file.exists():
        log.error(f"file not found: {args.metrics_file}")
        return 1
    try:
        artifact = read_json(args.metrics_file)
    except (OSError, json.JSONDecodeError) as error:
        log.error(f"cannot read {args.metrics_file}: {error}")
        return 1
    if not isinstance(artifact, dict) or "session_metadata" not in artifact:
        log.error(
            f"{args.metrics_file} does not look like a metrics artifact "
            "(missing 'session_metadata' top-level key)"
        )
        return 1
    render_artifact(artifact)
    return 0


def _print_metadata(metadata: dict[str, Any]) -> None:
    """Render the session-metadata header."""
    _heading("session metadata")
    log.info(
        f"  model:                       {metadata['model']!r} (drift: {metadata['model_drift']})"
    )
    log.info(f"  cc_version:                  {metadata['cc_version']!r}")
    log.info(f"  auth_mode_indicator:         {metadata['auth_mode_indicator']!r}")
    log.info(f"  entrypoint:                  {metadata['entrypoint']!r}")
    log.info(f"  service_tier:                {metadata['service_tier']!r}")
    log.info(f"  session_start_timestamp:     {metadata['session_start_timestamp']}")
    log.info(f"  session_end_timestamp:       {metadata['session_end_timestamp']}")
    conversations = metadata["conversations"]
    log.info(f"  conversations: {len(conversations)}")
    for conv in conversations:
        log.info(
            f"    - {conv['role_key']:18} "
            f"session_id={(conv['session_id'] or '')[:8]} "
            f"records={conv['record_count']:>5} "
            f"first_command={conv['first_command']!r}"
        )


def _print_parameters(parameters: dict[str, Any]) -> None:
    """Render the parameters block."""
    _heading("parameters")
    for key, value in parameters.items():
        if isinstance(value, list):
            log.info(f"  {key}:")
            for item in value:
                log.info(f"    - {item}")
        else:
            log.info(f"  {key}: {value}")


def _print_scope(label: str, block: dict[str, Any]) -> None:
    """Render one scope's economic, process, and supplementary blocks."""
    _heading(f"scope: {label}")
    log.info("  economic:")
    _print_leaves(block["economic"], indent="    ")
    log.info("  process / time:")
    _print_leaves(block["process"]["time"], indent="    ")
    log.info("  process / user_input:")
    _print_leaves(block["process"]["user_input"], indent="    ")
    log.info("  supplementary:")
    _print_leaves(block["supplementary"], indent="    ")


def _print_leaves(block: dict[str, Any], indent: str) -> None:
    """Render the leaves of a metric block, one line per entry."""
    name_width = max((len(name) for name in block), default=0)
    for name, leaf in block.items():
        value = leaf["value"]
        label = leaf["label"]
        constructed = "constructed" if leaf["constructed"] else "direct"
        rendered_value = _render_value(value)
        log.info(f"{indent}{name:<{name_width}}  {rendered_value:>22}  [{label}, {constructed}]")


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


def _print_diagnostics(diagnostics: dict[str, Any]) -> None:
    """Render the diagnostics block, with invariant checks summarised."""
    _heading("diagnostics")
    invariants = diagnostics.get("invariant_checks", {})
    failures = {name: result for name, result in invariants.items() if result.get("status") != "ok"}
    log.info(
        f"  compaction_events_total:                  {diagnostics['compaction_events_total']}"
    )
    log.info(
        f"  cost_excludes_compaction_synthesis:       "
        f"{diagnostics['cost_excludes_compaction_synthesis']}"
    )
    log.info(
        f"  synthetic_assistant_records_excluded:     "
        f"{diagnostics['synthetic_assistant_records_excluded']}"
    )
    log.info(
        f"  errored_calls_excluded:                   "
        f"{diagnostics.get('errored_calls_excluded', 0)}"
    )
    log.info(f"  agent_dispatches_total:                   {diagnostics['agent_dispatches_total']}")
    log.info(
        f"  agent_dispatches_without_usage:           "
        f"{diagnostics['agent_dispatches_without_usage']}"
    )
    log.info(
        f"  subagent_files_seen:                      {diagnostics.get('subagent_files_seen', 0)}"
    )
    log.info(
        f"  subagent_models_indexed:                  "
        f"{diagnostics.get('subagent_models_indexed', 0)}"
    )
    distribution = diagnostics.get("model_token_distribution", {})
    if distribution:
        log.info("  model_token_distribution:")
        for model, tokens in sorted(distribution.items(), key=lambda item: item[1], reverse=True):
            log.info(f"    {model:30} {tokens:>14,}")
    log.info(
        f"  tool_result_count / tool_error_count:     "
        f"{diagnostics['tool_result_count']} / {diagnostics['tool_error_count']}"
    )
    log.info(
        f"  entrypoint_valid / auth_mode_valid:       "
        f"{diagnostics['entrypoint_valid']} / {diagnostics['auth_mode_valid']}"
    )
    log.info(
        f"  turns_with_missing_uuid:                  {diagnostics['turns_with_missing_uuid']}"
    )
    log.info(
        f"  queue_lifecycle_warnings:                 "
        f"{len(diagnostics.get('queue_lifecycle_warnings', []))}"
    )
    for warning in diagnostics.get("queue_lifecycle_warnings", []):
        log.info(f"    - {warning}")
    unknown = diagnostics.get("unknown_commands_observed", [])
    if unknown:
        log.info(f"  unknown_commands_observed:                {', '.join(unknown)}")
    log.info(
        f"  invariant_checks:                         "
        f"{len(invariants) - len(failures)} of {len(invariants)} pass"
    )
    for name, result in failures.items():
        log.info(
            f"    FAIL {name}: residual={result.get('residual')} "
            f"(left={result.get('left')}, right={result.get('right')})"
        )
    notes = diagnostics.get("notes", [])
    if notes:
        log.info("  notes:")
        for note in notes:
            log.info(f"    - {note}")
    by_file = diagnostics.get("compaction_events_by_file", {})
    if by_file:
        log.info("  compaction_events_by_file:")
        for path, count in by_file.items():
            log.info(f"    - {path}: {count}")


def _heading(label: str) -> None:
    """Emit a section heading framed by the logging module's separator rule."""
    log.blank()
    log.line()
    log.info(label.upper())
    log.line()


if __name__ == "__main__":
    sys.exit(main())
