# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Metrics layer: study-defined formulas over the data layer.

Each module folds a study-defined formula, ratio, or statistic over
values the data layer already produced; nothing in this layer reads
the conversation JSONL. It imports ``data`` and the root leaves and is
imported by ``report``.

Submodules:

- ``cost``: per-call API-equivalent cost against the rate table.
- ``time``: turn-time decomposition, inter-turn time, duration, and the
  per-turn duration distribution statistics.
- ``user_input``: bucket shares and per-bucket mean magnitudes.
- ``reliability``: tool-call success rate.
"""

from __future__ import annotations
