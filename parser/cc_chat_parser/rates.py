#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Per-model token rate table for API-equivalent cost computation.

Claude Code participants in the case study are expected to use a
subscription plan, but the cost figure reported by the parser is the
API-equivalent dollar amount their session would have cost at the
public Anthropic API rates current on the snapshot date. The
conversion makes APM and Spec-kit sessions comparable on the same
monetary scale regardless of each participant's billing arrangement.

The Anthropic API exposes five mutually-exclusive token categories per
call: non-cached input tokens, output tokens, cache-read tokens (input
tokens served from a previously-written cache prefix), cache 5-minute
write tokens, and cache 1-hour write tokens. Each category is billed
at its own rate.

Rates are loaded at module import time from a YAML file whose default
location is ``rates.yaml`` next to this module. The file carries the
snapshot date, the source URLs the rates were sourced from, and the
five-category rates per model. Editing the YAML is the standard way to
refresh rates; the change is one commit and the snapshot date moves
with the values so their provenance stays attached.

An alternate rate file may be supplied via the environment variable
``CC_PARSER_RATE_TABLE`` (absolute path to a YAML file with the same
top-level shape). Useful for re-running an older study against
historical rates without modifying the canonical file, or for ad-hoc
what-if comparisons.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RATE_TABLE_FILENAME = "rates.yaml"
RATE_TABLE_ENV_VAR = "CC_PARSER_RATE_TABLE"

CATEGORY_INPUT = "input"
CATEGORY_OUTPUT = "output"
CATEGORY_CACHE_READ = "cache_read"
CATEGORY_CACHE_5M = "cache_5m"
CATEGORY_CACHE_1H = "cache_1h"

CATEGORIES: tuple[str, ...] = (
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    CATEGORY_CACHE_READ,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_1H,
)

_TOKENS_PER_MILLION = 1_000_000.0


class RateTableError(Exception):
    """Raised when the rate-table YAML file is missing fields or malformed."""


@dataclass(frozen=True)
class ModelRates:
    """Per-million-token rates for a single Claude model.

    Attributes:
        input: Non-cached input tokens, USD per million.
        output: Output tokens, USD per million.
        cache_read: Cache-read input tokens, USD per million
            (Anthropic-documented 0.1x of the input rate).
        cache_5m: Tokens written to the 5-minute ephemeral cache,
            USD per million (Anthropic-documented 1.25x of input).
        cache_1h: Tokens written to the 1-hour ephemeral cache,
            USD per million (Anthropic-documented 2.0x of input).
    """

    input: float
    output: float
    cache_read: float
    cache_5m: float
    cache_1h: float


@dataclass(frozen=True)
class RateTable:
    """The parsed contents of a rate-table YAML file.

    Attributes:
        snapshot_date: Date the rates were sourced, as written in
            the YAML file. Free-form string (typically ISO date) so
            the YAML stays human-friendly.
        sources: URLs that document where the rates came from.
        models: Map from Claude model identifier (the value of
            ``message.model`` on assistant records) to that model's
            five-category rates.
        source_path: Absolute path of the YAML file the table was
            loaded from. Surfaced in diagnostics so a reader can
            see whether the canonical file or an override was used.
    """

    snapshot_date: str
    sources: tuple[str, ...]
    models: dict[str, ModelRates]
    source_path: str


def load_rate_table() -> RateTable:
    """Load the rate table from disk.

    Reads the file pointed to by the ``CC_PARSER_RATE_TABLE``
    environment variable when set, otherwise the package-bundled
    ``rates.yaml`` next to this module.

    Returns:
        A populated ``RateTable``.

    Raises:
        RateTableError: When the file is missing, unreadable, or
            does not match the expected top-level shape.
    """
    path = _resolve_rate_table_path()
    try:
        with path.open("r", encoding="utf-8") as source:
            payload = yaml.safe_load(source)
    except OSError as error:
        raise RateTableError(f"cannot read rate table at {path}: {error}") from error
    except yaml.YAMLError as error:
        raise RateTableError(f"invalid YAML in rate table at {path}: {error}") from error
    return _table_from_payload(payload, str(path))


def rates_for_model(table: RateTable, model: str) -> ModelRates:
    """Return the rate-table entry for a model, raising on an unpinned model.

    Args:
        table: A loaded ``RateTable``.
        model: A Claude model identifier (the value of
            ``message.model`` on assistant records).

    Returns:
        The matching ``ModelRates``.

    Raises:
        RateTableError: When the model is not present in the table.
            The caller is responsible for either adding the model to
            the YAML or surfacing the unpinned model as an
            actionable error to the user.
    """
    if model not in table.models:
        raise RateTableError(
            f"model {model!r} is not in the rate table at {table.source_path}; "
            f"add an entry to the file or override with the {RATE_TABLE_ENV_VAR} "
            "environment variable"
        )
    return table.models[model]


def cost_in_usd(
    table: RateTable,
    model: str,
    tokens_by_category: dict[str, int],
) -> float:
    """Return the API-equivalent cost in USD for one bag of tokens at the model's rates.

    Args:
        table: A loaded ``RateTable``.
        model: A Claude model identifier present in ``table.models``.
        tokens_by_category: A map from each category in
            ``CATEGORIES`` to a non-negative token count. Missing
            categories are treated as zero.

    Returns:
        The total cost in USD as a float.

    Raises:
        RateTableError: When the model is not pinned in the table.
    """
    rates = rates_for_model(table, model)
    return (
        tokens_by_category.get(CATEGORY_INPUT, 0) * rates.input
        + tokens_by_category.get(CATEGORY_OUTPUT, 0) * rates.output
        + tokens_by_category.get(CATEGORY_CACHE_READ, 0) * rates.cache_read
        + tokens_by_category.get(CATEGORY_CACHE_5M, 0) * rates.cache_5m
        + tokens_by_category.get(CATEGORY_CACHE_1H, 0) * rates.cache_1h
    ) / _TOKENS_PER_MILLION


def _resolve_rate_table_path() -> Path:
    """Return the path to the rate table, honouring the env-var override."""
    override = os.environ.get(RATE_TABLE_ENV_VAR)
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent / DEFAULT_RATE_TABLE_FILENAME


def _table_from_payload(payload: Any, source_path: str) -> RateTable:
    """Validate and convert a parsed YAML payload into a ``RateTable``."""
    if not isinstance(payload, dict):
        raise RateTableError(
            f"rate table at {source_path} must be a YAML mapping at the top level"
        )
    snapshot_date_raw = payload.get("snapshot_date")
    if snapshot_date_raw is None:
        raise RateTableError(f"rate table at {source_path} is missing 'snapshot_date'")
    snapshot_date = str(snapshot_date_raw)
    sources_raw = payload.get("sources")
    if not isinstance(sources_raw, list):
        raise RateTableError(f"rate table at {source_path} must include a 'sources' list")
    sources = tuple(str(item) for item in sources_raw)
    models_raw = payload.get("models")
    if not isinstance(models_raw, dict):
        raise RateTableError(
            f"rate table at {source_path} must include a 'models' mapping"
        )
    if not models_raw:
        raise RateTableError(f"rate table at {source_path} contains no models")
    models: dict[str, ModelRates] = {}
    for model, fields in models_raw.items():
        if not isinstance(fields, dict):
            raise RateTableError(
                f"rate table at {source_path}: model {model!r} entry is not a mapping"
            )
        try:
            models[str(model)] = ModelRates(
                input=_require_rate(fields, CATEGORY_INPUT, model, source_path),
                output=_require_rate(fields, CATEGORY_OUTPUT, model, source_path),
                cache_read=_require_rate(fields, CATEGORY_CACHE_READ, model, source_path),
                cache_5m=_require_rate(fields, CATEGORY_CACHE_5M, model, source_path),
                cache_1h=_require_rate(fields, CATEGORY_CACHE_1H, model, source_path),
            )
        except RateTableError:
            raise
    return RateTable(
        snapshot_date=snapshot_date,
        sources=sources,
        models=models,
        source_path=source_path,
    )


def _require_rate(
    fields: dict[str, Any],
    key: str,
    model: Any,
    source_path: str,
) -> float:
    """Return a required per-million-token rate from a model's YAML mapping."""
    value = fields.get(key)
    if not isinstance(value, (int, float)):
        raise RateTableError(
            f"rate table at {source_path}: model {model!r} is missing or "
            f"non-numeric '{key}' rate"
        )
    return float(value)
