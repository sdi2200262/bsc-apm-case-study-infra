# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Per-(implementation, group) aggregation entry points.

Each ``run_*`` entry runs one rubric group for one implementation and
returns ``{rubric_id: (passed, summary, detail, mode)}`` for the scorer;
``__main__`` drives them in rubric order. The uniform groups (the C and
Python course and general suites, and the Python baseline) share one row
loop (``_run_rows``) and differ only in their ``(rubric_id, test)`` table,
whether a seed instant is threaded in, and whether each row runs under
valgrind. The three structurally distinct C groups keep dedicated entries:
the C baseline carries the protocol-frame rows C.2.1/C.2.2 ahead of its
valgrind rows, the C config surface restores provisioning in ``finally``,
and the C memory group gates each scenario on its predecessor rows.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from ...environment.provision import provision
from ..calibration import seed_instant
from . import (
    baseline,
    config_surface,
    course_announcements,
    frame,
    general_announcements,
    memory,
)
from ._support import Result5, record_mem

GroupResults = dict[str, tuple[bool, str, str, str | None]]
_RubricTests = tuple[tuple[str, Callable[..., Result5]], ...]

# C baseline valgrind rows C.2.3 through C.2.12 (C.2.1/C.2.2 are the
# protocol-frame rows handled directly by run_c_baseline).
_C_BASELINE_MEM_TESTS: _RubricTests = (
    ("C.2.3", baseline.check_authstatus_pre_login),
    ("C.2.4", baseline.check_login_success),
    ("C.2.5", baseline.check_authstatus_post_login),
    ("C.2.6", baseline.check_login_already),
    ("C.2.7", baseline.check_missing_credentials),
    ("C.2.8", baseline.check_get_courses_logged_in),
    ("C.2.9", baseline.check_logout_success),
    ("C.2.10", baseline.check_authstatus_post_logout),
    ("C.2.11", baseline.check_get_courses_not_logged_in),
    ("C.2.12", baseline.check_logout_no_op),
)

_PY_BASELINE_TESTS: _RubricTests = (
    ("P.1.1", frame.check_tools_list),
    ("P.1.2", baseline.check_authstatus_pre_login),
    ("P.1.3", baseline.check_login_success),
    ("P.1.4", baseline.check_authstatus_post_login),
    ("P.1.5", baseline.check_login_already),
    ("P.1.6", baseline.check_missing_credentials),
    ("P.1.7", baseline.check_get_courses_logged_in),
    ("P.1.8", baseline.check_logout_success),
    ("P.1.9", baseline.check_authstatus_post_logout),
    ("P.1.10", baseline.check_get_courses_not_logged_in),
    ("P.1.11", baseline.check_logout_no_op),
)

_C_COURSE_TESTS: _RubricTests = (
    ("C.3.1", course_announcements.check_course_not_logged_in),
    ("C.3.2", course_announcements.check_course_bad_url),
    ("C.3.3", course_announcements.check_course_negative_days),
    ("C.3.4", course_announcements.check_course_empty_window),
    ("C.3.5", course_announcements.check_course_days_zero),
    ("C.3.6", course_announcements.check_course_zero_absolute),
    ("C.3.7", course_announcements.check_course_default),
    ("C.3.8", course_announcements.check_course_days_10),
    ("C.3.9", course_announcements.check_course_days_40),
)

_PY_COURSE_TESTS: _RubricTests = (
    ("P.2.1", course_announcements.check_course_not_logged_in),
    ("P.2.2", course_announcements.check_course_bad_url),
    ("P.2.3", course_announcements.check_course_negative_days),
    ("P.2.4", course_announcements.check_course_empty_window),
    ("P.2.5", course_announcements.check_course_days_zero),
    ("P.2.6", course_announcements.check_course_zero_absolute),
    ("P.2.7", course_announcements.check_course_default),
    ("P.2.8", course_announcements.check_course_days_10),
    ("P.2.9", course_announcements.check_course_days_40),
)

_C_GENERAL_TESTS: _RubricTests = (
    ("C.4.1", general_announcements.check_general_not_logged_in),
    ("C.4.2", general_announcements.check_general_negative_days),
    ("C.4.3", general_announcements.check_general_over_thirty),
    ("C.4.4", general_announcements.check_general_days_zero),
    ("C.4.5", general_announcements.check_general_days_5),
    ("C.4.6", general_announcements.check_general_days_8),
    ("C.4.7", general_announcements.check_general_default),
)

_PY_GENERAL_TESTS: _RubricTests = (
    ("P.3.1", general_announcements.check_general_not_logged_in),
    ("P.3.2", general_announcements.check_general_negative_days),
    ("P.3.3", general_announcements.check_general_over_thirty),
    ("P.3.4", general_announcements.check_general_days_zero),
    ("P.3.5", general_announcements.check_general_days_5),
    ("P.3.6", general_announcements.check_general_days_8),
    ("P.3.7", general_announcements.check_general_default),
)


def run_python_baseline(eclass_dir: Path, mock_root: Path, debug: bool = False) -> GroupResults:
    """Run the Python baseline group (P.1.1 through P.1.11)."""
    return _run_rows("python", _PY_BASELINE_TESTS, eclass_dir, mock_root, debug)


def run_python_course_announcements(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> GroupResults:
    """Run the Python course-announcement group (P.2.1 through P.2.9)."""
    return _run_rows(
        "python",
        _PY_COURSE_TESTS,
        eclass_dir,
        mock_root,
        debug,
        instant=seed_instant(mock_root),
    )


def run_python_general_announcements(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> GroupResults:
    """Run the Python general-announcement group (P.3.1 through P.3.7)."""
    return _run_rows(
        "python",
        _PY_GENERAL_TESTS,
        eclass_dir,
        mock_root,
        debug,
        instant=seed_instant(mock_root),
    )


def run_c_baseline(
    eclass_dir: Path,
    mock_root: Path,
    debug: bool = False,
    passed_tests: Iterable[str] = (),
) -> GroupResults:
    """Run the C baseline group (C.2.1 through C.2.12).

    C.2.1 (the hand-written initialize frame) and C.2.2 (tools/list) are
    protocol-frame rows with no memory sub-assertion. C.2.3 through C.2.12
    run under valgrind; each records a functional row and a ``<id>.mem``
    sub-assertion scored only when the functional row passed.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.
        passed_tests: Unused; accepted so every C group entry takes a
            uniform call shape.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail, mode)``.
    """
    del passed_tests
    results: GroupResults = {}
    init_ok, init_msg, init_detail, _init_leak, init_mode = frame.check_initialize_frame(
        "c", eclass_dir, mock_root, debug
    )
    results["C.2.1"] = (init_ok, init_msg, init_detail, init_mode)
    tl_ok, tl_msg, tl_detail, _tl_leak, tl_mode = frame.check_tools_list(
        "c", eclass_dir, mock_root, debug
    )
    results["C.2.2"] = (tl_ok, tl_msg, tl_detail, tl_mode)
    results.update(
        _run_rows("c", _C_BASELINE_MEM_TESTS, eclass_dir, mock_root, debug, memcheck=True)
    )
    return results


def run_c_config(eclass_dir: Path, mock_root: Path, debug: bool = False) -> GroupResults:
    """Run the C configuration-surface probes (C.1.5, C.1.6).

    Runs the env-var probe then the verbatim-``.env`` probe, then restores
    the dual-provisioned tree in ``finally`` for the downstream functional
    and memory suites regardless of either probe's outcome.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail, mode)``;
        ``mode`` is ``None`` (a surface probe is a login-succeeded verdict,
        not a string match).
    """
    results: GroupResults = {}
    try:
        env_ok, env_msg, env_detail = config_surface.check_env_var_config_surface(
            eclass_dir, mock_root, debug
        )
        results["C.1.5"] = (env_ok, env_msg, env_detail, None)
        dot_ok, dot_msg, dot_detail = config_surface.check_dotenv_config_surface(
            eclass_dir, mock_root, debug
        )
        results["C.1.6"] = (dot_ok, dot_msg, dot_detail, None)
    finally:
        provision(eclass_dir, mock_root)
    return results


def run_c_course_announcements(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> GroupResults:
    """Run the C course-announcement group (C.3.1 through C.3.9, under valgrind)."""
    return _run_rows(
        "c",
        _C_COURSE_TESTS,
        eclass_dir,
        mock_root,
        debug,
        instant=seed_instant(mock_root),
        memcheck=True,
    )


def run_c_general_announcements(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> GroupResults:
    """Run the C general-announcement group (C.4.1 through C.4.7, under valgrind)."""
    return _run_rows(
        "c",
        _C_GENERAL_TESTS,
        eclass_dir,
        mock_root,
        debug,
        instant=seed_instant(mock_root),
        memcheck=True,
    )


def run_c_memory(
    eclass_dir: Path,
    mock_root: Path,
    debug: bool = False,
    passed_tests: Iterable[str] = (),
) -> GroupResults:
    """Run the C multi-step memory scenarios whose feature gates have passed.

    A scenario whose ``gates_on`` is not a subset of ``passed_tests`` is
    skipped (recorded as a zero-point fail naming the missing rows) rather
    than driven under valgrind on a path the participant did not implement.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: Unused; valgrind output is captured into the result detail.
        passed_tests: Rubric identifiers that have already passed this run.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail, mode)``;
        ``mode`` is ``None`` (a leak-hygiene verdict is not a string match).
    """
    del debug
    passed_set = frozenset(passed_tests)
    results: GroupResults = {}
    for scenario in memory.SCENARIOS:
        missing = tuple(test_id for test_id in scenario.gates_on if test_id not in passed_set)
        if missing:
            reason = (
                f"{scenario.scenario_id}: skipped, feature gate did not pass ({', '.join(missing)})"
            )
            results[scenario.scenario_id] = (False, reason, reason, None)
            continue
        ok, summary, detail = memory.run_scenario(scenario, eclass_dir, mock_root)
        results[scenario.scenario_id] = (ok, summary, detail, None)
    return results


def _run_rows(
    impl: str,
    tests: _RubricTests,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    *,
    instant: datetime | None = None,
    memcheck: bool = False,
) -> GroupResults:
    """Run a uniform sequence of rows and return their result mapping.

    Each row calls its test with ``(impl, eclass_dir, mock_root, debug)``,
    plus ``instant=`` when one is supplied (the announcement rows) and
    ``memcheck=True`` when requested (the C functional rows). When
    ``memcheck`` is set, a ``<id>.mem`` sub-assertion is recorded after
    each functional row from the row's leak verdict.

    Args:
        impl: ``"python"`` or ``"c"``.
        tests: The ordered ``(rubric_id, test)`` table for the group.
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.
        instant: The per-run seed instant for announcement rows, or
            ``None`` for baseline rows whose tests take no instant.
        memcheck: When ``True``, run each row under valgrind and record
            its ``<id>.mem`` sub-assertion.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail, mode)``,
        plus a ``<id>.mem`` entry per row when ``memcheck`` is set.
    """
    results: GroupResults = {}
    for test_id, fn in tests:
        if instant is None:
            ok, msg, detail, leak, mode = fn(impl, eclass_dir, mock_root, debug, memcheck=memcheck)
        else:
            ok, msg, detail, leak, mode = fn(
                impl, eclass_dir, mock_root, debug, instant=instant, memcheck=memcheck
            )
        results[test_id] = (ok, msg, detail, mode)
        if memcheck:
            record_mem(results, test_id, ok, leak)
    return results
