# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Protocol-test subpackage.

Submodules:

- ``runner``: server-spawn helpers and JSON-RPC framing.
- ``_memcheck``: valgrind stderr parsing helpers used by ``runner``.
- ``calibration``: per-run seed-apply instant from MariaDB.
- ``seed``: pinned grading-environment seed loader; exposes
  username, password, enrolled course codes, per-course
  announcements, admin announcements, and per-window helpers.
- ``expected``: constructs the faithful openeclass response
  strings for the exact-string scenario assertions.
- ``matching``: the single acceptance policy (byte-exact vs.
  whitespace-normalised, the ``get_courses`` accept-set, the
  reference-derived initialize frame) and the recorded match mode.
- ``announcement_matching``: announcement-response parsing and date
  canonicalisation, extracted from ``matching``.
- ``groups``: the per-(implementation, group) run entry points over
  one shared row loop, alongside the per-group assertion suites they
  drive (baseline, frame, announcement, memory, and configuration-
  surface checks) and their shared result scaffolding; see its own
  inventory. The entry points return the per-test-id result mapping
  the grader CLI driver consumes.
- ``_jsonrpc_io``: line-level JSON-RPC stdio reads and the shared
  outgoing-frame serializer; exposes ``set_compact_emission`` so the
  CLI driver can select compact emission once for the whole run.
"""

from __future__ import annotations

from ._jsonrpc_io import set_compact_emission

__all__ = ["set_compact_emission"]
