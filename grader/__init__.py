# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Offline grader for BSc APM Case Study participant submissions.

Grades a participant's ``eclass-mcp-server`` patch against the grading
environment and writes a JSON results report scored against the rubric.
The work is split across four layers, an acyclic ``environment`` ->
``protocol`` -> ``scoring`` -> ``report`` flow:

- ``environment``: prepares the checkout (patch, provision, builds).
- ``protocol``: runs the MCP tests and records the per-row results.
- ``scoring``: the rubric authority and the score aggregator.
- ``report``: the JSON results artefact, console summary, notice policy.

The package is used through its command modules: ``python -m grader``
grades a patch, ``python -m grader.notes`` manages result annotations,
``python -m grader.inspect`` renders a results file for reading.
"""

from __future__ import annotations
