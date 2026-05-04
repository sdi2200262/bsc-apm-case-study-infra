#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Participant submission filename parsing and manifest-key derivation.

The pipeline accepts submissions whose filenames match the pattern
``{PID}_S{1|2}_{apm|speckit}`` with an optional ``.zip`` suffix.
Three segments separated by underscores: a participant identifier of
the form ``P\\d{3}``, a session token of the form ``S1`` or ``S2``,
and a framework token of either ``apm`` or ``speckit`` (no hyphen;
matches the parser's ``--framework`` flag vocabulary).

The manifest key is the same three-segment string without the
``.zip`` suffix. The entry in ``pipeline_manifest.json`` for a
submission is keyed by this string, and the per-submission
directory under ``_staging/`` and ``<PID>/<S{n}>_<framework>/``
both use the manifest key as their name.

The third segment also drives the framework flag the pipeline passes
to the parser when it subprocesses ``cc_chat_parser`` for the parse
stage. Auto-detection from transcript content is intentionally not
performed: the framework comes from the submission filename, and a
typo or mismatch produces a clean error instead of silent
mis-classification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import SubmissionFormatError

FRAMEWORK_APM = "apm"
FRAMEWORK_SPECKIT = "speckit"

KNOWN_FRAMEWORKS: frozenset[str] = frozenset({FRAMEWORK_APM, FRAMEWORK_SPECKIT})

SESSION_FIRST = "S1"
SESSION_SECOND = "S2"

KNOWN_SESSIONS: frozenset[str] = frozenset({SESSION_FIRST, SESSION_SECOND})

_SUBMISSION_PATTERN = re.compile(
    r"^(?P<pid>P\d{3})_(?P<session>S[12])_(?P<framework>apm|speckit)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SubmissionName:
    """Parsed components of a submission filename.

    Attributes:
        pid: Participant identifier in ``P\\d{3}`` form, uppercase.
        session: Session token, ``S1`` or ``S2``, uppercase.
        framework: Framework token, ``apm`` or ``speckit``,
            lowercase.
        manifest_key: Concatenation ``{pid}_{session}_{framework}``
            used as the manifest entry key and as the submission
            directory name under both ``_staging/`` and the
            per-participant tree under the dataset output root.
    """

    pid: str
    session: str
    framework: str
    manifest_key: str


def parse_submission_name(name: str) -> SubmissionName:
    """Parse a submission filename into typed components.

    Args:
        name: The submission filename, with or without the ``.zip``
            suffix. Either a bare directory name or a zip filename
            is accepted.

    Returns:
        A populated ``SubmissionName``.

    Raises:
        SubmissionFormatError: When the name does not match the
            ``{PID}_S{1|2}_{apm|speckit}`` pattern.
    """
    stem = _strip_zip_suffix(name)
    match = _SUBMISSION_PATTERN.match(stem)
    if match is None:
        raise SubmissionFormatError(
            f"submission name does not match {{PID}}_S{{1|2}}_{{apm|speckit}}: {name!r}"
        )
    pid = match.group("pid").upper()
    session = match.group("session").upper()
    framework = match.group("framework").lower()
    manifest_key = f"{pid}_{session}_{framework}"
    return SubmissionName(
        pid=pid,
        session=session,
        framework=framework,
        manifest_key=manifest_key,
    )


def is_valid_submission_name(name: str) -> bool:
    """Return ``True`` when a name parses as a submission, ``False`` otherwise.

    Used by callers that want a non-throwing check, for example the
    validate stage's diagnostic listing of zip files in a directory.
    """
    try:
        parse_submission_name(name)
    except SubmissionFormatError:
        return False
    return True


def participant_subdir(submission: SubmissionName) -> str:
    """Return the relative path component for a submission's per-participant directory.

    Submissions are promoted from ``_staging/<manifest_key>/`` to
    ``<PID>/<session>_<framework>/`` so the dataset tree groups
    every session for a given participant under one parent.
    """
    return f"{submission.pid}/{submission.session}_{submission.framework}"


def _strip_zip_suffix(name: str) -> str:
    """Return ``name`` with a trailing ``.zip`` suffix removed (case-insensitive)."""
    if name.lower().endswith(".zip"):
        return name[: -len(".zip")]
    return name
