# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Protocol-test subpackage.

Submodules:

- ``runner``: server-spawn helpers and JSON-RPC framing the
  assertion modules depend on.
- ``baseline_tests``: assertion functions for the ten baseline
  rubric rows (P.1.x / C.2.x), parameterised by implementation.
- ``course_announcements_tests``: assertion functions for the
  eight course-announcement rubric rows (P.2.x / C.3.x).
- ``general_announcements_tests``: assertion functions for the
  six general-announcement rubric rows (P.3.x / C.4.x).
- ``memory_tests``: the four memory-leak scenarios and the
  valgrind-driven runner the C.5.x rows depend on.
- ``python_baseline``, ``python_course_announcements``,
  ``python_general_announcements``, ``c_baseline``,
  ``c_course_announcements``, ``c_general_announcements``,
  ``c_memory``: thin aggregators that call the assertions with
  the matching ``impl`` and return the per-test-id result
  mapping the grader's CLI driver consumes.
"""
