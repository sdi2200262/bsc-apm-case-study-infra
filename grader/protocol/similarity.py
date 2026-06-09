# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Character edit-distance similarity for partial credit.

When the acceptance matcher rejects a string-matched row, this measures
how near the response came to its expected output, as a length-normalized
Levenshtein ratio in ``[0, 1]``. The scoring layer turns a ratio at or
above the configured floor into a fractional ``partial`` award; this
module owns only the measure, not the floor or the verdict.

The ratio is taken on the whitespace-normalized forms (the same
``matching.normalize_response`` the matcher uses), so a row rejected only
for insignificant whitespace is not penalized for it again. A row with
more than one accepted form is scored against its closest form (the
maximum ratio over them). Levenshtein distance
(https://en.wikipedia.org/wiki/Levenshtein_distance) is used over
Hamming because the misses involve length changes, not only
equal-length substitutions.
"""

from __future__ import annotations

from collections.abc import Sequence

from .matching import normalize_response


def levenshtein(a: str, b: str) -> int:
    """Return the Levenshtein edit distance between two strings.

    Counts the minimum single-character insertions, deletions, and
    substitutions to turn ``a`` into ``b``. Uses the iterative
    two-row dynamic-programming form, so memory is linear in the
    shorter string rather than quadratic.

    Args:
        a: The first string.
        b: The second string.

    Returns:
        The edit distance, a non-negative integer.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # Keep the inner row the shorter of the two, so the row width is
    # min(len(a), len(b)) and the loop runs over the longer one.
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            substitute = previous[j - 1] + (char_a != char_b)
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]


def similarity_ratio(actual: str, expected_forms: Sequence[str]) -> float:
    """Return the closest-form edit-distance similarity ratio in ``[0, 1]``.

    For each accepted expected form, both sides are whitespace-normalized
    and the ratio ``1 - distance / max(len(actual), len(expected))`` is
    taken; the maximum over the forms is returned (the closest accepted
    form). Two empty strings score ``1.0`` by convention; an empty against
    a non-empty scores ``0.0``. An empty ``expected_forms`` scores ``0.0``
    (nothing to be near to).

    Args:
        actual: The participant's response text.
        expected_forms: The accepted expected strings for the row; the
            ratio is taken against the closest one.

    Returns:
        The similarity ratio in ``[0, 1]``.
    """
    normalized_actual = normalize_response(actual)
    best = 0.0
    for form in expected_forms:
        normalized_form = normalize_response(form)
        span = max(len(normalized_actual), len(normalized_form))
        distance = levenshtein(normalized_actual, normalized_form)
        ratio = 1.0 if span == 0 else 1.0 - distance / span
        best = max(best, ratio)
    return best
