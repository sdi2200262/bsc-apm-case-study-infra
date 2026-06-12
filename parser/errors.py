# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Common exception base for the Claude Code chat parser package.

Every parser failure raised deliberately by the package is a
subclass of ``ParserError``; a caller that wants to catch any
parser failure regardless of its origin catches the base type.
The concrete subclasses live in the module whose work they
describe rather than here: ``schema.SchemaError`` covers a JSONL
line that does not match the expected record shape;
``rates.RateTableError`` covers a missing or malformed rate-table
YAML file; ``notes.NotesError`` covers a recoverable failure in a
notes-sidecar operation.
"""

from __future__ import annotations


class ParserError(Exception):
    """Base for every error raised inside the chat parser package.

    Concrete failures are raised as one of the subclasses defined in
    the package's other modules; this type exists so a caller can
    catch any parser-originated failure without enumerating them.
    """
