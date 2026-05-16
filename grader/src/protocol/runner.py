#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Protocol-test runner: server spawning, JSON-RPC framing, fixtures.

The protocol-test modules drive a freshly-spawned MCP server
subprocess (Python or C implementation) over JSON-RPC stdio and
assert against the responses. This module owns the infrastructure
the assertion modules depend on:

- ``ServerProcess``: subprocess wrapper with framed stdin/stdout
  and a 10-second per-request read timeout.
- ``spawn_server``: context manager that allocates a server, runs
  the assertion's body, and tears the server down.
- ``mcp_server_env``: environment variables a participant's MCP
  server expects, parsed from the testing environment's own
  ``.env`` plus the grader-side TLS trust anchors.
- ``initialize_server``, ``call_tool``, ``extract_text``,
  ``tool_exists``: small helpers the assertion bodies share.

For the C implementation, ``call_tool`` additionally validates
``tools/call`` arguments against the participant's advertised
``inputSchema`` before the binary receives the call. The Python
implementation routes through the MCP SDK, which performs the same
validation internally; the C replica is participant-written and
runs no such gate without this enforcement, which would let a
participant whose schema and handler disagree pass C feature tests
that the Python SDK would correctly reject.

The ``ECLASS_*`` configuration values are not redeclared here:
they are parsed from the testing environment's own ``.env`` at
``<mock_root>/.env`` (the same file ``grader.src.provision`` copies
verbatim into the checkout) so the environment-variable surface
and the dotenv surface carry byte-identical values by
construction. Seed values (username, password, enrolled course
codes, announcement bodies) live in ``grader.src.seed``.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator
from typing import IO

import jsonschema

from ..env_file import parse_env_file

REQUEST_TIMEOUT_SECONDS = 10.0
SERVER_STARTUP_WAIT_SECONDS = 0.5
SERVER_SHUTDOWN_WAIT_SECONDS = 2.0
NOTIFICATION_FLUSH_WAIT_SECONDS = 0.1

PROTOCOL_VERSION = "2025-03-26"
CLIENT_NAME = "grader"
CLIENT_VERSION = "1.0.0"

BASELINE_TOOL_NAMES = frozenset({"login", "logout", "get_courses", "authstatus"})

DOTENV_FILENAME = ".env"
ECLASS_KEY_PREFIX = "ECLASS_"


@dataclass(frozen=True)
class TestContext:
    """Per-test settings carried through to the server subprocess.

    Attributes:
        impl: Implementation under test, ``"python"`` or ``"c"``.
        eclass_dir: Resolved path to the ``eclass-mcp-server``
            checkout the patch applies to.
        env_vars: Environment variables to merge into the server
            subprocess environment.
        debug: When ``True``, server stdio is echoed to stdout.
    """

    impl: str
    eclass_dir: Path
    env_vars: dict[str, str]
    debug: bool = False


class ServerProcess:
    """JSON-RPC stdio wrapper around a participant MCP server subprocess.

    Attributes:
        ctx: Per-test settings carried through to the subprocess
            (implementation, eclass directory, environment overrides).
        proc: The underlying ``Popen`` object once the subprocess
            is running, or ``None`` before ``start()`` and after
            ``stop()``.
        _advertised_tools: Cache of the participant's
            ``tools/list`` response, keyed by tool name with the
            tool's ``inputSchema`` as the value (or ``None`` when
            the participant declared no schema for that tool).
            Populated lazily on first call to
            :meth:`get_advertised_tools`.
    """

    def __init__(self, ctx: TestContext) -> None:
        """Initialise with a populated ``TestContext``.

        Args:
            ctx: The test context describing implementation,
                directory, and environment overrides.
        """
        self.ctx = ctx
        self.proc: subprocess.Popen | None = None
        self._advertised_tools: dict[str, dict | None] | None = None

    def start(self) -> bool:
        """Spawn the server subprocess.

        Returns:
            ``True`` when the subprocess started and survived the
            startup grace period; ``False`` when it failed to spawn
            or exited immediately.
        """
        env = os.environ.copy()
        env.update(self.ctx.env_vars)
        if self.ctx.impl == "python":
            cmd = ["uv", "run", "python", "-m", "src.eclass_mcp_server.server"]
            cwd = self.ctx.eclass_dir
        else:
            cmd = [str(self.ctx.eclass_dir / "c-replica" / "server")]
            cwd = self.ctx.eclass_dir / "c-replica"
        if self.ctx.debug:
            print(f"[debug] starting server: {' '.join(cmd)}")
            print(f"[debug] cwd: {cwd}")
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                env=env,
                bufsize=1,
            )
            time.sleep(SERVER_STARTUP_WAIT_SECONDS)
            if self.proc.poll() is not None:
                if self.ctx.debug:
                    stderr = self.proc.stderr.read() if self.proc.stderr else ""
                    print(f"[debug] server exited early: {stderr}")
                return False
            return True
        except OSError as error:
            if self.ctx.debug:
                print(f"[debug] failed to start server: {error}")
            return False

    def stop(self) -> None:
        """Close stdin and wait for the subprocess, killing on timeout."""
        if self.proc is None:
            return
        if self.proc.stdin is not None:
            try:
                self.proc.stdin.close()
            except (OSError, BrokenPipeError):
                pass
        try:
            self.proc.wait(timeout=SERVER_SHUTDOWN_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None

    def send_request(self, request: dict) -> dict | None:
        """Send a JSON-RPC request and return the parsed response.

        Args:
            request: JSON-RPC request payload.

        Returns:
            Parsed JSON response, or ``None`` on timeout, EOF, or
            JSON decode failure.
        """
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            return None
        try:
            line = json.dumps(request) + "\n"
            if self.ctx.debug:
                print(f"[debug] send: {line.strip()}")
            self.proc.stdin.write(line)
            self.proc.stdin.flush()
            response_line = _read_with_timeout(
                self.proc.stdout, REQUEST_TIMEOUT_SECONDS, self.ctx.debug
            )
            if not response_line:
                return None
            if self.ctx.debug:
                print(f"[debug] recv: {response_line.strip()}")
            return json.loads(response_line.strip())
        except (OSError, json.JSONDecodeError) as error:
            if self.ctx.debug:
                print(f"[debug] request error: {error}")
            return None

    def send_notification(self, notification: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self.proc is None or self.proc.stdin is None:
            return
        try:
            self.proc.stdin.write(json.dumps(notification) + "\n")
            self.proc.stdin.flush()
            time.sleep(NOTIFICATION_FLUSH_WAIT_SECONDS)
        except OSError:
            pass

    def get_advertised_tools(self) -> dict[str, dict | None]:
        """Return the tools the server advertises in ``tools/list``.

        The full ``tools/list`` response is fetched once on the
        first call and cached for the server's lifetime. Each
        entry's value is the tool's ``inputSchema`` if the
        participant declared one and it parses as a mapping;
        ``None`` otherwise.

        Returns:
            Mapping from tool name to advertised ``inputSchema``
            (or ``None``). Empty when the ``tools/list`` request
            failed or returned no tools.
        """
        if self._advertised_tools is None:
            self._advertised_tools = self._fetch_advertised_tools()
        return self._advertised_tools

    def _fetch_advertised_tools(self) -> dict[str, dict | None]:
        """Send ``tools/list`` and build the advertised-tools cache.

        Returns:
            Mapping from tool name to advertised ``inputSchema``
            (or ``None`` when the participant did not include a
            usable ``inputSchema`` for that tool).
        """
        response = self.send_request({
            "jsonrpc": "2.0",
            "id": 50,
            "method": "tools/list",
            "params": {},
        })
        if not response or "result" not in response:
            return {}
        advertised: dict[str, dict | None] = {}
        for tool in response["result"].get("tools", []):
            name = tool.get("name")
            if not isinstance(name, str):
                continue
            schema = tool.get("inputSchema")
            advertised[name] = schema if isinstance(schema, dict) else None
        return advertised


def eclass_config_pairs(mock_root: Path) -> dict[str, str]:
    """Return the ``ECLASS_*`` configuration pairs from the mock's ``.env``.

    The single source is ``<mock_root>/.env``, the testing
    environment's own dotenv file written by its install step and
    copied verbatim into the checkout by ``grader.src.provision``.
    Parsing the same file here means the environment-variable
    injection path and the dotenv provisioning path carry
    byte-identical values by construction; neither surface is
    hand-maintained. Only the ``ECLASS_*`` keys are returned; the
    TLS trust-anchor keys are supplied separately by
    :func:`tls_trust_env`.

    Args:
        mock_root: Resolved path to the testing environment install
            whose ``.env`` is the single configuration source.

    Returns:
        Mapping of ``ECLASS_*`` configuration keys to values.
    """
    mock_root = Path(mock_root).resolve()
    parsed = parse_env_file(mock_root / DOTENV_FILENAME)
    return {
        key: value
        for key, value in parsed.items()
        if key.startswith(ECLASS_KEY_PREFIX)
    }


def tls_trust_env(mock_root: Path) -> dict[str, str]:
    """Return the TLS trust-anchor environment for the spawned server.

    These keys point the participant server's HTTP client at the
    grader mock's authoritative SSO certificate. They are grader-side
    transport plumbing, not part of the participant-documented
    configuration surface, so they are kept distinct from
    :func:`eclass_config_pairs` and are never written into a ``.env``
    file.

    Args:
        mock_root: Resolved path to the testing environment install,
            used to anchor the SSL CA bundle.

    Returns:
        Mapping of TLS trust-anchor environment variables.
    """
    cert_path = str(mock_root / "certs" / "sso_cert.pem")
    return {
        "SSL_CERT_FILE": cert_path,
        "REQUESTS_CA_BUNDLE": cert_path,
        "CURL_CA_BUNDLE": cert_path,
        "PYTHONHTTPSVERIFY": "0",
    }


def mcp_server_env(mock_root: Path) -> dict[str, str]:
    """Return the environment variables a participant MCP server expects.

    The result merges the canonical ``ECLASS_*`` configuration pairs
    with the TLS trust-anchor keys, so a server spawned with this
    environment is fully configured via environment variables alone.

    Args:
        mock_root: Resolved path to the testing environment install,
            used to anchor the SSL CA bundle.

    Returns:
        Mapping suitable for ``env_vars`` on a ``TestContext``. The
        ``ECLASS_*`` values, credentials included, come from the
        testing environment's own ``.env``; the TLS trust anchors
        are appended by :func:`tls_trust_env`.
    """
    env = eclass_config_pairs(mock_root)
    env.update(tls_trust_env(mock_root))
    return env


@contextmanager
def spawn_server(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    env_overrides: dict[str, str] | None = None,
) -> Iterator[ServerProcess | None]:
    """Spawn a server, yield it for the assertion body, then stop it.

    The yielded value is the running ``ServerProcess`` on success or
    ``None`` if the server failed to start. Assertion bodies should
    branch on ``None`` and return a structured failure rather than
    raising.

    Args:
        impl: Implementation under test.
        eclass_dir: Resolved eclass-mcp-server path.
        mock_root: Resolved testing environment path.
        debug: Whether to echo server stdio.
        env_overrides: Optional overrides applied on top of the
            base server env, used by tests that exercise specific
            credential states.
    """
    env = mcp_server_env(mock_root)
    if env_overrides:
        env.update(env_overrides)
    ctx = TestContext(impl=impl, eclass_dir=eclass_dir, env_vars=env, debug=debug)
    server = ServerProcess(ctx)
    if not server.start():
        yield None
        return
    try:
        yield server
    finally:
        server.stop()


def initialize_server(server: ServerProcess) -> None:
    """Send the initialize request and the initialized notification."""
    server.send_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        },
    })
    server.send_notification({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    })


def call_tool(server: ServerProcess, tool: str, args: dict) -> dict | None:
    """Call ``tools/call`` for the given tool and return the response.

    Baseline tools accept a dummy ``random_string`` parameter; this
    helper injects it when the caller did not provide one so the
    assertion bodies do not have to. Injection runs before schema
    validation so a participant who correctly declares
    ``random_string`` as required on a baseline tool's
    ``inputSchema`` still sees a valid call.

    On the C implementation, after injection, arguments are
    validated against the participant's advertised ``inputSchema``
    for the tool. The Python implementation routes through the MCP
    SDK, which validates internally; the C replica runs no such
    gate without this check. When validation fails, this helper
    returns a synthesised response shaped like the SDK's
    validation-error response so the strict-tier assertions see
    the same response shape across implementations.
    """
    if tool in BASELINE_TOOL_NAMES and "random_string" not in args:
        args = {**args, "random_string": "test"}
    if server.ctx.impl == "c":
        schema = server.get_advertised_tools().get(tool)
        if schema is not None:
            error_response = _validate_against_schema(args, schema)
            if error_response is not None:
                return error_response
    return server.send_request({
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    })


def extract_text(response: dict | None) -> str:
    """Return the first text-content block of a ``tools/call`` response."""
    if not response or "result" not in response:
        return ""
    content = response["result"].get("content", [])
    if not content:
        return ""
    return content[0].get("text", "")


def tool_exists(server: ServerProcess, tool_name: str) -> bool:
    """Return ``True`` when the named tool appears in ``tools/list``."""
    return tool_name in server.get_advertised_tools()


def _validate_against_schema(args: dict, schema: dict) -> dict | None:
    """Validate ``args`` against ``schema``; return a synthesised error or None.

    Args:
        args: The arguments the caller is about to send.
        schema: The participant's advertised ``inputSchema`` for
            the target tool.

    Returns:
        ``None`` when ``args`` validate against ``schema``, or
        when ``schema`` itself is malformed (a malformed schema
        means the gate cannot run; the call passes through
        unvalidated rather than failing the participant on a
        schema-shape issue this helper cannot adjudicate). A
        JSON-RPC response dict shaped like the MCP Python SDK's
        validation-error response otherwise: ``result.content``
        carries a single text block whose text begins with
        ``"Input validation error: "`` followed by the
        jsonschema-derived message; ``result.isError`` is true.
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


def _read_with_timeout(stream: IO[str], timeout: float, debug: bool) -> str:
    """Read a single line from ``stream`` with a ``select``-based timeout."""
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        if debug:
            print(f"[debug] timeout: no response after {timeout}s")
        return ""
    return stream.readline()
