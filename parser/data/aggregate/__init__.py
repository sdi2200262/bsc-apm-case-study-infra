# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Per-scope data aggregation and the granular per-call and per-turn series.

Submodules:

- ``call_records``: the shared main-call selection rule and the per-call
  and per-dispatch model-resolution series the token and cost folds consume.
- ``turn_series``: per-turn data (duration, steer and request counts, the
  per-turn phase-request share).
- ``tokens``: per-scope token sums, the model-token distribution, and the
  dispatch-resolution provenance.
- ``counts``: every count (requests, subagents, tools, turns, steers) and
  the per-prompt bucket-and-length series the turn-prompt metric folds.
"""

from __future__ import annotations
