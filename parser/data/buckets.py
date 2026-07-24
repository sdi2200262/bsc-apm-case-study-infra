# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Classify a turn prompt into one of three content buckets.

Every turn-starting user prompt is classified into exactly one of:

* ``protocol``: the prompt invokes a framework slash
  command (an APM ``apm-*`` or a Spec-kit ``speckit-*`` command)
  inside a ``<command-name>`` marker. Local Claude Code commands
  such as ``/clear`` or ``/exit`` are not framework participation
  and do not put a prompt in the protocol bucket.
* ``short``: not a protocol prompt, and the text content is shorter
  than the configured threshold in characters.
* ``standard``: not a protocol prompt, and the text content meets
  or exceeds the configured threshold.

The default threshold is 50 characters; an alternate value can be
supplied via the ``--short-threshold`` flag at parse time.
"""

from __future__ import annotations

from .commands import classify_command, extract_command_names

BUCKET_PROTOCOL = "protocol"
BUCKET_SHORT = "short"
BUCKET_STANDARD = "standard"

BUCKETS: tuple[str, ...] = (BUCKET_PROTOCOL, BUCKET_SHORT, BUCKET_STANDARD)

DEFAULT_SHORT_THRESHOLD = 50


def classify_bucket(text: str, short_threshold: int) -> str:
    """Classify a turn prompt into ``protocol``, ``short``, or ``standard``.

    Args:
        text: The prompt's full text content, formed by concatenating
            the record's text content blocks.
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
    ``speckit-`` puts the input in the protocol bucket, including
    framework commands the parser does not yet have a phase or role
    mapping for. This matches the bucket's intent as a measure of
    framework participation rather than of command-table coverage;
    unknown framework commands are still flagged separately in the
    diagnostics block so the analysis layer can audit which command
    surfaces participants actually used.
    """
    return any(classify_command(name) for name in extract_command_names(text))
