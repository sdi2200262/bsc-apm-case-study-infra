# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Notice aggregation for the grader console summary.

A ``Notice`` represents a single human-review flag emitted during a
grading run. Two tags are in use:

- ``REVIEW``: rows whose acceptance was qualitatively ambiguous and
  requires human judgment before the result enters the cohort record.
  This covers rows accepted only via a lenient form and near-miss rows
  credited fractionally by partial credit (``verdict == "partial"``).
- ``WARNING``: objectively abnormal conditions that need no judgment
  to classify but that the analyst must be aware of.

``collect_notices`` is the sole aggregator; its docstring documents
the canonical ordering it produces. Rendering the notice tuple to the
terminal lives in the logging module (``grader.log.notice_block``);
this module owns the notice content, not its presentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol.matching import (
    ANNOUNCEMENTS_UNORDERED,
    CAP_DOCUMENTED,
    DESCRIPTION_PRESENCE_ONLY,
    GET_COURSES_DOCUMENTED,
    LENIENT_MODES,
    MISSING_CREDS_DOCUMENTED,
)
from ..scoring.scoring import Scorer

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
    MISSING_CREDS_DOCUMENTED: ("accepted via the documented one-sentence missing-credentials form"),
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

    Iterates the scorer's results in recording order (the order the
    rows were run and recorded). REVIEW notices are collected first,
    then WARNING notices, so the returned tuple always has all REVIEW
    entries before all WARNING entries within the group ordering.

    Args:
        scorer: Populated scorer whose results carry per-row
            diagnostic and pass/fail state.

    Returns:
        A tuple of ``Notice`` objects, REVIEW notices before
        WARNING notices, each group in recording order.
    """
    review: list[Notice] = []
    warning: list[Notice] = []

    for test_id, result in scorer.results.items():
        if result.verdict == "partial":
            similarity = result.similarity if result.similarity is not None else 0.0
            review.append(
                Notice(
                    tag=TAG_REVIEW,
                    label=test_id,
                    summary=(
                        f"partial credit at similarity {similarity:.3f}; "
                        "the metric proposes, the analyst ratifies or deducts"
                    ),
                    detail="cue: review for manual deduction",
                )
            )
        elif result.diagnostic in LENIENT_MODES:
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
                    summary=(
                        "handshake row failed; may be participant defect, "
                        "SDK change, or grader over-specification"
                    ),
                    detail=(
                        "inspect the JSON report and check for uniform "
                        "cohort failure before judging"
                    ),
                )
            )

    return tuple(review + warning)
