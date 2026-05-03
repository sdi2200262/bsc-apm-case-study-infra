#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Classify a user input into one of three behavioural buckets.

Every turn-starting user prompt and every delivered steer is
classified into exactly one of:

* ``protocol``: the input invokes a recognised framework slash
  command (an APM ``apm-*`` or a Spec-kit ``speckit.*`` command)
  inside a ``<command-name>`` marker. Local Claude Code commands
  such as ``/clear`` or ``/exit`` are not framework participation
  and do not put an input in the protocol bucket.
* ``short``: not a protocol input, and the text content is shorter
  than the configured threshold in characters.
* ``standard``: not a protocol input, and the text content meets
  or exceeds the configured threshold.

The threshold is a tunable knob the analysis pipeline can sweep
over to test sensitivity. The default value of 50 characters is
intended as a starting point; an alternate value can be supplied
via the ``--short-threshold`` flag at parse time, and a sensitivity
sweep across candidate thresholds accompanies the primary
analysis.
"""

from __future__ import annotations

from .commands import classify_command, extract_command_names

BUCKET_PROTOCOL = "protocol"
BUCKET_SHORT = "short"
BUCKET_STANDARD = "standard"

BUCKETS: tuple[str, ...] = (BUCKET_PROTOCOL, BUCKET_SHORT, BUCKET_STANDARD)

DEFAULT_SHORT_THRESHOLD = 50
SHORT_THRESHOLD_SWEEP: tuple[int, ...] = (30, 50, 70, 100)


def classify_bucket(text: str, short_threshold: int) -> str:
    """Classify a user input into ``protocol``, ``short``, or ``standard``.

    Args:
        text: The input's full text content. For a turn-starting
            user prompt, this is the concatenated text of the
            record's text content blocks. For a delivered steer,
            this is the queue enqueue's content field.
        short_threshold: Upper bound (exclusive) on text length for
            the ``short`` bucket, in characters.

    Returns:
        ``BUCKET_PROTOCOL`` when the text contains any APM or
        Spec-kit framework command marker (recognised or not),
        ``BUCKET_SHORT`` when it has no such marker and is shorter
        than ``short_threshold`` in characters, and
        ``BUCKET_STANDARD`` otherwise.
    """
    if has_framework_command(text):
        return BUCKET_PROTOCOL
    if len(text) < short_threshold:
        return BUCKET_SHORT
    return BUCKET_STANDARD


def has_framework_command(text: str) -> bool:
    """Return ``True`` when ``text`` contains any APM or Spec-kit command marker.

    Membership in the parser's known-command tables is not
    required: any marker whose name begins with ``apm-`` or
    ``speckit.`` puts the input in the protocol bucket, including
    framework commands the parser does not yet have a phase or role
    mapping for. This matches the bucket's intent as a measure of
    framework participation rather than of command-table coverage;
    unknown framework commands are still flagged separately in the
    diagnostics block so the analysis layer can audit which command
    surfaces participants actually used.
    """
    for name in extract_command_names(text):
        if classify_command(name):
            return True
    return False
