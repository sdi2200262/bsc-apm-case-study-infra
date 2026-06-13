# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Claude Code transcript parser for BSc APM Case Study submissions.

Reads a submission's Claude Code CLI JSONL conversation files and emits
the data, metrics, and schema artifacts for the thesis case study. The
work is split across three layers, an acyclic ``data`` -> ``metrics`` ->
``report`` flow:

- ``data``: the sole JSONL reader; record schema, conversation and
  session assembly, and the per-scope aggregation series.
- ``metrics``: the study-defined formulas folded over the data layer.
- ``report``: artifact assembly, terminal rendering, and the
  review-notice policy.

The package is used through its command modules: ``python -m parser``
parses a submission's transcripts into artifacts and terminal views;
``python -m parser.notes`` manages the curated notes sidecar;
``python -m parser.inspect`` renders emitted artifacts.
"""

from __future__ import annotations
