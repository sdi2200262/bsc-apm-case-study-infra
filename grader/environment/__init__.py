# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Sandbox-preparation layer.

Submodules:

- ``preflight``: HTTP probes against the grading environment.
- ``reset``: invokes the grading environment's reset script.
- ``patch``: git apply / cleanup against the eclass-mcp-server checkout.
- ``provision``: copies the ``.env`` and ``certs/`` into the checkout.
- ``env_file``: KEY=VALUE ``.env`` parser.
- ``build_python``: dependency install (``uv sync``), non-scored prerequisite.
- ``build_c``: ``compile_c_replica`` and ``verify_stack`` for the C replica.
"""

from __future__ import annotations
