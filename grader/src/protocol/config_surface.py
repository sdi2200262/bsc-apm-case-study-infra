#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Configuration-surface assertions for the C replica: the C.1.3 and
C.1.4 positive probes and the C.2.4 per-surface missing-credentials
probe.

C.1.3 spawns the server with no ``.env`` on disk and only the
``ECLASS_*`` values (parsed from the testing environment's own
``.env``) plus the grader-side TLS anchors in the environment.
C.1.4 provisions the verbatim documented ``.env`` and ``certs/``
and places no ``ECLASS_*`` and no TLS variables in the
environment. Each probe drives ``initialize`` plus one
authenticated ``login``: only a real login proves the surface
under test was read.

C.2.4 mirrors that isolation for the negative contract: each
implemented surface is deprived of credentials and must return the
missing-credentials error. A surface a participant did not
implement is penalised once at C.1.3/C.1.4 and not billed again,
so C.2.4 is scored only on implemented surfaces (the C.1.3/C.1.4
verdicts are passed in by the caller).

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
    CREDENTIAL_KEYS,
    DOTENV_FILENAME,
    blank_dotenv_credentials,
    install_sso_cert,
    provision,
    write_dotenv,
)
from ..seed import SEED
from .baseline_tests import LOGIN_MISSING_CREDS
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


def test_missing_credentials_attributed(
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    *,
    env_surface_implemented: bool,
    dotenv_surface_implemented: bool,
) -> tuple[bool, str, str]:
    """C.2.4: missing-credentials handling, billed per implemented surface.

    Each implemented surface is deprived of credentials in isolation
    and must return the exact missing-credentials error. A surface a
    participant did not implement is already penalised at C.1.3 or
    C.1.4 and is not billed again here, so the row is scored only on
    the surfaces ``env_surface_implemented``/``dotenv_surface_implemented``
    mark and passes iff every scored surface reports the error; with
    neither implemented the loss is attributed to C.1.3/C.1.4. The
    verbatim ``.env`` and ``certs/`` are restored unconditionally so
    the rows that follow see the dual-provisioned state.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.
        env_surface_implemented: Whether C.1.3 passed (the env-var
            surface is implemented and therefore scored here).
        dotenv_surface_implemented: Whether C.1.4 passed (the
            dotenv surface is implemented and therefore scored).

    Returns:
        Tuple of ``(passed, summary, detail)``.
    """
    eclass_dir = Path(eclass_dir).resolve()
    mock_root = Path(mock_root).resolve()
    if not env_surface_implemented and not dotenv_surface_implemented:
        message = (
            "C.2.4: no configuration surface implemented; missing-credentials "
            "handling is attributed to C.1.3/C.1.4 and not billed again here"
        )
        return (False, message, message)
    outcomes: list[tuple[str, bool, str]] = []
    try:
        if env_surface_implemented:
            (eclass_dir / DOTENV_FILENAME).unlink(missing_ok=True)
            env = eclass_config_pairs(mock_root)
            for key in CREDENTIAL_KEYS:
                env[key] = ""
            env.update(tls_trust_env(mock_root))
            ok, _summary, detail = _missing_creds_probe(
                eclass_dir,
                env,
                debug,
                "env-var surface",
                neutralise_inherited=False,
            )
            outcomes.append(("env-var surface", ok, detail))
        if dotenv_surface_implemented:
            write_dotenv(eclass_dir, mock_root)
            install_sso_cert(eclass_dir, mock_root)
            blank_dotenv_credentials(eclass_dir)
            ok, _summary, detail = _missing_creds_probe(
                eclass_dir,
                {},
                debug,
                "verbatim documented .env surface",
                neutralise_inherited=True,
            )
            outcomes.append(("verbatim documented .env surface", ok, detail))
    finally:
        provision(eclass_dir, mock_root)
    scored = ", ".join(label for label, _ok, _detail in outcomes)
    passed = all(ok for _label, ok, _detail in outcomes)
    if passed:
        summary = (
            f"C.2.4: missing-credentials error returned on every scored "
            f"surface ({scored})"
        )
    else:
        failed = ", ".join(
            label for label, ok, _detail in outcomes if not ok
        )
        summary = (
            f"C.2.4: missing-credentials handling failed on {failed} "
            f"(scored surfaces: {scored})"
        )
    detail = " | ".join(
        f"{label}: {dtl}" for label, _ok, dtl in outcomes
    )
    return (passed, summary, detail)


def _handshake_then_login(
    test_id: str,
    eclass_dir: Path,
    env: dict[str, str],
    debug: bool,
    surface_label: str,
    neutralise_inherited: bool,
) -> tuple[str | None, tuple[bool, str, str] | None]:
    """Spawn the C server, run ``initialize``, and return the login text.

    The shared spawn/handshake/login sequence for the surface
    probes. The server environment is restricted to exactly the
    keys in ``env`` (no inherited ``ECLASS_*`` bleed-through) so the
    surface under test is the only configuration source.

    Args:
        test_id: Rubric identifier the result is recorded under.
        eclass_dir: Resolved eclass-mcp-server checkout path.
        env: The exact environment overrides for the spawn.
        debug: When ``True``, server stdio is echoed to stdout.
        surface_label: Human-readable surface name for messages.
        neutralise_inherited: When ``True``, any ``ECLASS_*`` or TLS
            trust-anchor key the operator shell exports that ``env``
            does not set is overridden empty so the on-disk surface
            is the only configuration source.

    Returns:
        ``(login_text, None)`` once the authenticated ``login`` tool
        has returned, or ``(None, failure)`` where ``failure`` is
        the ``(passed, summary, detail)`` triple for the first step
        that did not hold (spawn or ``initialize``).
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
            return None, (
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
    finally:
        server.stop()
    return login_text, None


def _probe(
    test_id: str,
    eclass_dir: Path,
    env: dict[str, str],
    debug: bool,
    surface_label: str,
) -> tuple[bool, str, str]:
    """Spawn the C server under ``env``, handshake, and prove login.

    Asserts that the server authenticates (the seeded success
    string appears) reading only the surface under test, so the
    surface is proven readable. Fails with a single actionable
    summary at the first step that does not hold: spawn,
    ``initialize``, or the authenticated ``login``.

    Args:
        test_id: Rubric identifier the result is recorded under.
        eclass_dir: Resolved eclass-mcp-server checkout path.
        env: The exact environment overrides for the spawn.
        debug: When ``True``, server stdio is echoed to stdout.
        surface_label: Human-readable surface name for the summary.

    Returns:
        Tuple of ``(passed, summary, detail)``.
    """
    login_text, failure = _handshake_then_login(
        test_id,
        eclass_dir,
        env,
        debug,
        surface_label,
        neutralise_inherited=(test_id == "C.1.4"),
    )
    if failure is not None:
        return failure
    if LOGIN_SUCCESS not in login_text:
        return (
            False,
            f"{test_id}: login did not succeed under the "
            f"{surface_label}; configuration was not read",
            f"{test_id}: expected {LOGIN_SUCCESS!r} in the login "
            f"response under the {surface_label}; got {login_text!r}",
        )
    return (
        True,
        f"{test_id}: initialize and authenticated login succeeded under "
        f"the {surface_label}",
        f"{test_id}: the C server completed the initialize handshake and "
        f"authenticated with the seeded credentials reading only the "
        f"{surface_label}",
    )


def _missing_creds_probe(
    eclass_dir: Path,
    env: dict[str, str],
    debug: bool,
    surface_label: str,
    *,
    neutralise_inherited: bool,
) -> tuple[bool, str, str]:
    """Spawn under ``env``, handshake, and assert the missing-credentials error.

    The surface-isolated counterpart to :func:`_probe`: the same
    spawn/initialize/login sequence, but the contract is the exact
    ``LOGIN_MISSING_CREDS`` string rather than a successful login,
    so it proves the server reports missing credentials on the
    deprived surface instead of authenticating.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        env: The exact environment overrides for the spawn.
        debug: When ``True``, server stdio is echoed to stdout.
        surface_label: Human-readable surface name for the summary.
        neutralise_inherited: Passed through to the shared spawn so
            the dotenv sub-probe sees no inherited ``ECLASS_*``/TLS.

    Returns:
        Tuple of ``(passed, summary, detail)``.
    """
    login_text, failure = _handshake_then_login(
        "C.2.4", eclass_dir, env, debug, surface_label, neutralise_inherited
    )
    if failure is not None:
        return failure
    if login_text != LOGIN_MISSING_CREDS:
        return (
            False,
            f"C.2.4: expected the missing-credentials error under the "
            f"{surface_label}; the surface was not deprived correctly",
            f"C.2.4: expected {LOGIN_MISSING_CREDS!r} under the "
            f"{surface_label}; got {login_text!r}",
        )
    return (
        True,
        f"C.2.4: missing-credentials error returned under the {surface_label}",
        f"C.2.4: the C server reported missing credentials with the "
        f"{surface_label} deprived",
    )


def _strip_eclass_inherited(
    env: dict[str, str], neutralise_inherited: bool
) -> dict[str, str]:
    """Return ``env``, optionally neutralising inherited config keys.

    The runner spawn merges overrides on top of ``os.environ``. When
    ``neutralise_inherited`` is ``True`` the contract is "nothing in
    the process environment configures the server": any ``ECLASS_*``
    or TLS trust-anchor key the operator shell exports that ``env``
    does not itself set is overridden with an empty value rather
    than silently inherited, so the only configuration source is the
    on-disk ``.env`` and ``certs/``. When ``False`` (an env-var
    surface probe) ``env`` already carries the keys it needs and is
    returned unchanged.

    Args:
        env: The surface-under-test overrides.
        neutralise_inherited: Whether to strip inherited
            ``ECLASS_*``/TLS keys (the on-disk surface probes).

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
