# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Public entry points for the Claude Code chat parser package.

The package reads Claude Code CLI JSONL conversation files and produces a
scope-nested metric artifact for the thesis case study. External callers
that want to embed the parser import from this module; the command-line
interface in ``__main__`` wraps the same surface. The re-exports here are
the stable embedding surface: the loaders, the artifact builder, the core
record and session types, the JSON IO helpers, the rate table, and the
archival cipher. The per-dimension data and metric computations are
internal to the ``data`` and ``metrics`` layers and are imported from
there directly.
"""

from __future__ import annotations

from .data.buckets import (
    BUCKET_PROTOCOL,
    BUCKET_SHORT,
    BUCKET_STANDARD,
    BUCKETS,
    DEFAULT_SHORT_THRESHOLD,
    classify_bucket,
)
from .data.commands import (
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
from .data.conversation import (
    CompactionEvent,
    Conversation,
    RequestUsageIndex,
    SteerEvent,
    discover_conversation_files,
    load_conversation,
)
from .data.jsonl import (
    SANITIZATION_META_KEY,
    is_sanitised_payload,
    iter_jsonl_lines,
    read_file_text,
    read_json,
    write_file_text,
    write_json,
)
from .data.schema import Record, SchemaError
from .data.session import ConversationView, Session, load_session
from .data.turns import Turn, derive_turns
from .errors import ParserError
from .rates import (
    CATEGORIES,
    ModelRates,
    RateTable,
    RateTableError,
    cost_in_usd,
    load_rate_table,
    rates_for_model,
)
from .report.build import build_report
from .sanitize import sanitise_jsonl_file, unsanitise_to_text

__all__ = [
    "BUCKETS",
    "BUCKET_PROTOCOL",
    "BUCKET_SHORT",
    "BUCKET_STANDARD",
    "CATEGORIES",
    "DEFAULT_SHORT_THRESHOLD",
    "FRAMEWORK_APM",
    "FRAMEWORK_SPECKIT",
    "PHASE_IMPLEMENTATION",
    "PHASE_OTHER",
    "PHASE_PLANNING",
    "ROLE_MANAGER",
    "ROLE_PLANNER",
    "ROLE_UNASSIGNED",
    "ROLE_WORKER",
    "SANITIZATION_META_KEY",
    "CompactionEvent",
    "Conversation",
    "ConversationView",
    "ModelRates",
    "ParserError",
    "RateTable",
    "RateTableError",
    "Record",
    "RequestUsageIndex",
    "SchemaError",
    "Session",
    "SteerEvent",
    "Turn",
    "build_report",
    "classify_bucket",
    "cost_in_usd",
    "derive_turns",
    "discover_conversation_files",
    "is_sanitised_payload",
    "iter_jsonl_lines",
    "load_conversation",
    "load_rate_table",
    "load_session",
    "rates_for_model",
    "read_file_text",
    "read_json",
    "sanitise_jsonl_file",
    "unsanitise_to_text",
    "write_file_text",
    "write_json",
]
