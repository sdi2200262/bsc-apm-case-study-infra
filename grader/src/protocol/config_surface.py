#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Configuration-surface assertions for the C replica: C.1.5 and C.1.6.

C.1.5 spawns the server with no ``.env`` on disk and only the
``ECLASS_*`` values (parsed from the testing environment's own
``.env``) plus the grader-side TLS anchors in the environment.
C.1.6 provisions the verbatim documented ``.env`` and ``certs/``
and places no ``ECLASS_*`` and no TLS variables in the environment.
Each probe drives ``initialize`` plus one authenticated ``login``:
only a real login proves the surface under test was read.

Missing-credentials handling is a single behavioural row
(P.1.6 / C.2.7) in ``baseline_tests`` with both surfaces deprived
together; this module only owns the two positive surface probes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..provision import (
    DOTENV_FILENAME,
    install_sso_cert,
    write_dotenv,
)
from ..seed import SEED, user
from .expected import login_success
from .runner import (
    CLIENT_NAME,
    CLIENT_VERSION,
    PROTOCOL_VERSION,
    ServerProcess,
    TestContext,
    call_tool,
    eclass_config_pairs,
    extract_text,
    tls_trust_env,
)

TLS_TRUST_ENV_KEYS = (
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "PYTHONHTTPSVERIFY",
)

_PRINCIPAL = user(SEED, "student_courses")
LOGIN_SUCCESS = login_success(_PRINCIPAL.username)

IMPL = "c"


def test_env_var_config_surface(
    eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """C.1.5: server handshakes and logs in configured via ``ECLASS_*`` only.

    The eclass checkout's ``.env`` is removed before the spawn so
    the only configuration source is the injected environment.
    A successful ``initialize`` plus a login that returns the seeded
    success string proves the env-var surface was read.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.

    Returns:
        Tuple of ``(passed, summary, detail)``.
    """
    dotenv_path = Path(eclass_dir).resolve() / DOTENV_FILENAME
    dotenv_path.unlink(missing_ok=True)
    env = eclass_config_pairs(mock_root)
    env.update(tls_trust_env(mock_root))
    return _probe("C.1.5", eclass_dir, env, debug, "env-var surface")


def test_dotenv_config_surface(
    eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """C.1.6: server handshakes and logs in via the verbatim ``.env``.

    The testing environment's own ``.env`` and its ``certs/``
    directory are copied verbatim into the checkout. No ``ECLASS_*``
    and no TLS trust-anchor variables are placed in the process
    environment; the copied ``.env`` carries ``SSL_CERT_FILE`` and
    the copied ``certs/`` makes that relative path resolve. A
    successful ``initialize`` plus a login proves the dotenv surface
    was read.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.

    Returns:
        Tuple of ``(passed, summary, detail)``.
    """
    write_dotenv(eclass_dir, mock_root)
    install_sso_cert(eclass_dir, mock_root)
    return _probe(
        "C.1.6", eclass_dir, {}, debug, "verbatim documented .env surface"
    )


def _probe(
    test_id: str,
    eclass_dir: Path,
    env: dict[str, str],
    debug: bool,
    surface_label: str,
) -> tuple[bool, str, str]:
    """Spawn the C server under ``env``, handshake, and prove login.

    Args:
        test_id: Rubric identifier the result is recorded under.
        eclass_dir: Resolved eclass-mcp-server checkout path.
        env: The exact environment overrides for the spawn.
        debug: When ``True``, server stdio is echoed to stdout.
        surface_label: Human-readable surface name for the summary.

    Returns:
        Tuple of ``(passed, summary, detail)``.
    """
    neutralise = test_id == "C.1.6"
    login_text, failure = _handshake_then_login(
        test_id, eclass_dir, env, debug, surface_label, neutralise
    )
    if failure is not None:
        return failure
    if login_text != LOGIN_SUCCESS:
        return (
            False,
            f"{test_id}: login did not succeed under the {surface_label}",
            f"{test_id}: expected {LOGIN_SUCCESS!r} under the "
            f"{surface_label}; got {login_text!r}",
        )
    return (
        True,
        f"{test_id}: initialize and authenticated login succeeded under "
        f"the {surface_label}",
        f"{test_id}: the C server authenticated reading only the {surface_label}",
    )


def _handshake_then_login(
    test_id: str,
    eclass_dir: Path,
    env: dict[str, str],
    debug: bool,
    surface_label: str,
    neutralise_inherited: bool,
) -> tuple[str | None, tuple[bool, str, str] | None]:
    """Spawn, initialize, login; return login text or a failure triple.

    Args:
        test_id: Rubric identifier for failure messages.
        eclass_dir: Resolved eclass-mcp-server checkout path.
        env: Surface-under-test environment overrides.
        debug: Echo server stdio when ``True``.
        surface_label: Human-readable surface name.
        neutralise_inherited: Strip inherited ``ECLASS_*``/TLS keys
            from the process environment so the on-disk surface is
            the only configuration source.

    Returns:
        ``(login_text, None)`` on success; ``(None, failure)`` where
        ``failure`` is a ``(passed, summary, detail)`` triple on the
        first step that does not hold.
    """
    ctx = TestContext(
        impl=IMPL,
        eclass_dir=Path(eclass_dir).resolve(),
        env_vars=_strip_eclass_inherited(env, neutralise_inherited),
        debug=debug,
    )
    server = ServerProcess(ctx)
    if not server.start():
        return None, (
            False,
            f"{test_id}: server did not start under the {surface_label}",
            f"{test_id}: the C server failed to spawn with only the "
            f"{surface_label} configured",
        )
    try:
        init_response = server.send_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        })
        if not init_response or "result" not in init_response:
            return None, (
                False,
                f"{test_id}: initialize did not return a result under "
                f"the {surface_label}",
                f"{test_id}: initialize response: {json.dumps(init_response)}",
            )
        server.send_notification({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        login_text = extract_text(call_tool(server, "login", {}))
    finally:
        server.stop()
    return login_text, None


def _strip_eclass_inherited(
    env: dict[str, str], neutralise_inherited: bool
) -> dict[str, str]:
    """Return ``env``, optionally neutralising inherited config keys.

    Args:
        env: Surface-under-test overrides.
        neutralise_inherited: When ``True``, override any inherited
            ``ECLASS_*`` or TLS key not already in ``env`` with
            an empty string so the on-disk surface is the sole source.

    Returns:
        The override mapping the spawn should apply.
    """
    if not neutralise_inherited:
        return dict(env)
    neutralised = dict(env)
    for key in os.environ:
        if key in neutralised:
            continue
        if key.startswith("ECLASS_") or key in TLS_TRUST_ENV_KEYS:
            neutralised[key] = ""
    return neutralised
