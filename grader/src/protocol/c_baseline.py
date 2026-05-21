#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C baseline phase aggregator: C.2.1 through C.2.12.

C.2.1 (initialize frame) and C.2.2 (tools/list) are protocol-only
assertions that carry no memory sub-assertion. C.2.3 through C.2.12
run under valgrind via ``memcheck=True`` and each records two
results: the functional verdict ``<id>`` and the memory sub-assertion
``<id>.mem`` scored only if the functional assertion passed.

C.2.1 is judged against a constructed ``initialize`` expected response with
two accepted capability forms (see :mod:`.expected`); nothing is
captured from the submission and no server is spawned to derive the
contract. The matched capability form is recorded as the row's
diagnostic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from . import baseline_tests
from ._assertion_support import Result5, record_mem

IMPL = "c"

_MEM_TESTS: tuple[tuple[str, Callable[..., Result5]], ...] = (
    ("C.2.3", baseline_tests.test_authstatus_pre_login),
    ("C.2.4", baseline_tests.test_login_success),
    ("C.2.5", baseline_tests.test_authstatus_post_login),
    ("C.2.6", baseline_tests.test_login_already),
    ("C.2.7", baseline_tests.test_missing_credentials),
    ("C.2.8", baseline_tests.test_get_courses_logged_in),
    ("C.2.9", baseline_tests.test_logout_success),
    ("C.2.10", baseline_tests.test_authstatus_post_logout),
    ("C.2.11", baseline_tests.test_get_courses_not_logged_in),
    ("C.2.12", baseline_tests.test_logout_no_op),
)


def run(
    eclass_dir: Path,
    mock_root: Path,
    debug: bool = False,
    passed_tests: Iterable[str] = (),
) -> dict[str, tuple[bool, str, str, str | None]]:
    """Run every C baseline assertion and return the result mapping.

    C.2.1 is judged against the constructed ``initialize`` expected response,
    recording the matched capability form as its diagnostic.
    C.2.3 through C.2.12 run with ``memcheck=True``; each records a
    functional result under ``<id>`` and a memory sub-assertion under
    ``<id>.mem``. The memory sub-assertion passes only when the
    functional assertion passed AND the valgrind run was leak-clean.
    C.2.1 and C.2.2 carry no memory sub-assertion.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.
        passed_tests: Unused; kept for signature parity with
            ``c_memory.run``.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail,
        mode)``; the functional row carries the ``matching`` mode it
        was accepted under, the ``.mem`` sub-assertion carries
        ``None`` (a leak verdict is not a string match).
    """
    del passed_tests
    results: dict[str, tuple[bool, str, str, str | None]] = {}

    init_ok, init_msg, init_detail, _init_leak, init_mode = (
        baseline_tests.test_initialize_frame(
            IMPL, eclass_dir, mock_root, debug
        )
    )
    results["C.2.1"] = (init_ok, init_msg, init_detail, init_mode)
    tl_ok, tl_msg, tl_detail, _tl_leak, tl_mode = baseline_tests.test_tools_list(
        IMPL, eclass_dir, mock_root, debug
    )
    results["C.2.2"] = (tl_ok, tl_msg, tl_detail, tl_mode)

    for test_id, fn in _MEM_TESTS:
        ok, msg, detail, leak, mode = fn(
            IMPL, eclass_dir, mock_root, debug, memcheck=True
        )
        results[test_id] = (ok, msg, detail, mode)
        no_verdict_msg = (
            f"skipped: {test_id} produced no leak verdict "
            "(server did not start)"
        )
        record_mem(results, test_id, ok, leak, no_verdict_msg)

    return results
