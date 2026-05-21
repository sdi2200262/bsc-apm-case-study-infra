# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Protocol-test subpackage.

Submodules:

- ``runner``: server-spawn helpers and JSON-RPC framing.
- ``_memcheck``: valgrind stderr parsing helpers used by ``runner``.
- ``calibration``: per-run seed-apply instant from MariaDB.
- ``expected``: constructs the faithful openeclass response
  strings for the exact-string scenario assertions.
- ``matching``: the single acceptance policy (byte-exact vs.
  whitespace-normalised, the ``get_courses`` accept-set, the
  reference-derived initialize frame) and the recorded match mode.
- ``baseline_tests``: assertion functions for the baseline rubric
  rows (P.1.x / C.2.x), parameterised by implementation.
- ``course_announcements_tests``: assertion functions for the
  course-announcement rubric rows (P.2.x / C.3.x).
- ``general_announcements_tests``: assertion functions for the
  general-announcement rubric rows (P.3.x / C.4.x).
- ``memory_tests``: the three C.5.x multi-step memory scenarios.
- ``config_surface``: the two positive configuration-surface
  probes (C.1.5, C.1.6).
- ``python_baseline``, ``python_course_announcements``,
  ``python_general_announcements``, ``c_baseline``,
  ``c_course_announcements``, ``c_general_announcements``,
  ``c_config``, ``c_memory``: thin aggregators that call
  assertions with the matching ``impl`` and return the
  per-test-id result mapping the grader CLI driver consumes.
"""
