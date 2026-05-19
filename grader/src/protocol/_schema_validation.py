#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Tools/call argument validation against a participant's advertised inputSchema.

The C ``tools/call`` path validates the caller's arguments against the
``inputSchema`` the participant advertised in ``tools/list`` before
the binary receives the call, mimicking what the MCP SDK does on the
Python side. The result is either ``None`` (the arguments pass) or
a synthesised JSON-RPC response shaped like the SDK's
validation-error response (returned to the caller in place of a real
``tools/call`` round-trip). A malformed advertised schema, which the
grader does not control, causes the gate to no-op (``None``) and the
call passes through; the documented total behaviour for an untrusted
participant schema.
"""

from __future__ import annotations

import jsonschema


def validate_against_schema(args: dict, schema: dict) -> dict | None:
    """Validate ``args`` against ``schema``; return a synthesised error or ``None``.

    Returns ``None`` also when ``schema`` is malformed: the gate
    cannot run and the call passes through unvalidated.

    Args:
        args: Arguments to validate.
        schema: The participant's advertised ``inputSchema``.

    Returns:
        ``None`` on success; a JSON-RPC response dict shaped like
        the SDK's validation-error response otherwise.
    """
    try:
        jsonschema.validate(args, schema)
    except jsonschema.ValidationError as error:
        return {
            "jsonrpc": "2.0",
            "id": 99,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": f"Input validation error: {error.message}",
                    }
                ],
                "isError": True,
            },
        }
    except jsonschema.SchemaError:
        pass
    return None
