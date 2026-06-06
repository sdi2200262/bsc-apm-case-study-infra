# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Offline grader for BSc APM Case Study participant submissions.

Grades a participant's ``eclass-mcp-server`` patch against the testing
environment and writes a JSON results report scored against the rubric.
The work is split across three subpackages:
- ``environment``: testing-environment preflight, reset, provisioning,
  and the Python/C builds.
- ``protocol``: the per-phase test aggregators and the JSON-RPC client
  that drives the participant's MCP server.
- ``scoring``: rubric scoring, the JSON and console reporting, and the
  review-notice policy.

The package is used through its command modules:
- ``python -m grader`` grades a patch.
- ``python -m grader.notes`` manages the hand-written result annotations.
- ``inspect.py`` renders a results file for reading.
"""

from __future__ import annotations
