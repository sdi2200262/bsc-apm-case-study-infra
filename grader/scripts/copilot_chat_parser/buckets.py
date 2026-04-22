#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Input-bucket classifier for user messages.

Every user message is classified into one of three buckets:

* ``protocol``: the message invokes a framework slash command (APM or
  Spec-kit) in ``message.parts[]``.
* ``short``: not a protocol message, and the text content is shorter
  than the configured threshold.
* ``standard``: not a protocol message, and the text content meets or
  exceeds the configured threshold.

The threshold is provided by the caller and is the same integer used in
``--short-threshold``.
"""

from __future__ import annotations

from .commands import command_framework
from .schema import FRAMEWORK_UNKNOWN, SlashCommand

BUCKET_PROTOCOL = "protocol"
BUCKET_SHORT = "short"
BUCKET_STANDARD = "standard"

DEFAULT_SHORT_THRESHOLD = 50
SHORT_THRESHOLD_SWEEP: tuple[int, ...] = (30, 50, 70, 100)


def classify_bucket(
    message_text: str,
    slash_commands: tuple[SlashCommand, ...],
    short_threshold: int,
) -> str:
    """Classify a user message into ``protocol``, ``short``, or ``standard``.

    Args:
        message_text: The concatenated text of every ``text`` part in the
            message.
        slash_commands: Slash-command invocations parsed from the message.
        short_threshold: Upper bound (exclusive) on text length for the
            ``short`` bucket, in characters.

    Returns:
        ``BUCKET_PROTOCOL`` when any slash command is an APM or Spec-kit
        command, ``BUCKET_SHORT`` when the message has no protocol command
        and its text length is under ``short_threshold``, otherwise
        ``BUCKET_STANDARD``.
    """
    if any(command_framework(command) != FRAMEWORK_UNKNOWN for command in slash_commands):
        return BUCKET_PROTOCOL
    if len(message_text) < short_threshold:
        return BUCKET_SHORT
    return BUCKET_STANDARD
