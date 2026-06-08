# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Rubric-group runners and the per-group assertion suites.

``runners`` holds the eight ``run_*`` entry points the grader CLI drives
in rubric order; each runs one rubric group for one implementation over
the shared row loop. The assertion suites it calls live beside it:

- ``baseline``: the baseline rubric rows (P.1.x / C.2.x).
- ``frame``: the tools/list and C-only initialize-frame checks.
- ``course_announcements``: the course-announcement rows (P.2.x / C.3.x).
- ``general_announcements``: the general-announcement rows (P.3.x / C.4.x).
- ``memory``: the three C.5.x multi-step memory scenarios under valgrind.
- ``config_surface``: the two configuration-surface probes (C.1.5, C.1.6).
- ``_support``: the shared result shape, step-failure sentinels, and the
  ``.mem`` sub-assertion recording the suites share.

The eight entry points are re-exported here so ``from .protocol import
groups`` and ``groups.run_*`` resolve unchanged for the CLI driver.
"""

from __future__ import annotations

from .runners import (
    run_c_baseline,
    run_c_config,
    run_c_course_announcements,
    run_c_general_announcements,
    run_c_memory,
    run_python_baseline,
    run_python_course_announcements,
    run_python_general_announcements,
)

__all__ = [
    "run_c_baseline",
    "run_c_config",
    "run_c_course_announcements",
    "run_c_general_announcements",
    "run_c_memory",
    "run_python_baseline",
    "run_python_course_announcements",
    "run_python_general_announcements",
]
