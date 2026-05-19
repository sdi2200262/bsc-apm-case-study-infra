#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Protocol-test runner: server spawning, JSON-RPC framing, fixtures.

Drives a freshly-spawned MCP server subprocess (Python or C) over
JSON-RPC stdio. The public surface is enumerated in ``__all__``: a
``ServerProcess`` subprocess wrapper, a ``spawn_server`` context
manager, the JSON-RPC helpers (``initialize_server``, ``call_tool``,
``extract_text``), the spawned-server environment block re-exported
from :mod:`.server_env` (``eclass_config_pairs``, ``tls_trust_env``,
``mcp_server_env``), and the constructed client identity constants
(``CLIENT_NAME``, ``CLIENT_VERSION``, ``PROTOCOL_VERSION``). For C,
``call_tool`` validates ``tools/call`` arguments against the
participant's advertised ``inputSchema`` before the binary receives
the call.

On a credential-bearing spawn (``env_overrides`` carrying a non-empty
``ECLASS_USERNAME`` and ``ECLASS_PASSWORD``) ``spawn_server`` also
projects that principal onto the checkout's on-disk ``.env`` for the
duration of the spawn and restores the provisioned ``.env``
afterward, so both documented configuration surfaces carry the
scenario's principal. An all-empty credential override (the
missing-credentials deprivation probe) is not projected; the caller's
own ``.env`` deprivation stays in force.

When ``memcheck=True`` and ``impl="c"``, ``spawn_server`` wraps the
binary under valgrind; after the context manager exits the caller
may call ``server.leak_verdict()`` on the still-live reference. The
valgrind leak parsers live in :mod:`._memcheck` and the spawned-server
environment block in :mod:`.server_env`.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator
from typing import IO

from .. import provision
from ._memcheck import VALGRIND_STDERR_TAIL_LINES, parse_leak_bytes, tail_lines
from ._schema_validation import validate_against_schema
from .server_env import eclass_config_pairs, mcp_server_env, tls_trust_env

__all__ = [
    "ServerProcess",
    "TestContext",
    "spawn_server",
    "initialize_server",
    "call_tool",
    "extract_text",
    "eclass_config_pairs",
    "tls_trust_env",
    "mcp_server_env",
    "CLIENT_NAME",
    "CLIENT_VERSION",
    "PROTOCOL_VERSION",
]

REQUEST_TIMEOUT_SECONDS = 10.0
MEMCHECK_REQUEST_TIMEOUT_SECONDS = 60.0
SERVER_STARTUP_WAIT_SECONDS = 0.5
SERVER_SHUTDOWN_WAIT_SECONDS = 2.0
NOTIFICATION_FLUSH_WAIT_SECONDS = 0.1

PROTOCOL_VERSION = "2025-03-26"
CLIENT_NAME = "grader"
CLIENT_VERSION = "1.0.0"

BASELINE_TOOL_NAMES = frozenset({"login", "logout", "get_courses", "authstatus"})


@dataclass(frozen=True)
class TestContext:
    """Per-test settings carried through to the server subprocess.

    Attributes:
        impl: ``"python"`` or ``"c"``.
        eclass_dir: Resolved eclass-mcp-server checkout path.
        env_vars: Environment overrides for the subprocess.
        debug: Echo server stdio when ``True``.
        memcheck: Run C binary under valgrind when ``True``
            (ignored for Python).
    """

    impl: str
    eclass_dir: Path
    env_vars: dict[str, str]
    debug: bool = False
    memcheck: bool = False


class ServerProcess:
    """JSON-RPC stdio wrapper around a participant MCP server subprocess.

    Attributes:
        ctx: Per-test settings carried through to the subprocess.
        proc: Underlying ``Popen`` while running; ``None`` otherwise.
        _advertised_tools: Lazy cache of ``tools/list`` response,
            keyed by tool name to its ``inputSchema`` or ``None``.
        _valgrind_stderr_file: Open file handle capturing valgrind's
            stderr in the memcheck path; ``None`` in the non-memcheck
            path. Persists after ``stop()`` for :meth:`leak_verdict`.
        _proc_exit_code: Exit code recorded at ``stop()`` time; used
            by :meth:`leak_verdict` to check the error sentinel.
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
        self._valgrind_stderr_file: IO[str] | None = None
        self._proc_exit_code: int | None = None

    def start(self) -> bool:
        """Spawn the server subprocess.

        When ``ctx.memcheck`` and ``ctx.impl == "c"``, the binary
        is wrapped under valgrind with full leak checking; valgrind
        stderr is redirected to a ``NamedTemporaryFile`` (not a PIPE)
        to prevent a verbose report from deadlocking the subprocess.

        Returns:
            ``True`` when the subprocess started and survived the
            startup grace period; ``False`` otherwise.
        """
        env = os.environ.copy()
        env.update(self.ctx.env_vars)
        if self.ctx.impl == "python":
            cmd = ["uv", "run", "python", "-m", "src.eclass_mcp_server.server"]
            cwd = self.ctx.eclass_dir
        else:
            server_binary = str(self.ctx.eclass_dir / "c-replica" / "server")
            cwd = self.ctx.eclass_dir / "c-replica"
            if self.ctx.memcheck:
                cmd = [
                    "valgrind",
                    "--leak-check=full",
                    "--show-leak-kinds=all",
                    "--error-exitcode=99",
                    server_binary,
                ]
            else:
                cmd = [server_binary]
        if self.ctx.debug:
            print(f"[debug] starting server: {' '.join(cmd)}")
            print(f"[debug] cwd: {cwd}")
        try:
            if self.ctx.impl == "c" and self.ctx.memcheck:
                self._valgrind_stderr_file = tempfile.NamedTemporaryFile(
                    mode="w+",
                    suffix=".valgrind.txt",
                    delete=False,
                )
                stderr_arg = self._valgrind_stderr_file
            else:
                stderr_arg = subprocess.PIPE
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_arg,
                text=True,
                cwd=cwd,
                env=env,
                bufsize=1,
            )
            time.sleep(SERVER_STARTUP_WAIT_SECONDS)
            if self.proc.poll() is not None:
                self._emit_start_failure(self.proc.returncode)
                return False
            return True
        except OSError as error:
            print(
                f"server start failed: {self.ctx.impl} subprocess "
                f"could not be launched: {error}",
                file=sys.stderr,
            )
            return False

    def _emit_start_failure(self, returncode: int) -> None:
        """Print one operator-visible line describing an early-exit start failure.

        Reads the captured stderr (valgrind file or the subprocess
        pipe), keeps a bounded tail, classifies a negative
        ``returncode`` as a signal exit, and writes one line to
        stderr so an operator running without ``--debug`` still sees
        why the server did not stay up.
        """
        if self._valgrind_stderr_file is not None:
            self._valgrind_stderr_file.flush()
            self._valgrind_stderr_file.seek(0)
            stderr_text = self._valgrind_stderr_file.read()
        elif self.proc is not None and self.proc.stderr is not None:
            try:
                stderr_text = self.proc.stderr.read() or ""
            except (OSError, ValueError):
                stderr_text = ""
        else:
            stderr_text = ""
        tail = tail_lines(stderr_text, VALGRIND_STDERR_TAIL_LINES).strip()
        if returncode < 0:
            why = f"killed by signal {-returncode}"
        else:
            why = f"exited with code {returncode}"
        detail = f"; stderr tail: {tail}" if tail else ""
        print(
            f"server start failed: {self.ctx.impl} subprocess {why}{detail}",
            file=sys.stderr,
        )

    def stop(self) -> None:
        """Close stdin, wait for the subprocess (killing on timeout), record exit."""
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
            self.proc.wait()
        self._proc_exit_code = self.proc.returncode
        self.proc = None
        if self._valgrind_stderr_file is not None:
            self._valgrind_stderr_file.flush()

    def leak_verdict(self) -> tuple[bool, str]:
        """Return the valgrind leak verdict after ``stop()`` has been called.

        Call only when ``ctx.memcheck`` and ``ctx.impl == "c"``.
        Clean iff exit code is not 99 AND both ``definitely lost``
        and ``indirectly lost`` are zero bytes.

        Returns:
            Tuple of ``(clean, detail_text)`` where ``detail_text``
            is the last ``VALGRIND_STDERR_TAIL_LINES`` lines of the
            captured valgrind report.
        """
        if self._valgrind_stderr_file is None:
            return True, "(no memcheck; not a valgrind run)"
        self._valgrind_stderr_file.seek(0)
        raw = self._valgrind_stderr_file.read()
        report = tail_lines(raw, VALGRIND_STDERR_TAIL_LINES)
        exit_code = self._proc_exit_code if self._proc_exit_code is not None else 0
        definitely_lost = parse_leak_bytes(raw, "definitely lost")
        indirectly_lost = parse_leak_bytes(raw, "indirectly lost")
        clean = (exit_code != 99) and (definitely_lost == 0) and (indirectly_lost == 0)
        return clean, report

    def send_request(self, request: dict) -> dict | None:
        """Send a JSON-RPC request; return the parsed response or ``None``."""
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            return None
        try:
            line = json.dumps(request) + "\n"
            if self.ctx.debug:
                print(f"[debug] send: {line.strip()}")
            self.proc.stdin.write(line)
            self.proc.stdin.flush()
            timeout = (
                MEMCHECK_REQUEST_TIMEOUT_SECONDS
                if self.ctx.memcheck
                else REQUEST_TIMEOUT_SECONDS
            )
            response_line = _read_with_timeout(
                self.proc.stdout, timeout, self.ctx.debug
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
        """Return the tools the server advertises, fetched once and cached.

        Returns:
            Mapping from tool name to its ``inputSchema`` or
            ``None``. Empty when the request failed.
        """
        if self._advertised_tools is None:
            self._advertised_tools = self._fetch_advertised_tools()
        return self._advertised_tools

    def _fetch_advertised_tools(self) -> dict[str, dict | None]:
        """Send ``tools/list`` and return the name-to-inputSchema mapping."""
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


@contextmanager
def spawn_server(
    impl: str,
    eclass_dir: Path,
    mock_root: Path,
    debug: bool,
    env_overrides: dict[str, str] | None = None,
    memcheck: bool = False,
) -> Iterator[ServerProcess | None]:
    """Spawn a server, yield it for the assertion body, then stop it.

    Yields ``None`` when the server failed to start; assertion bodies
    branch on ``None`` and return a structured failure. When
    ``memcheck`` is ``True`` and ``impl == "c"``, the binary runs
    under valgrind; after ``stop()`` the caller may call
    ``server.leak_verdict()`` on the still-live reference.

    When ``env_overrides`` carries a non-empty ``ECLASS_USERNAME``
    and ``ECLASS_PASSWORD``, that principal is also projected onto
    the checkout's on-disk ``.env`` for the spawn and the
    provisioned ``.env`` is restored afterward, so a server reading
    only the documented ``.env`` authenticates as the same principal
    the env-var surface carries. An all-empty credential override is
    the missing-credentials deprivation probe: it is not projected,
    so the caller's own ``.env`` deprivation stays in force.

    Args:
        impl: Implementation under test.
        eclass_dir: Resolved eclass-mcp-server path.
        mock_root: Resolved testing environment path.
        debug: Whether to echo server stdio.
        env_overrides: Optional credential / credential-state
            overrides. A non-empty principal here is projected onto
            the on-disk ``.env`` as well; an all-empty deprivation
            override is not.
        memcheck: Run under valgrind (C only).
    """
    env = mcp_server_env(mock_root)
    if env_overrides:
        env.update(env_overrides)
    # Project a principal-bearing override onto the on-disk .env as
    # well, so a server that reads only the documented .env file
    # (PRD section 4 makes that surface legitimate) authenticates as
    # the same principal the env-var surface carries. The guard
    # requires both values present AND non-empty: the
    # missing-credentials probe passes "" / "" to deprive both
    # surfaces and has already blanked the on-disk .env itself, so
    # re-writing it here would defeat that deprivation.
    projected = False
    if env_overrides:
        username = env_overrides.get("ECLASS_USERNAME")
        password = env_overrides.get("ECLASS_PASSWORD")
        if username and password:
            provision.set_dotenv_credentials(eclass_dir, username, password)
            projected = True
    try:
        ctx = TestContext(
            impl=impl,
            eclass_dir=eclass_dir,
            env_vars=env,
            debug=debug,
            memcheck=memcheck,
        )
        server = ServerProcess(ctx)
        if not server.start():
            yield None
            return
        try:
            yield server
        finally:
            server.stop()
    finally:
        # Restore the provisioned .env verbatim (single-sourced from
        # <mock_root>/.env, so SSL_CERT_FILE and every non-credential
        # key are exactly as provisioned) only when this spawn
        # projected a principal, so non-credential spawns and the
        # missing-credentials probe's own .env management are left
        # untouched.
        if projected:
            provision.write_dotenv(eclass_dir, mock_root)


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

    Injects ``random_string`` for baseline tools when absent. For C,
    validates args against the participant's advertised
    ``inputSchema``; when validation fails, returns a synthesised
    response shaped like the SDK's validation-error response.
    """
    if tool in BASELINE_TOOL_NAMES and "random_string" not in args:
        args = {**args, "random_string": "test"}
    if server.ctx.impl == "c":
        schema = server.get_advertised_tools().get(tool)
        if schema is not None:
            error_response = validate_against_schema(args, schema)
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


def _read_with_timeout(stream: IO[str], timeout: float, debug: bool) -> str:
    """Read a single line from ``stream`` with a ``select``-based timeout."""
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        if debug:
            print(f"[debug] timeout: no response after {timeout}s")
        return ""
    return stream.readline()
