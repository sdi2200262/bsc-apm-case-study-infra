#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
C memory phase aggregator: C.5.1 through C.5.4.
"""

from __future__ import annotations

from pathlib import Path

from . import memory_tests


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str]]:
    """Run every memory scenario and return the result mapping.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path
            (the C replica lives at ``c-replica/`` beneath it).
        mock_root: Resolved testing environment install path.
        debug: Reserved for parity with the other aggregators;
            valgrind output is captured into the result detail.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail)``.
    """
    del debug
    return {
        scenario.scenario_id: memory_tests.run_scenario(scenario, eclass_dir, mock_root)
        for scenario in memory_tests.SCENARIOS
    }
