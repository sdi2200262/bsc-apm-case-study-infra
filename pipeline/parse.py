#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Run the parser on a validated submission's transcripts and promote the artifacts.

This stage takes the unpacked submission's ``transcripts/``
directory under ``<output-root>/_staging/<manifest_key>/``,
invokes ``cc_chat_parser`` against it twice (once with
``--metrics`` to compute the canonical scope-nested artifact, and
once with ``--sanitize`` to seal each ``*.jsonl`` for archival),
and promotes the outputs into
``<output-root>/<PID>/<S{n}>_<framework>/``: ``metrics.json``
alongside a ``sanitized_transcripts/`` directory containing the
sealed sidecar files.

The parser subprocess inherits ``CC_PARSER_SECRET`` from the
calling environment for sanitisation; the secret is not surfaced
on the command line. The framework flag the parser receives is
derived from the submission filename's third segment, never
inferred from transcript content.

The parser package's location on disk is given by ``--parser-root``
(or ``paths.parser_root`` in ``pipeline.yaml``). The pipeline sets
``PYTHONPATH`` to that root so the subprocess imports
``cc_chat_parser`` regardless of the working directory.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import resolve_config, require_path
from .errors import (
    PipelineError,
    StageExecutionError,
    StageInputError,
)
from .io import compute_checksum
from .manifest import (
    STAGE_PARSE,
    STATUS_SUCCESS,
    add_stage,
    load_manifest,
    save_manifest,
)
from .submissions import (
    SubmissionName,
    parse_submission_name,
    participant_subdir,
)

PARSER_PACKAGE_NAME = "cc_chat_parser"
TRANSCRIPTS_DIRNAME = "transcripts"
SANITIZED_DIRNAME = "sanitized_transcripts"
METRICS_FILENAME = "metrics.json"
STAGING_DIRNAME = "_staging"
SECRET_ENV_VAR = "CC_PARSER_SECRET"
SANITIZED_PREFIX = "sanitized_"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the parse stage.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` on success, ``1`` on a recovered
        error (missing input, parser failure, manifest issue),
        ``2`` on operator error (missing flags, missing paths).
    """
    args = _parse_args(argv)
    try:
        config = resolve_config(
            output_root=args.output_root,
            config_override=args.config,
            parser_root_flag=args.parser_root,
        )
        parser_root = require_path(config.parser_root, "parser root", "parse")
        submission = parse_submission_name(args.submission_name)
        transcripts_dir = _require_validated_transcripts(config.output_root, submission)
        target_dir = config.output_root / participant_subdir(submission)
        target_dir.mkdir(parents=True, exist_ok=True)
        metrics_target = target_dir / METRICS_FILENAME
        sanitized_dir = target_dir / SANITIZED_DIRNAME
        sanitized_dir.mkdir(parents=True, exist_ok=True)
        env = _prepare_subprocess_env(parser_root)
        _invoke_metrics(env, parser_root, transcripts_dir, submission, metrics_target)
        if not args.no_sanitize:
            sanitized_files = _invoke_sanitize_and_promote(
                env, parser_root, transcripts_dir, sanitized_dir
            )
        else:
            sanitized_files = []
        manifest = load_manifest(config.output_root)
        manifest = add_stage(
            manifest,
            submission.manifest_key,
            STAGE_PARSE,
            STATUS_SUCCESS,
            framework=submission.framework,
            input_transcripts_count=_count_transcripts(transcripts_dir),
            output_metrics=str(metrics_target.relative_to(config.output_root)),
            output_checksum=compute_checksum(metrics_target),
            sanitized_files=sanitized_files,
        )
        save_manifest(manifest)
    except StageInputError as error:
        print(f"error: parse input missing: {error}", file=sys.stderr)
        return 1
    except StageExecutionError as error:
        print(f"error: parse failed: {error}", file=sys.stderr)
        return 1
    except PipelineError as error:
        print(f"error: pipeline error: {error}", file=sys.stderr)
        return 1
    print(
        f"parsed: {submission.manifest_key} "
        f"({len(sanitized_files)} sanitised transcript file"
        f"{'s' if len(sanitized_files) != 1 else ''}); "
        f"metrics at {metrics_target.relative_to(config.output_root)}"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.parse",
        description=(
            "Run the parser on a validated submission's transcripts; "
            "promote the metrics JSON and sealed sidecars to the "
            "per-participant directory."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "submission_name",
        help=(
            "Submission manifest key ({PID}_S{1|2}_{apm|speckit}); the "
            "validate stage must have unpacked this submission to "
            "<output-root>/_staging/<manifest_key>/."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Dataset output root directory.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional pipeline.yaml path; defaults to <output-root>/pipeline.yaml.",
    )
    parser.add_argument(
        "--parser-root",
        type=Path,
        default=None,
        help="Path to the parser directory (overrides pipeline.yaml).",
    )
    parser.add_argument(
        "--no-sanitize",
        action="store_true",
        help=(
            "Skip the sanitisation pass; only write metrics.json. The "
            "raw transcripts in staging stay untouched and no sealed "
            "sidecars are produced."
        ),
    )
    return parser.parse_args(argv)


def _require_validated_transcripts(
    output_root: Path,
    submission: SubmissionName,
) -> Path:
    """Return the staged ``transcripts/`` directory for a submission, or raise."""
    staging = output_root / STAGING_DIRNAME / submission.manifest_key
    transcripts = staging / TRANSCRIPTS_DIRNAME
    if not transcripts.is_dir():
        raise StageInputError(
            f"parse: staged transcripts directory not found at {transcripts}; "
            "run pipeline.validate first"
        )
    return transcripts


def _count_transcripts(transcripts_dir: Path) -> int:
    """Return the number of ``*.jsonl`` files in a transcripts directory."""
    return sum(1 for entry in transcripts_dir.iterdir() if entry.suffix == ".jsonl")


def _prepare_subprocess_env(parser_root: Path) -> dict[str, str]:
    """Return an environment dict with ``PYTHONPATH`` extended for the parser."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{parser_root}{os.pathsep}{existing}" if existing else str(parser_root)
    )
    return env


def _invoke_metrics(
    env: dict[str, str],
    parser_root: Path,
    transcripts_dir: Path,
    submission: SubmissionName,
    metrics_target: Path,
) -> None:
    """Run ``python -m cc_chat_parser <transcripts> --framework X --metrics -o <out>``."""
    cmd = [
        sys.executable,
        "-m",
        PARSER_PACKAGE_NAME,
        str(transcripts_dir),
        "--framework",
        submission.framework,
        "--metrics",
        "-o",
        str(metrics_target),
    ]
    completed = subprocess.run(
        cmd,
        cwd=parser_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "").strip().splitlines()[-1:] or [""]
        raise StageExecutionError(
            f"parse: parser metrics mode exited {completed.returncode}: "
            f"{stderr_tail[0]}"
        )
    if not metrics_target.is_file():
        raise StageExecutionError(
            f"parse: parser did not produce metrics JSON at {metrics_target}"
        )


def _invoke_sanitize_and_promote(
    env: dict[str, str],
    parser_root: Path,
    transcripts_dir: Path,
    sanitized_dir: Path,
) -> list[str]:
    """Run the parser's sanitise mode and move sealed sidecars into the dataset.

    The parser writes ``sanitized_<stem>.json`` next to each input
    JSONL inside ``transcripts_dir``; this helper then moves each
    sealed sidecar into ``sanitized_dir`` so the staging area stays
    free of dataset-bound artifacts and the dataset directory
    accumulates sealed transcripts only.
    """
    if not env.get(SECRET_ENV_VAR):
        raise StageInputError(
            f"parse: {SECRET_ENV_VAR} environment variable must be set "
            "for sanitisation"
        )
    cmd = [
        sys.executable,
        "-m",
        PARSER_PACKAGE_NAME,
        str(transcripts_dir),
        "--sanitize",
    ]
    completed = subprocess.run(
        cmd,
        cwd=parser_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "").strip().splitlines()[-1:] or [""]
        raise StageExecutionError(
            f"parse: parser sanitise mode exited {completed.returncode}: "
            f"{stderr_tail[0]}"
        )
    promoted: list[str] = []
    candidates = list(transcripts_dir.glob(f"{SANITIZED_PREFIX}*.json")) + list(
        transcripts_dir.glob(f"*/subagents/{SANITIZED_PREFIX}*.json")
    )
    for entry in candidates:
        if not entry.name.startswith(SANITIZED_PREFIX) or entry.suffix != ".json":
            continue
        relative = entry.relative_to(transcripts_dir)
        destination = sanitized_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(entry), str(destination))
        promoted.append(str(relative))
    promoted.sort()
    return promoted


if __name__ == "__main__":
    sys.exit(main())
