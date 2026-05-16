#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Configuration-surface assertions for the C replica: C.1.3 and C.1.4.

C.1.3 spawns the server with no ``.env`` on disk and only the
``ECLASS_*`` values (parsed from the testing environment's own
``.env``) plus the grader-side TLS anchors in the environment.
C.1.4 provisions the verbatim documented ``.env`` and ``certs/``
and places no ``ECLASS_*`` and no TLS variables in the
environment. Each probe drives ``initialize`` plus one
authenticated ``login``: only a real login proves the surface
under test was read.

The TLS anchors stay in C.1.3's environment because they are
grader-side transport plumbing, not the participant-documented
configuration surface; C.1.4 needs none there since the verbatim
``.env``/``certs`` supply trust on disk.
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
from ..seed import SEED
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

LOGIN_SUCCESS = f"Login successful! You are now logged in as {SEED.username}."

IMPL = "c"


def test_env_var_config_surface(
    eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """C.1.3: server handshakes and logs in configured via ``ECLASS_*`` only.

    The eclass checkout's ``.env`` is removed before the spawn so
    the only configuration source is the injected environment: the
    ``ECLASS_*`` values parsed from the testing environment's own
    ``.env`` plus the grader-side TLS trust anchors (whose
    ``SSL_CERT_FILE`` is an absolute path into ``<mock_root>``, so
    no on-disk ``certs/`` in the checkout is consulted). A
    successful ``initialize`` plus a login that returns the seeded
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
    return _probe(
        "C.1.3",
        eclass_dir,
        env,
        debug,
        "env-var surface",
    )


def test_dotenv_config_surface(
    eclass_dir: Path, mock_root: Path, debug: bool
) -> tuple[bool, str, str]:
    """C.1.4: server handshakes and logs in via the verbatim ``.env``.

    The testing environment's own ``.env`` and its ``certs/``
    directory are copied verbatim into the checkout (the literal
    documented local-development wiring). No ``ECLASS_*`` and no TLS
    trust-anchor variables are placed in the process environment:
    the copied ``.env`` carries ``SSL_CERT_FILE=./certs/
    sso_cert.pem`` and the copied ``certs/`` makes that relative
    path resolve, so the server is configured entirely on disk. A
    successful ``initialize`` plus a login that returns the seeded
    success string proves the dotenv surface was read.

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
        "C.1.4",
        eclass_dir,
        {},
        debug,
        "verbatim documented .env surface",
    )


def _probe(
    test_id: str,
    eclass_dir: Path,
    env: dict[str, str],
    debug: bool,
    surface_label: str,
) -> tuple[bool, str, str]:
    """Spawn the C server under ``env``, handshake, and prove login.

    The server environment is restricted to exactly the keys in
    ``env`` (no inherited ``ECLASS_*`` bleed-through) so the surface
    under test is the only configuration source. The probe fails
    with a single actionable summary at the first step that does not
    hold: spawn, ``initialize``, or the authenticated ``login``.

    Args:
        test_id: Rubric identifier the result is recorded under.
        eclass_dir: Resolved eclass-mcp-server checkout path.
        env: The exact environment overrides for the spawn.
        debug: When ``True``, server stdio is echoed to stdout.
        surface_label: Human-readable surface name for the summary.

    Returns:
        Tuple of ``(passed, summary, detail)``.
    """
    ctx = TestContext(
        impl=IMPL,
        eclass_dir=Path(eclass_dir).resolve(),
        env_vars=_strip_eclass_inherited(env, test_id),
        debug=debug,
    )
    server = ServerProcess(ctx)
    if not server.start():
        return (
            False,
            f"{test_id}: server did not start under the {surface_label}",
            f"{test_id}: the C server failed to spawn or exited during the "
            f"startup grace period with only the {surface_label} configured",
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
            return (
                False,
                f"{test_id}: initialize did not return a result under the "
                f"{surface_label}",
                f"{test_id}: initialize response under the {surface_label}: "
                f"{json.dumps(init_response)}",
            )
        server.send_notification({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        login_text = extract_text(call_tool(server, "login", {}))
        if LOGIN_SUCCESS not in login_text:
            return (
                False,
                f"{test_id}: login did not succeed under the "
                f"{surface_label}; configuration was not read",
                f"{test_id}: expected {LOGIN_SUCCESS!r} in the login "
                f"response under the {surface_label}; got {login_text!r}",
            )
    finally:
        server.stop()
    return (
        True,
        f"{test_id}: initialize and authenticated login succeeded under "
        f"the {surface_label}",
        f"{test_id}: the C server completed the initialize handshake and "
        f"authenticated with the seeded credentials reading only the "
        f"{surface_label}",
    )


def _strip_eclass_inherited(
    env: dict[str, str], test_id: str
) -> dict[str, str]:
    """Return ``env`` with inherited config keys neutralised for C.1.4.

    The runner spawn merges overrides on top of ``os.environ``. The
    verbatim-``.env`` probe's contract is "nothing in the process
    environment configures the server": no ``ECLASS_*`` and no TLS
    trust-anchor variable, so the only configuration source is the
    copied ``.env`` and ``certs/`` on disk. Any such key the
    operator shell happens to export is overridden with an empty
    value rather than silently inherited. For the env-var probe
    ``env`` already carries the keys it needs, so no neutralisation
    runs.

    Args:
        env: The surface-under-test overrides.
        test_id: Rubric identifier; only the verbatim-``.env``
            probe (``"C.1.4"``) neutralises inherited keys.

    Returns:
        The override mapping the spawn should apply.
    """
    if test_id != "C.1.4":
        return dict(env)
    neutralised = dict(env)
    for key in os.environ:
        if key in neutralised:
            continue
        if key.startswith("ECLASS_") or key in TLS_TRUST_ENV_KEYS:
            neutralised[key] = ""
    return neutralised
