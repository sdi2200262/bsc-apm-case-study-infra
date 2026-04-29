#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
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
  server expects, derived from the testing environment install
  and the loaded seed credentials.
- ``initialize_server``, ``call_tool``, ``extract_text``,
  ``tool_exists``: small helpers the assertion bodies share.

Seed values (username, password, enrolled course codes,
announcement bodies) live in ``grader.src.seed`` and are read from
there rather than redeclared here.
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
from typing import Iterator

from ..seed import SEED

REQUEST_TIMEOUT_SECONDS = 10.0
SERVER_STARTUP_WAIT_SECONDS = 0.5
SERVER_SHUTDOWN_WAIT_SECONDS = 2.0
NOTIFICATION_FLUSH_WAIT_SECONDS = 0.1

PROTOCOL_VERSION = "2025-03-26"
CLIENT_NAME = "grader"
CLIENT_VERSION = "1.0.0"

BASELINE_TOOL_NAMES = frozenset({"login", "logout", "get_courses", "authstatus"})

ECLASS_BASE_URL = "http://localhost"
SSO_DOMAIN = "172.17.0.1:8082"
SSO_PROTOCOL = "https"


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
    """JSON-RPC stdio wrapper around a participant MCP server subprocess."""

    def __init__(self, ctx: TestContext) -> None:
        """Initialise with a populated ``TestContext``.

        Args:
            ctx: The test context describing implementation,
                directory, and environment overrides.
        """
        self.ctx = ctx
        self.proc: subprocess.Popen | None = None

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


def mcp_server_env(mock_root: Path) -> dict[str, str]:
    """Return the environment variables a participant MCP server expects.

    Args:
        mock_root: Resolved path to the testing environment install,
            used to anchor the SSL CA bundle.

    Returns:
        Mapping suitable for ``env_vars`` on a ``TestContext``. The
        username and password are read from the loaded seed.
    """
    cert_path = str(mock_root / "certs" / "sso_cert.pem")
    return {
        "ECLASS_URL": ECLASS_BASE_URL,
        "ECLASS_USERNAME": SEED.username,
        "ECLASS_PASSWORD": SEED.password,
        "ECLASS_SSO_DOMAIN": SSO_DOMAIN,
        "ECLASS_SSO_PROTOCOL": SSO_PROTOCOL,
        "SSL_CERT_FILE": cert_path,
        "REQUESTS_CA_BUNDLE": cert_path,
        "CURL_CA_BUNDLE": cert_path,
        "PYTHONHTTPSVERIFY": "0",
    }


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
    assertion bodies do not have to.
    """
    if tool in BASELINE_TOOL_NAMES and "random_string" not in args:
        args = {**args, "random_string": "test"}
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
    response = server.send_request({
        "jsonrpc": "2.0",
        "id": 50,
        "method": "tools/list",
        "params": {},
    })
    if not response or "result" not in response:
        return False
    tools = response["result"].get("tools", [])
    return any(tool.get("name") == tool_name for tool in tools)


def _read_with_timeout(stream, timeout: float, debug: bool) -> str:
    """Read a single line from ``stream`` with a ``select``-based timeout."""
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        if debug:
            print(f"[debug] timeout: no response after {timeout}s")
        return ""
    return stream.readline()
