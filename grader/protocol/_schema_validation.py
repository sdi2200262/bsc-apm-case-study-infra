#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Tools/call argument validation against a participant's advertised ``inputSchema``.

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

This gate applies to the C replica only and mirrors what an
SDK-compliant client experiences against the Python reference. A
participant whose advertised schema is stricter than the PRD (a
``days_back`` schema with ``minimum: 0``, for instance) has stopped
being a drop-in replacement for the Python reference: the negative-
``days_back`` rows hit this gate before the participant's tool body
runs, the caller receives the synthesised validation error in place
of the PRD-mandated error string, and the row correctly bills the
divergence. The replica's contract is to behave as the SDK does;
choosing a schema that intercepts contract-relevant calls is the
participant's deviation, not an instrument artefact.
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
