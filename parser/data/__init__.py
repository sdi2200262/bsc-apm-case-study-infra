# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Data layer: the sole reader of the conversation JSONL, emitting data values.

This layer reads and parses the transcript, assembles the typed
``Session``, derives turns, assigns roles and phases, and aggregates
per-scope data (token sums, counts, the per-call and per-turn series,
and identity facts). It is imported by ``metrics`` and
``report`` and imports only sibling data modules and the root leaves;
nothing in this layer imports from ``metrics`` or ``report``.

Submodules:

- ``jsonl``: line and JSON reading, sanitised-payload detection.
- ``schema``: the ``Record`` type, record-type constants, field extractors.
- ``conversation``: the per-file ``Conversation`` load and its indices.
- ``subagent_models``: sibling subagent model index and fallback resolver.
- ``commands``: framework, role, and phase command vocabulary.
- ``prompts``: user-record predicates.
- ``buckets``: input-size bucket classifier.
- ``apm_roles`` / ``speckit_phases``: framework role and phase assignment.
- ``turns``: turn derivation.
- ``session``: ``Session`` assembly and the session identity facts.
- ``aggregate``: per-scope data aggregation and the granular series.
"""

from __future__ import annotations
