# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
BSc APM Case Study grader package.

Source modules:

- ``config``: path resolution from CLI flags or grader.yaml.
- ``errors``: GraderError exception hierarchy.
- ``preflight``: HTTP probes against the testing environment.
- ``reset``: subprocess invocation of the testing environment's
  reset script.
- ``patch``: git apply / cleanup against the eclass-mcp-server
  checkout.
- ``build_python``: dependency install (``uv sync``) for the
  Python implementation; runs as a non-scored prerequisite.
- ``build_c``: ``compile_c_replica`` (C.1.1) and
  ``verify_stack`` (C.1.2) for the C replica.
- ``seed``: pinned testing-environment seed loader; exposes
  username, password, enrolled course codes, per-course
  announcements, admin announcements, and per-window helpers.
- ``scoring``: rubric definitions and the ``Scorer`` aggregator.
- ``reporting``: JSON, text, and console report writers.
- ``protocol``: MCP-server-driving protocol-test subpackage.
"""
