# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""User-input dimension metrics: bucket-share distributions and per-bucket magnitudes.

Two populations of user input drive this dimension: the turn-starting
prompts that open a conversational turn, and the delivered steers the user
queued mid-turn that reached the model. The four counts of those
populations are data and live in ``data/aggregate/counts``, which also
attaches each input's bucket label and character length as a series.

This module folds those series into the dimension's metrics: the share of
each input-size bucket across three populations (turn prompts alone,
delivered steers alone, and their union), and the mean character magnitude
per bucket within the turn-prompt and delivered-steer populations. The
union distribution is the headline metric because it characterises the
full surface area of user-driven coordination work the model processed.
Folding the pre-bucketed series here keeps the metric layer from reading
the conversation records.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.aggregate.counts import BucketedInput, UserInputCounts
from ..data.buckets import BUCKETS


@dataclass(frozen=True)
class UserInputShares:
    """Bucket-distribution metric block for a single scope.

    Attributes:
        turn_prompts_bucket_shares: Map from each bucket constant
            (``protocol``, ``short``, ``standard``) to its share of the
            turn-starting prompt population. Sums to ``1.0`` unless the
            population is empty, in which case all shares are ``0.0``.
        steer_delivered_bucket_shares: Same map over the delivered steer
            population.
        all_inputs_bucket_shares: Same map over the union of turn-starting
            prompts and delivered steers.
        turn_prompts_magnitude_by_bucket: Map from each bucket to the mean
            character count of inputs in that bucket within the
            turn-starting prompt population. Empty buckets report ``0.0``.
        steer_delivered_magnitude_by_bucket: Same map over the delivered
            steer population.
    """

    turn_prompts_bucket_shares: dict[str, float]
    steer_delivered_bucket_shares: dict[str, float]
    all_inputs_bucket_shares: dict[str, float]
    turn_prompts_magnitude_by_bucket: dict[str, float]
    steer_delivered_magnitude_by_bucket: dict[str, float]


def compute_user_input_shares(counts: UserInputCounts) -> UserInputShares:
    """Fold the per-input bucket-and-length series into shares and magnitudes.

    Args:
        counts: The scope's user-input counts, carrying the turn-prompt
            and delivered-steer ``BucketedInput`` series.

    Returns:
        A populated ``UserInputShares``.
    """
    turn_prompt_inputs = counts.turn_prompt_inputs
    delivered_steer_inputs = counts.delivered_steer_inputs
    return UserInputShares(
        turn_prompts_bucket_shares=_bucket_shares(turn_prompt_inputs),
        steer_delivered_bucket_shares=_bucket_shares(delivered_steer_inputs),
        all_inputs_bucket_shares=_bucket_shares(turn_prompt_inputs + delivered_steer_inputs),
        turn_prompts_magnitude_by_bucket=_bucket_mean_magnitudes(turn_prompt_inputs),
        steer_delivered_magnitude_by_bucket=_bucket_mean_magnitudes(delivered_steer_inputs),
    )


def _bucket_shares(inputs: tuple[BucketedInput, ...]) -> dict[str, float]:
    """Return a bucket -> share map for a population of bucketed inputs."""
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


def _bucket_mean_magnitudes(inputs: tuple[BucketedInput, ...]) -> dict[str, float]:
    """Return a bucket -> mean character count map for a population of bucketed inputs."""
    sums = {bucket: 0 for bucket in BUCKETS}
    counts = {bucket: 0 for bucket in BUCKETS}
    for item in inputs:
        sums[item.bucket] += item.length
        counts[item.bucket] += 1
    return {
        bucket: (sums[bucket] / counts[bucket]) if counts[bucket] else 0.0 for bucket in BUCKETS
    }
