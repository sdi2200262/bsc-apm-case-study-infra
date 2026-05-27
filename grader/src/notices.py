#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Notice aggregation and rendering for the grader console summary.

A :class:`Notice` represents a single human-review flag emitted
during a grading run. Two tags are in use: ``REVIEW`` for rows whose
acceptance was qualitatively ambiguous and requires human judgment
before the result enters the cohort record, and ``WARNING`` for
objectively abnormal conditions that need no judgment to classify but
that the analyst must be aware of.

:func:`collect_notices` is the sole aggregator. It reads the
populated :class:`~grader.src.scoring.Scorer` and returns a frozen
tuple of notices in the canonical order: all REVIEW notices first
(sorted by test row id), then all WARNING notices (sorted by test row
id). :func:`print_notice_block` renders that tuple to stdout in the
shared contract format.
"""

from __future__ import annotations

from dataclasses import dataclass

from .protocol.matching import (
    ANNOUNCEMENTS_UNORDERED,
    CAP_DOCUMENTED,
    DESCRIPTION_PRESENCE_ONLY,
    GET_COURSES_DOCUMENTED,
    LENIENT_MODES,
)
from .scoring import Scorer

TAG_REVIEW = "REVIEW"
TAG_WARNING = "WARNING"

# Plain-words label per lenient form shown in REVIEW notices.
# ``LENIENT_MODES`` is the single source of which modes are lenient;
# this map is presentation only. An unmapped future lenient mode falls
# back to a generic phrase so adding a new mode requires only the
# ``matching`` constant.
_LENIENT_FORM_PHRASE: dict[str, str] = {
    ANNOUNCEMENTS_UNORDERED: "accepted via the order-insensitive announcement form",
    GET_COURSES_DOCUMENTED: "accepted via the documented-clean get_courses form",
    CAP_DOCUMENTED: "accepted via the documented initialize.capabilities form",
    DESCRIPTION_PRESENCE_ONLY: (
        "accepted via the presence-only description check; "
        "review the participant's wording in the response below"
    ),
}

# Rubric rows whose pass/fail depends on SDK-emitted serialisation
# rather than the participant's own response body. A failure here may
# reflect a participant defect, an SDK behavioural change since the
# expected values were captured, or a grader over-specification.
HANDSHAKE_ROW_IDS: frozenset[str] = frozenset({"P.1.1", "C.2.1", "C.2.2"})


@dataclass(frozen=True)
class Notice:
    """A single human-review flag from a grading run.

    Attributes:
        tag: ``"REVIEW"`` or ``"WARNING"``.
        label: Short identifier for the flagged item, typically a
            test row id (e.g. ``"P.1.1"``).
        summary: One-sentence description of why the row is flagged.
        detail: Elaboration for the reviewer; equals ``summary`` when
            no additional context exists.
    """

    tag: str
    label: str
    summary: str
    detail: str


def collect_notices(scorer: Scorer) -> tuple[Notice, ...]:
    """Aggregate all review and warning notices for a grading run.

    Iterates the scorer's results in check order (the order tests are
    registered in the rubric). REVIEW notices are collected first,
    then WARNING notices, so the returned tuple always has all REVIEW
    entries before all WARNING entries within the group ordering.

    Args:
        scorer: Populated scorer whose results carry per-row
            diagnostic and pass/fail state.

    Returns:
        A tuple of :class:`Notice` objects, REVIEW notices before
        WARNING notices, each group in check order.
    """
    review: list[Notice] = []
    warning: list[Notice] = []

    for test_id, result in scorer.results.items():
        if result.diagnostic in LENIENT_MODES:
            diagnostic = result.diagnostic or ""
            phrase = _LENIENT_FORM_PHRASE.get(
                diagnostic,
                f"accepted via a lenient form ({diagnostic})",
            )
            review.append(
                Notice(
                    tag=TAG_REVIEW,
                    label=test_id,
                    summary=phrase,
                    detail="cue: review for manual deduction",
                )
            )

    for test_id, result in scorer.results.items():
        if test_id in HANDSHAKE_ROW_IDS and not result.passed:
            warning.append(
                Notice(
                    tag=TAG_WARNING,
                    label=test_id,
                    summary="handshake row failed; may be participant defect, SDK change, or grader over-specification",
                    detail=(
                        "inspect the JSON report and check for uniform cohort failure before judging"
                    ),
                )
            )

    return tuple(review + warning)


def print_notice_block(notices: tuple[Notice, ...]) -> None:
    """Render a tuple of notices to stdout.

    Emits one blank line before the block, then each notice in order.
    Returns immediately without printing anything when ``notices`` is
    empty.

    Each notice renders as:
    - ``[{tag}]`` on its own line, no indentation.
    - ``  label: {label}`` with two-space indent.
    - ``  {summary}`` with two-space indent.
    - Each line of ``detail`` (split on embedded newlines) with
      two-space indent.

    No separator between notices of the same tag. No trailing blank
    line after the final notice.

    Args:
        notices: Tuple of notices to render, ordered REVIEW before
            WARNING within each group.
    """
    if not notices:
        return
    print()
    for notice in notices:
        print(f"[{notice.tag}]")
        print(f"  label: {notice.label}")
        print(f"  {notice.summary}")
        for line in notice.detail.split("\n"):
            print(f"  {line}")
