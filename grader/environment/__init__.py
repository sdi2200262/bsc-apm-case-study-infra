# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Sandbox-preparation layer.

Submodules:

- ``preflight``: HTTP probes against the testing environment.
- ``reset``: subprocess invocation of the testing environment's
  reset script.
- ``patch``: git apply / cleanup against the eclass-mcp-server
  checkout.
- ``provision``: copies the testing environment's ``.env`` and
  ``certs/`` into the checkout and mutates credentials per scenario.
- ``env_file``: KEY=VALUE ``.env`` parser.
- ``build_python``: dependency install (``uv sync``) for the
  Python implementation; runs as a non-scored prerequisite.
- ``build_c``: ``compile_c_replica`` (C.1.1) and ``verify_stack``
  (C.1.2) for the C replica.
"""

from __future__ import annotations
