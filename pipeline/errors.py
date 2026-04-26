#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Exception hierarchy for the data-processing pipeline.

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
"""

from __future__ import annotations


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
