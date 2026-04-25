#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Public entry points for the Claude Code chat parser package.

The package reads Claude Code CLI JSONL conversation files and
produces a scope-nested metric artifact for the thesis case study.
External callers that want to embed the parser in their own tooling
import from this module; the command-line interface in ``__main__``
wraps the same surface.
"""

from __future__ import annotations

from .commands import (
    FRAMEWORK_APM,
    FRAMEWORK_SPECKIT,
    PHASE_IMPLEMENTATION,
    PHASE_OTHER,
    PHASE_PLANNING,
    ROLE_MANAGER,
    ROLE_PLANNER,
    ROLE_UNASSIGNED,
    ROLE_WORKER,
)
from .loader import (
    CompactionEvent,
    Conversation,
    RequestUsageIndex,
    SteerEvent,
    discover_conversation_files,
    load_conversation,
    load_conversations,
)
from .schema import Record, SchemaError
from .session import ConversationView, Session, load_session
from .turns import Turn, derive_turns

__all__ = [
    "CompactionEvent",
    "Conversation",
    "ConversationView",
    "FRAMEWORK_APM",
    "FRAMEWORK_SPECKIT",
    "PHASE_IMPLEMENTATION",
    "PHASE_OTHER",
    "PHASE_PLANNING",
    "ROLE_MANAGER",
    "ROLE_PLANNER",
    "ROLE_UNASSIGNED",
    "ROLE_WORKER",
    "Record",
    "RequestUsageIndex",
    "SchemaError",
    "Session",
    "SteerEvent",
    "Turn",
    "derive_turns",
    "discover_conversation_files",
    "load_conversation",
    "load_conversations",
    "load_session",
]
