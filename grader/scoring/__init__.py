# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Scoring layer: the rubric and the score aggregation over recorded results.

This layer owns the rubric authority and folds the per-row results the
``protocol`` layer records into the aggregate score nodes. It imports
the root leaves only; nothing in this layer reads the MCP wire or writes
output. It is imported by ``report``; ``protocol`` records into its
``Scorer`` without importing it back.

Submodules:

- ``rubric``: the test definitions and their per-group groupings.
- ``scoring``: the ``Scorer`` aggregator.
"""

from __future__ import annotations
