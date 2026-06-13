# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Exception hierarchy for the grader package.

The CLI catches the base ``GraderError`` and reports a structured error
before a non-zero exit. Each raised message names the failing component,
the path or URL involved when applicable, and the operator action that
typically resolves it. Two subclasses live with the code that raises them,
``provision.ProvisioningError`` and ``calibration.CalibrationError``; the
rest are defined below.
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
    """Raised when the grading environment is not reachable or healthy.

    A pre-flight HTTP probe to the openeclass or mock CAS endpoint
    returned a non-2xx status, timed out, or could not connect.
    The grader cannot run useful tests without both services up.
    """


class ResetError(GraderError):
    """Raised when the grading environment's reset script fails.

    The script either could not be found at
    ``<mock-root>/scripts/reset`` or returned a non-zero exit code.
    The reset is required between grading runs to guarantee
    determinism.
    """
