#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Manifest operations for the data-processing pipeline.

The manifest at ``<output-root>/pipeline_manifest.json`` is the audit
trail for every submission the pipeline has touched. One top-level
entry per submission, keyed by the manifest key
``{PID}_S{1|2}_{framework}``; each entry carries one block per stage
recording the stage's status, timestamp, input and output paths,
checksums, and any stage-specific fields (grading score breakdown,
sanitised file count, dataset row number).

The on-disk shape is JSON for tooling friendliness; the in-memory
shape uses frozen dataclasses so callers iterate typed records
rather than untyped dicts. Serialisation is via ``to_dict`` and
``from_dict`` methods that own the JSON shape; updates produce new
``Manifest`` values rather than mutating in place, matching the
immutability of the underlying records.

File locking and atomic writes: a shared lock is held during reads,
an exclusive lock during writes. The write is atomic on POSIX:
data goes to a sibling temporary file, locked under exclusive
flock, and renamed into place. Concurrent readers see either the
previous or the new content, never a partial write.
"""

from __future__ import annotations

import fcntl
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ManifestError

MANIFEST_FILENAME = "pipeline_manifest.json"

STAGE_VALIDATE = "validate"
STAGE_GRADE = "grade"
STAGE_PARSE = "parse"
STAGE_COMBINE = "combine"
STAGE_ADD_TO_DATASET = "add_to_dataset"

KNOWN_STAGES: tuple[str, ...] = (
    STAGE_VALIDATE,
    STAGE_GRADE,
    STAGE_PARSE,
    STAGE_COMBINE,
    STAGE_ADD_TO_DATASET,
)

STATUS_SUCCESS = "success"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class StageEntry:
    """One stage's record inside a submission entry.

    Attributes:
        stage: The stage name; one of ``KNOWN_STAGES``.
        timestamp: ISO-8601 UTC timestamp set when the stage
            entry was created or last updated.
        status: Status string; one of ``STATUS_SUCCESS``,
            ``STATUS_WARNING``, ``STATUS_ERROR``.
        fields: Stage-specific fields whose key set varies by
            stage. The validate stage records the input zip path
            and checksum; the grade stage records the score and
            breakdown; the parse stage records the framework and
            sanitised file list; and so on.
    """

    stage: str
    timestamp: str
    status: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the stage entry in JSON-serialisable form."""
        result: dict[str, Any] = {
            "timestamp": self.timestamp,
            "status": self.status,
        }
        result.update(self.fields)
        return result

    @classmethod
    def from_dict(cls, stage: str, payload: dict[str, Any]) -> "StageEntry":
        """Parse a stage entry from its JSON form."""
        timestamp = str(payload.get("timestamp", ""))
        status = str(payload.get("status", ""))
        fields = {
            key: value
            for key, value in payload.items()
            if key not in ("timestamp", "status")
        }
        return cls(
            stage=stage,
            timestamp=timestamp,
            status=status,
            fields=fields,
        )


@dataclass(frozen=True)
class SubmissionEntry:
    """All stages recorded for one submission.

    Attributes:
        manifest_key: The manifest key in
            ``{PID}_S{1|2}_{framework}`` form.
        stages: Map from stage name to ``StageEntry`` for every
            stage that has been executed for this submission.
    """

    manifest_key: str
    stages: dict[str, StageEntry] = field(default_factory=dict)

    def get_stage(self, stage: str) -> StageEntry | None:
        """Return the entry for one stage, or ``None`` when not executed."""
        return self.stages.get(stage)

    def has_stage(self, stage: str) -> bool:
        """Return ``True`` when the stage has been executed for this submission."""
        return stage in self.stages

    def to_dict(self) -> dict[str, Any]:
        """Return the submission entry in JSON-serialisable form."""
        return {
            stage_name: entry.to_dict()
            for stage_name, entry in self.stages.items()
        }


@dataclass(frozen=True)
class Manifest:
    """The full pipeline manifest.

    Attributes:
        created_at: ISO-8601 UTC timestamp of manifest creation.
        updated_at: ISO-8601 UTC timestamp of the most recent save.
        path: Absolute path of the manifest file on disk.
        entries: Map from manifest key to ``SubmissionEntry``.
    """

    created_at: str
    updated_at: str
    path: Path
    entries: dict[str, SubmissionEntry] = field(default_factory=dict)

    def get(self, manifest_key: str) -> SubmissionEntry | None:
        """Return the submission entry, or ``None`` when not present."""
        return self.entries.get(manifest_key)

    def to_dict(self) -> dict[str, Any]:
        """Return the manifest in JSON-serialisable form."""
        return {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entries": {
                key: entry.to_dict() for key, entry in self.entries.items()
            },
        }


def manifest_path(output_root: Path) -> Path:
    """Return the manifest path under an output root."""
    return output_root / MANIFEST_FILENAME


def load_manifest(output_root: Path) -> Manifest:
    """Load the manifest from disk, creating an empty manifest when absent.

    Args:
        output_root: The dataset output root directory.

    Returns:
        A populated ``Manifest``. When the file does not exist, an
        empty manifest with newly-set timestamps is returned; the
        caller's first ``save_manifest`` materialises it on disk.

    Raises:
        ManifestError: When the file exists but is malformed JSON
            or has the wrong top-level shape.
    """
    path = manifest_path(output_root)
    if not path.exists():
        return _empty_manifest(path)
    try:
        with path.open("r", encoding="utf-8") as source:
            fcntl.flock(source.fileno(), fcntl.LOCK_SH)
            try:
                payload = json.load(source)
            finally:
                fcntl.flock(source.fileno(), fcntl.LOCK_UN)
    except json.JSONDecodeError as error:
        raise ManifestError(
            f"invalid JSON in manifest at {path}: {error}"
        ) from error
    return _manifest_from_dict(payload, path)


def save_manifest(manifest: Manifest) -> Manifest:
    """Persist a manifest to disk and return the updated value.

    The ``updated_at`` field is set to the current UTC time; a new
    ``Manifest`` value with the updated timestamp is returned (the
    input is not mutated, since dataclasses are frozen). Writes go
    through a sibling temporary file under exclusive lock and then
    rename atomically.

    Args:
        manifest: The manifest to persist.

    Returns:
        A new ``Manifest`` with ``updated_at`` set to the time of
        write.

    Raises:
        ManifestError: When the parent directory does not exist or
            the manifest file cannot be written.
    """
    path = manifest.path
    parent = path.parent
    if not parent.exists():
        raise ManifestError(
            f"cannot save manifest; parent directory missing: {parent}"
        )
    updated = replace(manifest, updated_at=_now())
    payload = updated.to_dict()
    temp_path = parent / f".{path.name}.tmp"
    with temp_path.open("w", encoding="utf-8") as sink:
        fcntl.flock(sink.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(payload, sink, indent=2, ensure_ascii=False)
            sink.flush()
        finally:
            fcntl.flock(sink.fileno(), fcntl.LOCK_UN)
    temp_path.rename(path)
    return updated


def add_stage(
    manifest: Manifest,
    manifest_key: str,
    stage: str,
    status: str,
    **fields: Any,
) -> Manifest:
    """Return a new manifest with one stage entry added or replaced.

    Args:
        manifest: The existing manifest.
        manifest_key: Submission manifest key.
        stage: Stage name; must be one of ``KNOWN_STAGES``.
        status: Status string; ``STATUS_SUCCESS``,
            ``STATUS_WARNING``, or ``STATUS_ERROR``.
        **fields: Stage-specific fields (input file paths,
            checksums, scores, dataset row number, etc.).

    Returns:
        A new ``Manifest`` value with the entry installed. The
        input is not mutated.

    Raises:
        ManifestError: When ``stage`` is not a known stage name.
    """
    if stage not in KNOWN_STAGES:
        raise ManifestError(f"unknown stage name: {stage!r}")
    entry = StageEntry(
        stage=stage,
        timestamp=_now(),
        status=status,
        fields=dict(fields),
    )
    new_entries = dict(manifest.entries)
    submission = new_entries.get(
        manifest_key,
        SubmissionEntry(manifest_key=manifest_key),
    )
    new_stages = dict(submission.stages)
    new_stages[stage] = entry
    new_entries[manifest_key] = SubmissionEntry(
        manifest_key=manifest_key,
        stages=new_stages,
    )
    return replace(manifest, entries=new_entries)


def _empty_manifest(path: Path) -> Manifest:
    """Return a new empty manifest with timestamps set to the current UTC time."""
    now = _now()
    return Manifest(
        created_at=now,
        updated_at=now,
        path=path.resolve(),
        entries={},
    )


def _manifest_from_dict(payload: Any, path: Path) -> Manifest:
    """Convert a parsed JSON payload to a ``Manifest``."""
    if not isinstance(payload, dict):
        raise ManifestError(
            f"manifest at {path} must be a JSON object at the top level"
        )
    created_at = str(payload.get("created_at", ""))
    updated_at = str(payload.get("updated_at", ""))
    entries_raw = payload.get("entries", {})
    if not isinstance(entries_raw, dict):
        raise ManifestError(
            f"manifest at {path}: 'entries' must be a mapping"
        )
    entries: dict[str, SubmissionEntry] = {}
    for key, submission_payload in entries_raw.items():
        if not isinstance(submission_payload, dict):
            raise ManifestError(
                f"manifest at {path}: entry {key!r} must be a mapping"
            )
        stages: dict[str, StageEntry] = {}
        for stage_name, stage_payload in submission_payload.items():
            if not isinstance(stage_payload, dict):
                raise ManifestError(
                    f"manifest at {path}: entry {key!r}, stage {stage_name!r} must be a mapping"
                )
            stages[stage_name] = StageEntry.from_dict(stage_name, stage_payload)
        entries[str(key)] = SubmissionEntry(
            manifest_key=str(key),
            stages=stages,
        )
    return Manifest(
        created_at=created_at,
        updated_at=updated_at,
        path=path.resolve(),
        entries=entries,
    )


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
