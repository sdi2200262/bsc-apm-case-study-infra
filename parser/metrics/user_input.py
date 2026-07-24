# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Turn-prompt bucket shares and per-bucket magnitudes.

The data layer attaches each turn-starting prompt's bucket label and
character length as a series. This module folds that series into the
prompt-composition metrics. Steering is represented separately by its
delivered and abandoned counts.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.aggregate.counts import BucketedPrompt, UserInputCounts
from ..data.buckets import BUCKETS


@dataclass(frozen=True)
class TurnPromptBuckets:
    """Turn-prompt bucket metrics for a single scope.

    Attributes:
        turn_prompts_bucket_shares: Map from each bucket constant
            (``protocol``, ``short``, ``standard``) to its share of the
            turn-starting prompt population. Sums to ``1.0`` unless the
            population is empty, in which case all shares are ``0.0``.
        turn_prompts_magnitude_by_bucket: Map from each bucket to the mean
            character count of prompts in that bucket within the
            turn-starting prompt population. Empty buckets report ``0.0``.
    """

    turn_prompts_bucket_shares: dict[str, float]
    turn_prompts_magnitude_by_bucket: dict[str, float]


def compute_turn_prompt_buckets(counts: UserInputCounts) -> TurnPromptBuckets:
    """Fold the turn-prompt bucket series into shares and magnitudes.

    Args:
        counts: The scope's user-input counts, carrying the turn-prompt
            ``BucketedPrompt`` series.

    Returns:
        A populated ``TurnPromptBuckets``.
    """
    turn_prompt_inputs = counts.turn_prompt_inputs
    return TurnPromptBuckets(
        turn_prompts_bucket_shares=_bucket_shares(turn_prompt_inputs),
        turn_prompts_magnitude_by_bucket=_bucket_mean_magnitudes(turn_prompt_inputs),
    )


def _bucket_shares(inputs: tuple[BucketedPrompt, ...]) -> dict[str, float]:
    """Return a bucket-to-share map for a population of bucketed prompts."""
    shares = {bucket: 0.0 for bucket in BUCKETS}
    if not inputs:
        return shares
    counts = {bucket: 0 for bucket in BUCKETS}
    for item in inputs:
        counts[item.bucket] += 1
    total = len(inputs)
    for bucket in BUCKETS:
        shares[bucket] = counts[bucket] / total
    return shares


def _bucket_mean_magnitudes(inputs: tuple[BucketedPrompt, ...]) -> dict[str, float]:
    """Return mean prompt length for each bucket."""
    sums = {bucket: 0 for bucket in BUCKETS}
    counts = {bucket: 0 for bucket in BUCKETS}
    for item in inputs:
        sums[item.bucket] += item.length
        counts[item.bucket] += 1
    return {
        bucket: (sums[bucket] / counts[bucket]) if counts[bucket] else 0.0 for bucket in BUCKETS
    }
