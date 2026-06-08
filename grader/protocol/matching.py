# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Centralised acceptance policy for the exact-string scenario assertions.

``expected`` constructs the faithful openeclass output; this module owns
the single decision of whether a tool response is accepted and, when it is,
which form it took. Every string-matched rubric row runs its response
through one matcher here and records the returned diagnostic as an unscored
annotation, so the report states how each row matched rather than only that
it passed. A matcher returns ``None`` when the response is not accepted; the
caller treats that as a failed row and records no diagnostic.

Two kinds of diagnostic are recorded. The fixed-string rows record a
strictness mode:

- ``BYTE_EXACT``: the response equalled the constructed expected string byte
  for byte.
- ``WHITESPACE_NORMALIZED``: it equalled only after the non-breaking space
  family was mapped to an ASCII space. The PRD requires rendered text to
  carry normalised whitespace, so a date rendered with a narrow no-break
  space and one rendered with a plain space are the same answer.

The two-form rows instead record which of two accepted forms matched,
evaluated in order through ``_try_forms``: each matcher supplies its own
per-form predicates while the dispatch (try in order, label the first match)
lives in one place. Each pair has a faithful first form and a lenient second
form; the lenient forms are collected in ``LENIENT_MODES``, which
``grader.scoring.notices`` imports to warn a human, at end of grading, of
every row accepted only via a lenient form. The announcement two-form
matcher lives in ``announcement_matching``, which imports the mode constants
and the shared dispatch from this module.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .expected import (
    BASELINE_TOOL_NAMES,
    CAPABILITIES_DOCUMENTED,
    CAPABILITIES_FAITHFUL,
    INITIALIZE_PROTOCOL_VERSION,
    INITIALIZE_SERVER_INFO,
    expected_tools_list,
    get_courses_forms,
)
from .seed import Course

BYTE_EXACT = "byte-exact"
WHITESPACE_NORMALIZED = "whitespace-normalized"

# The two ``initialize`` capability forms, recorded as the row's
# diagnostic so the report states which contract the frame satisfied.
# The published wire-protocol reference and the MCP SDK's actual
# serialisation disagree on the capabilities object; both readings of
# the task material are accepted, with ``CAP_DOCUMENTED`` flagged for
# human review (see ``LENIENT_MODES``).
CAP_FAITHFUL = "capabilities-faithful"
CAP_DOCUMENTED = "capabilities-documented"

# The announcement and ``get_courses`` success rows record the
# accepted FORM as the diagnostic, not a strictness mode: the PRD
# does not mandate a presentation order, so the matcher accepts the
# openeclass-derived ordered form OR an order-insensitive form, and
# which one matched is the fact a reviewer acts on. The existing
# non-breaking-space normalisation is applied within each form
# unconditionally (the PRD whitespace rule), so a separate strictness
# mode would add no decision and is not surfaced for these rows.
ANNOUNCEMENTS_ORDERED = "announcements-ordered"
ANNOUNCEMENTS_UNORDERED = "announcements-unordered"
GET_COURSES_FAITHFUL = "get-courses-faithful"
GET_COURSES_DOCUMENTED = "get-courses-documented"

# The missing-credentials error row records the accepted FORM as its
# diagnostic. The Python reference emits a two-sentence error; the
# reference doc documents a one-sentence form. Both are legitimate
# readings of the published task material, so both are accepted, with
# the documented one-sentence form gated to the C replica and flagged
# for human review (see ``LENIENT_MODES``).
MISSING_CREDS_FAITHFUL = "missing-creds-faithful"
MISSING_CREDS_DOCUMENTED = "missing-creds-documented"

# Recorded on the ``tools/list`` row when at least one announcement
# tool's ``description`` was accepted via the presence check; see
# ``match_tools_list`` for the contract split.
DESCRIPTION_PRESENCE_ONLY = "description-presence-only"

# The lenient (second) accepted forms. ``notices`` imports this
# single set to detect, at end of grading, every row accepted only
# via a lenient form and warn a human to review it. Adding a future
# lenient form requires only extending this constant.
LENIENT_MODES = frozenset(
    {
        ANNOUNCEMENTS_UNORDERED,
        GET_COURSES_DOCUMENTED,
        CAP_DOCUMENTED,
        DESCRIPTION_PRESENCE_ONLY,
        MISSING_CREDS_DOCUMENTED,
    }
)

# The platform's locale date renderer emits U+202F (a narrow
# no-break space) before the meridiem under recent CLDR; the same
# layer can emit U+00A0 and the thin/figure spaces elsewhere. The
# PRD requires rendered text to carry normalised whitespace, so the
# comparison maps this space family to a plain ASCII space on both
# sides. Only the space codepoint is changed, character for
# character: newlines, indentation, and every other byte stay exact,
# so the date value, the response format, ordering, and structure
# remain fully asserted.
_SPACE_FAMILY = (0x00A0, 0x2007, 0x2009, 0x202F)
_SPACE_NORMALISATION = {codepoint: " " for codepoint in _SPACE_FAMILY}


def normalize_response(text: str) -> str:
    """Return ``text`` with the non-breaking space family mapped to ASCII space.

    Args:
        text: A tool response or a constructed expected response.

    Returns:
        ``text`` with U+00A0/U+2007/U+2009/U+202F replaced by a
        plain space; all other characters, including newlines and
        indentation, are unchanged.
    """
    return text.translate(_SPACE_NORMALISATION)


def match_exact(actual: str, expected: str) -> str | None:
    """Return ``BYTE_EXACT`` when ``actual`` equals ``expected`` byte for byte.

    Used by the error, empty-window, and fixed baseline-literal rows
    whose contract is a single invariant string with no rendered
    whitespace to normalise.

    Args:
        actual: The tool's response text.
        expected: The invariant expected string.

    Returns:
        ``BYTE_EXACT`` on an exact match, otherwise ``None``.
    """
    return BYTE_EXACT if actual == expected else None


def match_response(actual: str, expected: str) -> str | None:
    """Return the match mode for an announcement-response comparison.

    ``BYTE_EXACT`` when the two are byte-equal; otherwise
    ``WHITESPACE_NORMALIZED`` when they are equal after the
    non-breaking space family is mapped to an ASCII space on both
    sides; otherwise ``None``. Every difference other than that
    space family (count, ordering, titles, bodies, the date value
    and format, the entry structure) still fails the match.

    Args:
        actual: The tool's response text.
        expected: The constructed expected response.

    Returns:
        The match mode, or ``None`` when the two do not match even
        after whitespace normalisation.
    """
    if actual == expected:
        return BYTE_EXACT
    if normalize_response(actual) == normalize_response(expected):
        return WHITESPACE_NORMALIZED
    return None


def match_get_courses(
    text: str,
    courses: tuple[Course, ...],
    allow_documented_clean: bool,
) -> str | None:
    """Return the matched ``get_courses`` form, or ``None``.

    ``tools-reference.md`` documents a clean format while the Python
    reference server reproduces the openeclass layout glue; both are
    legitimate readings of the task materials. The Python reference
    must emit the openeclass-formatted form, so only that form is a
    candidate for it; the C replica may emit either. Each candidate
    is judged by ``match_response``, so the brittle U+00A0/CRLF/
    space glue is tolerated exactly as the rendered dates are. The
    recorded diagnostic is the matched layout: ``GET_COURSES_FAITHFUL``
    for the openeclass-formatted layout, ``GET_COURSES_DOCUMENTED``
    for the documented-clean layout. The documented-clean layout is a
    lenient acceptance and is warned for human review at end of
    grading (see ``grader.scoring.notices``).

    Args:
        text: The tool's response text.
        courses: The user's courses in title-alphabetical order.
        allow_documented_clean: When ``True`` (the C replica) the
            documented-clean layout is also an accepted candidate;
            when ``False`` (the Python reference) only the
            openeclass-formatted form is.

    Returns:
        ``GET_COURSES_FAITHFUL`` or ``GET_COURSES_DOCUMENTED`` for
        the matched layout, ``None`` when no candidate matches (a
        missing or extra course, a wrong title/code/URL, a wrong
        order, or a wrong count grammar all fall here).
    """
    faithful, documented_clean = get_courses_forms(courses)
    forms: list[tuple[str, Callable[[], bool]]] = [
        (GET_COURSES_FAITHFUL, lambda: match_response(text, faithful) is not None),
    ]
    if allow_documented_clean:
        forms.append(
            (
                GET_COURSES_DOCUMENTED,
                lambda: match_response(text, documented_clean) is not None,
            )
        )
    return _try_forms(forms)


def match_missing_credentials(
    text: str,
    faithful: str,
    documented: str,
    allow_documented: bool,
) -> str | None:
    """Return the matched missing-credentials error form, or ``None``.

    The Python reference server emits a two-sentence error verbatim;
    the reference doc documents a one-sentence form. Both are
    legitimate readings of the published task material, so both are
    candidates, with the documented form gated to the C replica and
    flagged for human review. Each candidate is compared byte for
    byte; this row carries no rendered text whose whitespace family
    could differ.

    Args:
        text: The tool's response text.
        faithful: The two-sentence error the Python reference emits.
        documented: The one-sentence error the reference doc documents.
        allow_documented: When ``True`` (the C replica) the documented
            one-sentence form is also accepted; when ``False`` only the
            two-sentence faithful form is.

    Returns:
        ``MISSING_CREDS_FAITHFUL`` or ``MISSING_CREDS_DOCUMENTED`` for
        the matched form, ``None`` when neither matches.
    """
    forms: list[tuple[str, Callable[[], bool]]] = [
        (MISSING_CREDS_FAITHFUL, lambda: text == faithful),
    ]
    if allow_documented:
        forms.append((MISSING_CREDS_DOCUMENTED, lambda: text == documented))
    return _try_forms(forms)


def match_initialize(actual_result: dict) -> str | None:
    """Return the matched ``initialize`` capability form, or ``None``.

    ``protocolVersion`` and ``serverInfo`` must equal the invariant
    constructed constants exactly. The ``capabilities`` object is
    then matched against the two accepted forms: the faithful form
    (what the SDK serialises for a tools-only server) yields
    ``CAP_FAITHFUL``; the documented form (what the wire-protocol
    reference literally specifies) yields ``CAP_DOCUMENTED``. The
    documented form is a lenient acceptance and is warned for human
    review at end of grading (see ``grader.scoring.notices``). Only
    these three fields are the contract; an ``initialize`` result
    may carry further fields (an ``instructions`` string, SDK
    metadata) and those are outside the row's contract and ignored.
    The expected values are constructed; nothing here is captured
    from the submission.

    Args:
        actual_result: The replica's ``initialize`` result object.

    Returns:
        ``CAP_FAITHFUL`` or ``CAP_DOCUMENTED`` for the matched
        capability form; ``None`` when the protocol version, server
        info, or capabilities object does not match either accepted
        form.
    """
    if actual_result.get("protocolVersion") != INITIALIZE_PROTOCOL_VERSION:
        return None
    if actual_result.get("serverInfo") != INITIALIZE_SERVER_INFO:
        return None
    capabilities = actual_result.get("capabilities")
    return _try_forms(
        [
            (CAP_FAITHFUL, lambda: capabilities == CAPABILITIES_FAITHFUL),
            (CAP_DOCUMENTED, lambda: capabilities == CAPABILITIES_DOCUMENTED),
        ]
    )


def match_tools_list(
    actual: list[dict],
) -> tuple[bool, str, str | None]:
    """Return whether ``tools/list`` matches the expected tool list.

    The six-object contract splits by tool name (see the module
    docstring): byte-exact on every key for the baseline tools in
    ``BASELINE_TOOL_NAMES``, byte-exact on ``name`` and
    ``inputSchema`` only for the announcement tools, with their
    ``description`` accepted as a non-empty stripped string. Every
    advertised entry must be a JSON object carrying a string
    ``name``; a non-object entry or one without a string name fails
    at the entry's index. The expected values are constructed.

    Args:
        actual: The ``tools`` array from the ``tools/list`` result.

    Returns:
        ``(True, summary, mode)`` when the contract holds, where
        ``mode`` is ``DESCRIPTION_PRESENCE_ONLY`` when at least
        one announcement-tool description was accepted via the
        presence check and ``None`` otherwise. ``(False, reason,
        None)`` when the contract fails, naming the first divergence.
    """
    for index, tool in enumerate(actual):
        if not isinstance(tool, dict):
            return False, f"tools/list entry {index} is not a JSON object", None
        if not isinstance(tool.get("name"), str):
            return False, f"tools/list entry {index} has no string name", None

    expected_tools = expected_tools_list()
    expected_names = {tool["name"] for tool in expected_tools}
    actual_by_name = {tool["name"]: tool for tool in actual}
    missing = expected_names - set(actual_by_name)
    if missing:
        return False, f"tools/list is missing {sorted(missing)}", None
    extra = set(actual_by_name) - expected_names
    if extra:
        return (
            False,
            f"tools/list advertises unexpected tools {sorted(extra)}",
            None,
        )

    presence_only_fired = False
    for expected_tool in expected_tools:
        name = expected_tool["name"]
        got = actual_by_name[name]
        for key in ("name", "inputSchema"):
            if got.get(key) != expected_tool.get(key):
                return False, (f"tools/list {name}.{key} differs from the expected values"), None
        if name in BASELINE_TOOL_NAMES:
            if got.get("description") != expected_tool.get("description"):
                return (
                    False,
                    (f"tools/list {name}.description differs from the expected values"),
                    None,
                )
        else:
            got_desc = got.get("description")
            if not isinstance(got_desc, str) or not got_desc.strip():
                return False, (f"tools/list {name}.description must be a non-empty string"), None
            presence_only_fired = True

    mode = DESCRIPTION_PRESENCE_ONLY if presence_only_fired else None
    return True, "all 6 tool objects match the expected contract", mode


def _try_forms(
    forms: Iterable[tuple[str, Callable[[], bool]]],
) -> str | None:
    """Return the label of the first accepted form, or ``None``.

    Each entry is a ``(label, accepts)`` pair; ``accepts`` is invoked
    in order and the first one returning ``True`` settles the match.
    The per-form acceptance algorithm stays with the caller so each
    matcher decides what counts as a match for each of its forms
    while the dispatch (try in order, label-of-first-match) lives in
    one place.

    Args:
        forms: Ordered ``(label, accepts)`` pairs to evaluate.

    Returns:
        The label of the first form whose predicate returned
        ``True``; ``None`` when none accepted.
    """
    for label, accepts in forms:
        if accepts():
            return label
    return None
