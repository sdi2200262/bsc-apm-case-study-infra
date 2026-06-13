# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Rubric-group runners and the per-group assertion suites.

``runners`` holds the eight ``run_*`` entry points the grader CLI drives
in rubric order, re-exported here so ``groups.run_*`` resolves unchanged.

- ``runners``: the eight ``run_*`` group entry points.
- ``baseline``: baseline rubric rows (P.1.x / C.2.x).
- ``frame``: tools/list and C-only initialize-frame rows.
- ``course_announcements``: course-announcement rows (P.2.x / C.3.x).
- ``general_announcements``: general-announcement rows (P.3.x / C.4.x).
- ``memory``: C.5.x multi-step memory scenarios under valgrind.
- ``config_surface``: configuration-surface probes (C.1.5, C.1.6).
- ``_support``: shared result shape, step-failure sentinels, ``.mem`` recording.
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
