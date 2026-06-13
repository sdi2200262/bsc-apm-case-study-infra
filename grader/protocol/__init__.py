# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Protocol-test subpackage: drive a spawned MCP server and grade its replies.

Submodules:

- ``runner``: server-spawn helpers and JSON-RPC framing.
- ``_jsonrpc_io``: line-level JSON-RPC stdio reads and the frame serializer.
- ``_memcheck``: valgrind stderr parsing for the C replica scenarios.
- ``calibration``: per-run seed-apply instant from MariaDB.
- ``seed``: pinned grading-environment seed loader and per-window helpers.
- ``expected``: constructs the faithful openeclass response strings.
- ``matching``: the single acceptance policy and the recorded match mode.
- ``announcement_matching``: announcement-response parsing and dates.
- ``groups``: the per-(implementation, group) run entry points and suites.

Re-exports ``set_compact_emission`` so the CLI driver can select compact
frame emission once for the whole run.
"""

from __future__ import annotations

from ._jsonrpc_io import set_compact_emission

__all__ = ["set_compact_emission"]
