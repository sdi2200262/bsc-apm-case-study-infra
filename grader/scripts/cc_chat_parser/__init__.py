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

from .buckets import (
    BUCKET_PROTOCOL,
    BUCKET_SHORT,
    BUCKET_STANDARD,
    BUCKETS,
    DEFAULT_SHORT_THRESHOLD,
    SHORT_THRESHOLD_SWEEP,
    classify_bucket,
)
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
from .io import (
    SANITIZATION_META_KEY,
    is_sanitised_payload,
    iter_jsonl_lines,
    load_json,
    looks_like_jsonl,
    read_file_text,
    write_file_text,
    write_json,
)
from .metrics.economic import (
    EconomicSession,
    TokenSums,
    compute_economic_for_records,
    compute_session_economic,
    resolve_pinned_model,
)
from .metrics.reliability import ReliabilityMetrics, compute_reliability_metrics
from .metrics.supplementary import SupplementaryMetrics, compute_supplementary_metrics
from .metrics.time import TimeMetrics, compute_time_metrics
from .metrics.user_input import UserInputMetrics, compute_user_input_metrics
from .report import build_report
from .sanitize import sanitise_jsonl_file, unsanitise_to_text
from .rates import (
    CATEGORIES,
    ModelRates,
    RateTable,
    RateTableError,
    cost_in_usd,
    load_rate_table,
    rates_for_model,
)
from .schema import Record, SchemaError
from .session import ConversationView, Session, load_session
from .turns import Turn, derive_turns

__all__ = [
    "BUCKETS",
    "BUCKET_PROTOCOL",
    "BUCKET_SHORT",
    "BUCKET_STANDARD",
    "CATEGORIES",
    "CompactionEvent",
    "Conversation",
    "ConversationView",
    "DEFAULT_SHORT_THRESHOLD",
    "EconomicSession",
    "FRAMEWORK_APM",
    "FRAMEWORK_SPECKIT",
    "ModelRates",
    "PHASE_IMPLEMENTATION",
    "PHASE_OTHER",
    "PHASE_PLANNING",
    "ROLE_MANAGER",
    "ROLE_PLANNER",
    "ROLE_UNASSIGNED",
    "ROLE_WORKER",
    "RateTable",
    "RateTableError",
    "Record",
    "ReliabilityMetrics",
    "RequestUsageIndex",
    "SANITIZATION_META_KEY",
    "SHORT_THRESHOLD_SWEEP",
    "SchemaError",
    "Session",
    "SteerEvent",
    "SupplementaryMetrics",
    "TimeMetrics",
    "TokenSums",
    "Turn",
    "UserInputMetrics",
    "build_report",
    "classify_bucket",
    "compute_economic_for_records",
    "compute_reliability_metrics",
    "compute_session_economic",
    "compute_supplementary_metrics",
    "compute_time_metrics",
    "compute_user_input_metrics",
    "cost_in_usd",
    "derive_turns",
    "discover_conversation_files",
    "is_sanitised_payload",
    "iter_jsonl_lines",
    "load_conversation",
    "load_conversations",
    "load_json",
    "load_rate_table",
    "load_session",
    "looks_like_jsonl",
    "read_file_text",
    "resolve_pinned_model",
    "sanitise_jsonl_file",
    "unsanitise_to_text",
    "write_file_text",
    "write_json",
    "rates_for_model",
]
