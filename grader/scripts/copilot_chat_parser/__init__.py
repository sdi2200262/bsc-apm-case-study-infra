#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Copilot Chat Parser package.

Public entry points for callers that want to embed the parser in their
own tooling. The command-line interface in ``__main__`` wraps these
functions.
"""

from __future__ import annotations

from .buckets import DEFAULT_SHORT_THRESHOLD, SHORT_THRESHOLD_SWEEP
from .io import is_sanitized, load_chat, save_csv_report, save_json_report
from .report import build_report
from .sanitize import sanitize_chat, unsanitize_chat
from .schema import SchemaError
from .session import AnnotatedRequest, ConversationSummary, Session, load_session

__all__ = [
    "AnnotatedRequest",
    "ConversationSummary",
    "DEFAULT_SHORT_THRESHOLD",
    "SHORT_THRESHOLD_SWEEP",
    "SchemaError",
    "Session",
    "build_report",
    "is_sanitized",
    "load_chat",
    "load_session",
    "sanitize_chat",
    "save_csv_report",
    "save_json_report",
    "unsanitize_chat",
]
