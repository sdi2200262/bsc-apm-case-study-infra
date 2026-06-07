#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
User-input dimension metrics: turn-prompt counts, steer counts, bucket distributions.

Two distinct populations of user input drive this dimension:

* **Turn-starting prompts**: the user-authored messages that open a
  conversational turn. Each becomes a turn in the parser's turn
  derivation.
* **Delivered steers**: messages the user typed during an ongoing
  turn and queued for delivery, which the model then read when it
  reached a release point. Abandoned steers (queued and removed
  before delivery) do not enter this population because the model
  never saw them; they are tallied separately as engagement
  attempts that did not land. A queued local-only built-in command
  is not a steer at all: it issues no model request, so it counts in
  neither the delivered nor the abandoned population.

Bucket distributions are computed over three populations: turn
prompts alone, delivered steers alone, and the union of the two
(every input the model actually saw from the user). The union
distribution is the headline metric because it characterises the
full surface area of user-driven coordination work the model
processed.

Steer count metrics expose the engagement attempt rate independent
of bucket: how many times did the user reach for a mid-turn
intervention regardless of whether the intervention reached the
model? ``steer_attempted_count`` totals delivered and abandoned
events; the delivered-versus-abandoned split shows whether the
participant tends to commit their interventions or back out before
they land.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..buckets import BUCKETS, classify_bucket
from ..loader import STEER_FATE_DELIVERED, SteerEvent
from ..schema import Record, queue_record_content, user_prompt_text
from ..turns import Turn


@dataclass(frozen=True)
class UserInputMetrics:
    """User-input metric block for a single scope.

    Attributes:
        turn_prompt_count: Number of turn-starting user prompts.
        steer_delivered_count: Steers whose queued content reached
            the model.
        steer_abandoned_count: Steers cancelled before delivery.
        steer_attempted_count: ``steer_delivered_count + steer_abandoned_count``.
        turn_prompts_bucket_shares: Map from each bucket constant
            (``protocol``, ``short``, ``standard``) to its share of
            the turn-starting prompt population. Sums to ``1.0``
            unless the population is empty, in which case all
            shares are ``0.0``.
        steer_delivered_bucket_shares: Same map over the delivered
            steer population.
        all_inputs_bucket_shares: Same map over the union of
            turn-starting prompts and delivered steers.
        turn_prompts_magnitude_by_bucket: Map from each bucket to
            the mean character count of inputs in that bucket
            within the turn-starting prompt population. Empty
            buckets report ``0.0``.
        steer_delivered_magnitude_by_bucket: Same map over the
            delivered steer population.
    """

    turn_prompt_count: int
    steer_delivered_count: int
    steer_abandoned_count: int
    steer_attempted_count: int
    turn_prompts_bucket_shares: dict[str, float]
    steer_delivered_bucket_shares: dict[str, float]
    all_inputs_bucket_shares: dict[str, float]
    turn_prompts_magnitude_by_bucket: dict[str, float]
    steer_delivered_magnitude_by_bucket: dict[str, float]


def compute_user_input_metrics(
    turns: Iterable[Turn],
    steer_events: Iterable[SteerEvent],
    short_threshold: int,
) -> UserInputMetrics:
    """Compute user-input metrics over a set of turns and steer events.

    Args:
        turns: Turns whose starting prompts make up the
            turn-prompt population.
        steer_events: Steer events whose enqueues are classified
            into delivered and abandoned populations.
        short_threshold: Bucket classifier threshold in characters.

    Returns:
        A populated ``UserInputMetrics``.
    """
    turn_list = list(turns)
    user_events = [e for e in steer_events if e.is_user_authored]
    delivered_events = [e for e in user_events if e.fate == STEER_FATE_DELIVERED]
    abandoned_events = [e for e in user_events if e.fate != STEER_FATE_DELIVERED]
    turn_prompt_texts = [_text_of_turn_prompt(t.starting_prompt) for t in turn_list]
    delivered_steer_texts = [
        _text_of_steer(event) for event in delivered_events
    ]
    return UserInputMetrics(
        turn_prompt_count=len(turn_list),
        steer_delivered_count=len(delivered_events),
        steer_abandoned_count=len(abandoned_events),
        steer_attempted_count=len(delivered_events) + len(abandoned_events),
        turn_prompts_bucket_shares=_bucket_shares(turn_prompt_texts, short_threshold),
        steer_delivered_bucket_shares=_bucket_shares(delivered_steer_texts, short_threshold),
        all_inputs_bucket_shares=_bucket_shares(
            turn_prompt_texts + delivered_steer_texts, short_threshold
        ),
        turn_prompts_magnitude_by_bucket=_bucket_mean_magnitudes(
            turn_prompt_texts, short_threshold
        ),
        steer_delivered_magnitude_by_bucket=_bucket_mean_magnitudes(
            delivered_steer_texts, short_threshold
        ),
    )


def _text_of_turn_prompt(record: Record) -> str:
    """Return the prompt text used for bucket classification on a turn-starter."""
    return user_prompt_text(record)


def _text_of_steer(event: SteerEvent) -> str:
    """Return the queued content used for bucket classification on a steer."""
    content = queue_record_content(event.enqueue_record)
    return content if content is not None else ""


def _bucket_shares(texts: list[str], short_threshold: int) -> dict[str, float]:
    """Return a bucket -> share map for a population of input texts."""
    shares = {bucket: 0.0 for bucket in BUCKETS}
    if not texts:
        return shares
    counts = {bucket: 0 for bucket in BUCKETS}
    for text in texts:
        counts[classify_bucket(text, short_threshold)] += 1
    total = len(texts)
    for bucket in BUCKETS:
        shares[bucket] = counts[bucket] / total
    return shares


def _bucket_mean_magnitudes(texts: list[str], short_threshold: int) -> dict[str, float]:
    """Return a bucket -> mean character count map for a population of input texts."""
    sums = {bucket: 0 for bucket in BUCKETS}
    counts = {bucket: 0 for bucket in BUCKETS}
    for text in texts:
        bucket = classify_bucket(text, short_threshold)
        sums[bucket] += len(text)
        counts[bucket] += 1
    return {
        bucket: (sums[bucket] / counts[bucket]) if counts[bucket] else 0.0
        for bucket in BUCKETS
    }
