# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Main-call selection, per-call/dispatch model resolution, and model-purity detection.

Two token populations: main (per-API-call, needs per-``requestId`` dedup) and
delegated (subagent dispatch usage on parent user records). This module owns the
single selection rule and the model-resolution iterators consumed by ``tokens``,
``counts``, ``turn_series``, and ``metrics/cost``.

It also owns ``compute_model_purity``, which detects silent main-model fallbacks.
Placed here because it drives off ``iter_main_request_records`` and
``canonical_model_id`` already resident; ``report/notices`` imports it from here.
``commands`` and ``prompts`` are imported for the ``/model``-command backing check;
neither imports this module, so the import graph stays acyclic.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ...rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    canonical_model_id,
)
from ..commands import extract_command_names
from ..prompts import is_user_authored_prompt
from ..schema import (
    CONTENT_BLOCK_TOOL_RESULT,
    RECORD_TYPE_ASSISTANT,
    RECORD_TYPE_USER,
    SYNTHETIC_MODEL_MARKER,
    Record,
    iter_agent_dispatch_blocks,
    user_prompt_text,
)
from ..session import Session
from ..subagent_models import resolve_unindexed_subagent_model
from ..token_usage import token_sums_dict_from_usage

if TYPE_CHECKING:
    from ..subagent_usage import SubagentDispatchIndex

_MODEL_COMMAND_NAME = "model"


@dataclass(frozen=True)
class ResolvedMainCall:
    """One priced-population main call: canonical model and token bag.

    Attributes:
        canonical_model: Canonicalised ``message.model`` of the call's first record.
        token_bag: Five-category token bag keyed by ``rates.CATEGORY_*`` constants.
    """

    canonical_model: str
    token_bag: dict[str, int]


@dataclass(frozen=True)
class ResolvedDispatch:
    """One Agent dispatch: resolved model, optional bracket, and token bag.

    Attributes:
        point_model: Point-estimate model the dispatch billed at.
        bracket: ``(lower, upper)`` when the resolver could not commit to one model.
        token_bag: Five-category token bag keyed by ``rates.CATEGORY_*`` constants.
        resolved_without_index: ``True`` when the ``agentId`` was not in the index.
    """

    point_model: str
    bracket: tuple[str, str] | None
    token_bag: dict[str, int]
    resolved_without_index: bool


@dataclass(frozen=True)
class MainCallEntry:
    """One main call: identity, timestamp, and token bag, before turn/phase/role attribution.

    Attributes:
        request_id: ``message.requestId``; join key for pairing tokens with cost.
        canonical_model: Canonicalised ``message.model``, or empty string when absent.
        timestamp: Timestamp of the call's first record, or ``None``.
        token_bag: Five-category token bag; all-zero when the first record lacked usage.
    """

    request_id: str
    canonical_model: str
    timestamp: datetime | None
    token_bag: dict[str, int]


@dataclass(frozen=True)
class ModelSwitch:
    """One observed change of a conversation's main model.

    Attributes:
        role_key: Conversation's role key (e.g. ``planner-1``, ``manager-2``).
        from_model: Canonical model of the previous main call.
        to_model: Canonical model of the switching main call.
        timestamp: Switching call's timestamp, or ``None``.
        backed: ``True`` when a user ``/model`` command preceded the switch;
            ``False`` for a silent fallback.
    """

    role_key: str
    from_model: str
    to_model: str
    timestamp: datetime | None
    backed: bool


@dataclass(frozen=True)
class ModelPurityReport:
    """Session-level model-purity reading.

    Attributes:
        assigned_model: Modal canonical main-call model; empty string when no main calls.
        per_model_counts: Deduped main-call count per canonical model across the session.
        total_main_calls: Total deduped main calls across the session.
        off_assignment_calls: Deduped calls whose model differs from ``assigned_model``.
        switches: Every observed main-model switch, in view order then document order.
    """

    assigned_model: str
    per_model_counts: dict[str, int]
    total_main_calls: int
    off_assignment_calls: int
    switches: tuple[ModelSwitch, ...]

    @property
    def off_assignment_fraction(self) -> float:
        """Return the off-assignment fraction, or ``0.0`` when no main calls exist."""
        if self.total_main_calls == 0:
            return 0.0
        return self.off_assignment_calls / self.total_main_calls

    @property
    def silent_switches(self) -> tuple[ModelSwitch, ...]:
        """Return the unbacked (silently fallen-back) switches, in order."""
        return tuple(switch for switch in self.switches if not switch.backed)


def is_main_request_record(record: Record) -> bool:
    """Return ``True`` for a record in the main-call selection population.

    Selects non-synthetic, non-API-error assistant records carrying a string
    ``requestId``. Per-``requestId`` dedup is applied by ``iter_main_request_records``.
    """
    if record.record_type != RECORD_TYPE_ASSISTANT:
        return False
    message = record.payload.get("message")
    if not isinstance(message, dict):
        return False
    if message.get("model") == SYNTHETIC_MODEL_MARKER:
        return False
    if record.payload.get("isApiErrorMessage") is True:
        return False
    return isinstance(record.payload.get("requestId"), str)


def iter_main_request_records(records: Iterable[Record]) -> Iterator[Record]:
    """Yield the first assistant record for each main-call requestId, in document order."""
    seen: set[str] = set()
    for record in records:
        if not is_main_request_record(record):
            continue
        request_id = record.payload["requestId"]
        if request_id in seen:
            continue
        seen.add(request_id)
        yield record


def iter_main_call_entries(records: Iterable[Record]) -> Iterator[MainCallEntry]:
    """Yield one ``MainCallEntry`` per distinct main-call requestId in ``records``.

    Drives off ``iter_main_request_records``; covers the same population as
    ``request_count``. Calls whose first record lacks a usage block emit an all-zero
    token bag.
    """
    for record in iter_main_request_records(records):
        message = record.payload["message"]
        model = message.get("model")
        usage = message.get("usage")
        token_bag = (
            token_sums_dict_from_usage(usage)
            if isinstance(usage, dict)
            else {
                CATEGORY_INPUT: 0,
                CATEGORY_OUTPUT: 0,
                CATEGORY_CACHE_READ: 0,
                CATEGORY_CACHE_5M: 0,
                CATEGORY_CACHE_1H: 0,
            }
        )
        yield MainCallEntry(
            request_id=record.payload["requestId"],
            canonical_model=canonical_model_id(model) if isinstance(model, str) else "",
            timestamp=record.timestamp,
            token_bag=token_bag,
        )


def iter_resolved_main_calls(records: Iterable[Record]) -> Iterator[ResolvedMainCall]:
    """Yield canonical model and token bag for each billed main call.

    Skips calls whose first record lacks a usage block; ``requestId`` is still consumed
    so a later record for the same call does not re-enter the population.
    """
    seen: set[str] = set()
    for record in records:
        if record.record_type != RECORD_TYPE_ASSISTANT:
            continue
        if record.payload.get("isApiErrorMessage") is True:
            continue
        message = record.payload.get("message")
        if not isinstance(message, dict):
            continue
        model = message.get("model")
        if not isinstance(model, str) or model == SYNTHETIC_MODEL_MARKER:
            continue
        request_id = record.payload.get("requestId")
        if not isinstance(request_id, str) or request_id in seen:
            continue
        seen.add(request_id)
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        yield ResolvedMainCall(
            canonical_model=canonical_model_id(model),
            token_bag=token_sums_dict_from_usage(usage),
        )


def iter_resolved_dispatches(
    records: list[Record],
    subagent_index: SubagentDispatchIndex,
) -> Iterator[ResolvedDispatch]:
    """Yield resolved model and token bag for each Agent dispatch.

    When the dispatch's ``agentId`` is indexed, prices the subagent's own
    model and its true token bag (summed from the subagent transcript by
    ``subagent_usage``) in place of the parent ``toolUseResult.usage``
    roll-up, which under-represents the bag (notably ``cache_5m = 0``). The
    indexed bag replaces the roll-up, so a dispatch is never counted twice.
    Falls back to the roll-up bag and the unindexed resolver only when no
    subagent file shipped for the ``agentId``.
    """
    contexts = _build_dispatch_contexts(records)
    for record in records:
        if record.record_type != RECORD_TYPE_USER:
            continue
        tool_use_result = record.payload.get("toolUseResult")
        if not isinstance(tool_use_result, dict):
            continue
        usage = tool_use_result.get("usage")
        if not isinstance(usage, dict):
            continue
        matched_tool_use_id = _matched_dispatch_tool_use_id(record, contexts)
        if matched_tool_use_id is None:
            continue
        agent_id = tool_use_result.get("agentId")
        roll_up_bag = token_sums_dict_from_usage(usage)
        if isinstance(agent_id, str) and agent_id in subagent_index.model_by_agent_id:
            yield ResolvedDispatch(
                point_model=subagent_index.model_by_agent_id[agent_id],
                bracket=None,
                token_bag=subagent_index.usage_by_agent_id.get(agent_id, roll_up_bag),
                resolved_without_index=False,
            )
            continue
        context = contexts[matched_tool_use_id]
        resolved = resolve_unindexed_subagent_model(
            subagent_type=context.subagent_type,
            input_model=context.input_model,
            parent_main_model=context.parent_main_model,
        )
        yield ResolvedDispatch(
            point_model=resolved.canonical_model,
            bracket=resolved.bracket,
            token_bag=roll_up_bag,
            resolved_without_index=True,
        )


@dataclass(frozen=True)
class _MainCall:
    """One deduped main call reduced to the fields the purity detector reads."""

    canonical_model: str
    timestamp: datetime | None


def compute_model_purity(session: Session) -> ModelPurityReport:
    """Compute the session's model-purity report.

    The modal canonical model across all deduped main calls is the assigned model.
    Within each conversation, a model change is backed when a user ``/model`` command
    falls between the previous and switching call; otherwise it is a silent fallback.
    """
    per_model_counts: dict[str, int] = {}
    total_main_calls = 0
    switches: list[ModelSwitch] = []

    for view in session.views:
        records = view.conversation.records
        main_calls = _deduped_main_calls(records)
        for call in main_calls:
            per_model_counts[call.canonical_model] = (
                per_model_counts.get(call.canonical_model, 0) + 1
            )
            total_main_calls += 1
        switches.extend(_detect_switches(view.role, records, main_calls))

    assigned_model = _modal_model(per_model_counts)
    off_assignment_calls = sum(
        count for model, count in per_model_counts.items() if model != assigned_model
    )
    return ModelPurityReport(
        assigned_model=assigned_model,
        per_model_counts=per_model_counts,
        total_main_calls=total_main_calls,
        off_assignment_calls=off_assignment_calls,
        switches=tuple(switches),
    )


def _deduped_main_calls(records: tuple[Record, ...]) -> list[_MainCall]:
    """Return the conversation's deduped main calls in document order."""
    main_calls: list[_MainCall] = []
    for record in iter_main_request_records(records):
        message = record.payload["message"]
        model = message.get("model")
        canonical = canonical_model_id(model) if isinstance(model, str) else ""
        main_calls.append(_MainCall(canonical_model=canonical, timestamp=record.timestamp))
    return main_calls


def _detect_switches(
    role_key: str,
    records: tuple[Record, ...],
    main_calls: list[_MainCall],
) -> list[ModelSwitch]:
    """Detect and classify every main-model switch in one conversation.

    A switch is backed when a user ``/model`` command falls within ``[prev_ts, switch_ts]``.
    """
    if len(main_calls) < 2:
        return []
    command_times = _model_command_timestamps(records)
    switches: list[ModelSwitch] = []
    previous = main_calls[0]
    for call in main_calls[1:]:
        if call.canonical_model != previous.canonical_model:
            backed = _has_command_between(command_times, previous.timestamp, call.timestamp)
            switches.append(
                ModelSwitch(
                    role_key=role_key,
                    from_model=previous.canonical_model,
                    to_model=call.canonical_model,
                    timestamp=call.timestamp,
                    backed=backed,
                )
            )
        previous = call
    return switches


def _model_command_timestamps(records: tuple[Record, ...]) -> list[datetime]:
    """Return sorted timestamps of user-issued ``/model`` commands.

    The command is local-only and surfaces as a ``<command-name>/model</command-name>``
    marker. Records without timestamps are dropped; they cannot position a switch.
    """
    times: list[datetime] = []
    for record in records:
        if not is_user_authored_prompt(record):
            continue
        if record.timestamp is None:
            continue
        if _MODEL_COMMAND_NAME in extract_command_names(user_prompt_text(record)):
            times.append(record.timestamp)
    times.sort()
    return times


def _has_command_between(
    command_times: list[datetime],
    lower: datetime | None,
    upper: datetime | None,
) -> bool:
    """Return ``True`` when a ``/model`` falls in ``[lower, upper]`` (``None`` unbounded)."""
    for command_time in command_times:
        if lower is not None and command_time < lower:
            continue
        if upper is not None and command_time > upper:
            continue
        return True
    return False


def _modal_model(per_model_counts: dict[str, int]) -> str:
    """Return the model with the highest deduped main-call count.

    Ties break on the lexicographically smallest model id for determinism.
    """
    if not per_model_counts:
        return ""
    return min(per_model_counts.items(), key=lambda item: (-item[1], item[0]))[0]


@dataclass(frozen=True)
class _DispatchContext:
    """Context for one Agent dispatch needed by the unindexed-model resolver.

    Attributes:
        subagent_type: ``input.subagent_type`` on the tool_use block, or ``None``.
        input_model: ``input.model`` on the tool_use block, or ``None``.
        parent_main_model: ``message.model`` of the emitting assistant record.
    """

    subagent_type: str | None
    input_model: str | None
    parent_main_model: str


def _build_dispatch_contexts(records: list[Record]) -> dict[str, _DispatchContext]:
    """Build a tool_use_id -> dispatch context map from ``Agent`` tool_use blocks."""
    contexts: dict[str, _DispatchContext] = {}
    for record, block in iter_agent_dispatch_blocks(records):
        parent_model = record.payload["message"].get("model")
        if not isinstance(parent_model, str):
            continue
        tool_use_id = block.get("id")
        if not isinstance(tool_use_id, str):
            continue
        inputs = block.get("input")
        if not isinstance(inputs, dict):
            inputs = {}
        subagent_type = inputs.get("subagent_type")
        if not isinstance(subagent_type, str):
            subagent_type = None
        input_model = inputs.get("model")
        if not isinstance(input_model, str):
            input_model = None
        contexts[tool_use_id] = _DispatchContext(
            subagent_type=subagent_type,
            input_model=input_model,
            parent_main_model=parent_model,
        )
    return contexts


def _matched_dispatch_tool_use_id(
    user_record: Record,
    contexts: dict[str, _DispatchContext],
) -> str | None:
    """Return the ``tool_use_id`` of the Agent dispatch this user record carries, or ``None``."""
    message = user_record.payload.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != CONTENT_BLOCK_TOOL_RESULT:
            continue
        tool_use_id = block.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id in contexts:
            return tool_use_id
    return None
