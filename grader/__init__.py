# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Offline grader for BSc APM Case Study participant submissions.

Grades a participant's ``eclass-mcp-server`` patch against the grading
environment and writes a JSON results report scored against the rubric.

Subpackages:
- ``environment``: preflight, reset, provisioning, Python/C builds.
- ``protocol``: per-group test aggregators and the JSON-RPC client.
- ``scoring``: rubric scoring, JSON/console reporting, notice policy.

Command modules: ``python -m grader`` grades a patch,
``python -m grader.notes`` manages result annotations, ``inspect.py``
renders a results file for reading.
"""

from __future__ import annotations
