#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Exception hierarchy and child-failure message builders for the pipeline.

Each pipeline stage script catches the appropriate ``PipelineError``
subclass in its ``main()`` and reports a structured error to stderr
before returning a non-zero exit code. Custom exception types make
the failure mode visible in the source: a stage that fails because a
required input is absent raises ``StageInputError``; a stage that
fails because a subprocess returned non-zero raises
``StageExecutionError``; a configuration miss raises
``PipelineConfigError``; an invalid submission filename or zip
layout raises ``SubmissionFormatError``; manifest corruption raises
``ManifestError``.

Every exception message includes the submission name (when known),
the file path, and the stage name so the operator can point at the
broken state without further introspection.

A stage that subprocesses a child (the grader, the parser) builds
its ``StageExecutionError`` message through :func:`child_failure`,
so every such failure is reported identically: a signal kill is
classified as the signal number and a bounded tail of both
captured streams is included rather than only the last stderr line.
"""

from __future__ import annotations

import subprocess

CHILD_OUTPUT_TAIL_LINES = 20


class PipelineError(Exception):
    """Base for every error raised inside the pipeline package."""


class PipelineConfigError(PipelineError):
    """Raised when the pipeline configuration is missing or malformed.

    Triggered by a missing required path (no CLI flag and no
    ``pipeline.yaml`` value), a malformed YAML file, or a
    configured path that does not exist on disk.
    """


class SubmissionFormatError(PipelineError):
    """Raised when a submission filename or zip layout is invalid.

    Filename violations of the ``{PID}_S{1|2}_{apm|speckit}``
    pattern, missing or extra contents inside the zip, and
    non-JSONL files inside the transcripts directory are all
    surfaced through this exception.
    """


class ManifestError(PipelineError):
    """Raised when the manifest file is corrupt or inconsistent.

    Includes JSON decode failures, schema mismatches, and operator
    errors (asking for a stage that has not been executed).
    """


class StageInputError(PipelineError):
    """Raised when a stage's required input artifact is absent.

    For example, ``combine.py`` cannot run without both
    ``results.json`` and ``metrics.json`` already produced.
    Distinguished from ``StageExecutionError``: the stage has not
    started executing; an upstream stage was skipped or failed.
    """


class StageExecutionError(PipelineError):
    """Raised when a stage's external execution fails.

    Subprocess returning non-zero, schema mismatch in a parsed
    artifact, manifest update failing because of a concurrent
    writer, and similar runtime failures.
    """


def bounded_tail(label: str, text: str | None) -> str:
    """Return up to the last ``CHILD_OUTPUT_TAIL_LINES`` lines of ``text``, labelled.

    The captured tail is indented under a header naming the stream
    so it reads as nested context beneath the failure line that
    :func:`child_failure` emits, and is bounded so a verbose child
    cannot unbound the ``StageExecutionError`` message.

    Args:
        label: Stream name shown in the header (``"stdout"`` or
            ``"stderr"``).
        text: Captured stream content, possibly ``None`` or empty.

    Returns:
        A header line naming the stream followed by its last lines,
        or a single line stating the stream was empty.
    """
    lines = (text or "").strip().splitlines()
    if not lines:
        return f"  {label}: (empty)"
    tail = lines[-CHILD_OUTPUT_TAIL_LINES:]
    body = "\n".join(f"  {line}" for line in tail)
    return f"  {label} (last {len(tail)} line(s)):\n{body}"


def child_failure(
    prefix: str, completed: subprocess.CompletedProcess[str]
) -> str:
    """Build an actionable ``StageExecutionError`` message from a failed child.

    A negative return code is a signal kill under the POSIX
    convention, so it is reported as the signal number rather than
    the raw negative code; otherwise the non-zero exit code is
    reported. A bounded tail of both captured streams follows, so
    the operator sees the surrounding context and not only the last
    stderr line (and sees something at all on a signal kill, which
    leaves no final error line).

    Args:
        prefix: Stage-and-child label that opens the message, e.g.
            ``"grade: grader"`` or ``"parse: parser metrics mode"``.
        completed: The finished captured subprocess.

    Returns:
        A single multi-line ``StageExecutionError`` message string.
    """
    rc = completed.returncode
    how = f"died on signal {-rc}" if rc < 0 else f"exited {rc}"
    return "\n".join((
        f"{prefix} {how}",
        bounded_tail("stderr", completed.stderr),
        bounded_tail("stdout", completed.stdout),
    ))
