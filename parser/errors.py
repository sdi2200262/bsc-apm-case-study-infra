# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Common exception base for the Claude Code chat parser package.

Owns ``ParserError``, the base type whose catch-at-base contract is
documented on the class. The concrete subclasses live in the module whose
work they describe rather than here: ``schema.SchemaError`` (a JSONL line
that does not match the expected record shape), ``rates.RateTableError`` (a
missing or malformed rate-table YAML file), and ``notes.NotesError`` (a
recoverable failure in a notes-sidecar operation).
"""

from __future__ import annotations


class ParserError(Exception):
    """Base for every error raised inside the chat parser package.

    Concrete failures are raised as one of the subclasses defined in
    the package's other modules; this type exists so a caller can
    catch any parser-originated failure without enumerating them.
    """
