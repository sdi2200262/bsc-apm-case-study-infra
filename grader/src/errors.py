#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Exception hierarchy for the grader package.

Each grader module raises the appropriate ``GraderError`` subclass
on failure; the top-level ``grade`` script catches the base
``GraderError`` and reports a structured error to stderr before
returning a non-zero exit code. Custom exception types make the
failure mode visible in the source: a configuration miss raises
``GraderConfigError``; an unreachable testing environment raises
``PreflightError``; a reset script that returns non-zero raises
``ResetError``.

Every exception message includes the failing component, the path
or URL involved when applicable, and the operator action that
typically resolves the failure.
"""

from __future__ import annotations


class GraderError(Exception):
    """Base for every error raised inside the grader package."""


class GraderConfigError(GraderError):
    """Raised when the grader configuration is missing or malformed.

    Triggered by a missing required path (no CLI flag and no
    ``grader.yaml`` value), a malformed YAML file, or a configured
    path that does not exist on disk.
    """


class PreflightError(GraderError):
    """Raised when the testing environment is not reachable or healthy.

    A pre-flight HTTP probe to the openeclass or mock CAS endpoint
    returned a non-2xx status, timed out, or could not connect.
    The grader cannot run useful tests without both services up.
    """


class ResetError(GraderError):
    """Raised when the testing environment's reset script fails.

    The script either could not be found at
    ``<mock-root>/scripts/reset`` or returned a non-zero exit code.
    The reset is required between grading runs to guarantee
    determinism.
    """
