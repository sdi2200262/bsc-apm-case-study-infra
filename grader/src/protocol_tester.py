#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Protocol Tester - MCP JSON-RPC protocol compliance and tool functionality tests.

This module tests both Python and C implementations against the MCP protocol
specification and expected tool behaviors.
"""

import subprocess
import json
import os
import time
import select
import sys
from pathlib import Path
from typing import Dict, Tuple, Optional, List, Callable
from dataclasses import dataclass


def _get_extended_env() -> dict:
    """Get environment with extended PATH for uv and cargo binaries."""
    env = os.environ.copy()
    home = Path.home()
    extra_paths = [str(home / ".local" / "bin"), str(home / ".cargo" / "bin")]
    env["PATH"] = ":".join(extra_paths + [env.get("PATH", "")])
    return env


@dataclass
class TestContext:
    """Context for running tests against an implementation."""
    impl: str  # "python" or "c"
    eclass_dir: Path
    env_vars: dict
    debug: bool = False


class ServerProcess:
    """Manages a server subprocess for testing."""
    
    def __init__(self, ctx: TestContext):
        self.ctx = ctx
        self.proc: Optional[subprocess.Popen] = None
    
    def start(self) -> bool:
        """Start the server process. Returns True on success."""
        env = _get_extended_env()
        env.update(self.ctx.env_vars)
        
        if self.ctx.impl == "python":
            cmd = self._get_python_cmd()
            cwd = self.ctx.eclass_dir
        else:
            cmd = [str(self.ctx.eclass_dir / "c-replica" / "server")]
            cwd = self.ctx.eclass_dir / "c-replica"
        
        if self.ctx.debug:
            print(f"[DEBUG] Starting server: {' '.join(cmd)}")
            print(f"[DEBUG] Working dir: {cwd}")
        
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                env=env,
                bufsize=1
            )
            time.sleep(0.5)  # Allow server startup
            
            if self.proc.poll() is not None:
                stderr = self.proc.stderr.read() if self.proc.stderr else ""
                if self.ctx.debug:
                    print(f"[DEBUG] Server exited early: {stderr}")
                return False
            return True
        except Exception as e:
            if self.ctx.debug:
                print(f"[DEBUG] Failed to start server: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the server process."""
        if self.proc:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
    
    def send_request(self, request: dict) -> Optional[dict]:
        """
        Send JSON-RPC request and return response.
        
        Applies a 10-second timeout to prevent hangs. This timeout applies
        equally to both Python and C implementations for fair testing.
        """
        if not self.proc:
            return None
        
        # Timeout: 10 seconds - generous for legitimate operations on localhost,
        # but catches hangs. Applies equally to both Python and C implementations.
        TIMEOUT = 10.0
        
        try:
            req_str = json.dumps(request) + "\n"
            if self.ctx.debug:
                print(f"[DEBUG] SEND: {req_str.strip()}")
            
            self.proc.stdin.write(req_str)
            self.proc.stdin.flush()
            
            # Read with timeout (applies to both Python and C)
            if sys.platform != 'win32':
                # Unix: use select for timeout
                ready, _, _ = select.select([self.proc.stdout], [], [], TIMEOUT)
                if not ready:
                    if self.ctx.debug:
                        print(f"[DEBUG] TIMEOUT: No response after {TIMEOUT}s")
                    return None
                response_line = self.proc.stdout.readline()
            else:
                # Windows: readline blocks, timeout handled by test framework
                # Note: Windows doesn't support select on pipes easily
                response_line = self.proc.stdout.readline()
            
            if not response_line:
                return None
            
            if self.ctx.debug:
                print(f"[DEBUG] RECV: {response_line.strip()}")
            
            return json.loads(response_line.strip())
        except json.JSONDecodeError as e:
            if self.ctx.debug:
                print(f"[DEBUG] JSON decode error: {e}")
            return None
        except Exception as e:
            if self.ctx.debug:
                print(f"[DEBUG] Request error: {e}")
            return None
    
    def send_notification(self, notification: dict) -> None:
        """Send JSON-RPC notification (no response expected)."""
        if not self.proc:
            return
        try:
            notif_str = json.dumps(notification) + "\n"
            self.proc.stdin.write(notif_str)
            self.proc.stdin.flush()
            time.sleep(0.1)
        except Exception:
            pass
    
    def _get_python_cmd(self) -> List[str]:
        """Get command to run Python server."""
        try:
            subprocess.run(["uv", "--version"], capture_output=True, check=True, 
                         env=_get_extended_env())
            return ["uv", "run", "python", "-m", "src.eclass_mcp_server.server"]
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ["python", "-m", "src.eclass_mcp_server.server"]


class ProtocolTester:
    """Tests protocol compliance and tool functionality."""
    
    def __init__(self, eclass_dir: Path, env_vars: dict, debug: bool = False):
        self.eclass_dir = Path(eclass_dir).resolve()
        self.env_vars = env_vars
        self.debug = debug
    
    # -------------------------------------------------------------------------
    # Protocol Tests (P1, P2)
    # -------------------------------------------------------------------------
    
    def test_initialize(self, impl: str) -> Tuple[bool, str, str]:
        """P1: Test initialize response structure."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            response = server.send_request({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "grader", "version": "1.0.0"}
                }
            })
            
            if not response or "result" not in response:
                return False, "Invalid or missing response", json.dumps(response)
            
            result = response["result"]
            required = ["protocolVersion", "capabilities", "serverInfo"]
            missing = [k for k in required if k not in result]
            
            if missing:
                return False, f"Missing fields: {missing}", json.dumps(response)
            
            server_name = result.get("serverInfo", {}).get("name", "")
            if server_name != "eclass-mcp":
                return False, f"serverInfo.name should be 'eclass-mcp', got '{server_name}'", json.dumps(response)
            
            return True, "Initialize response structure correct", json.dumps(response)
        finally:
            server.stop()
    
    def test_tools_list(self, impl: str) -> Tuple[bool, str, str]:
        """P2: Test tools/list response structure."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            # Initialize first
            server.send_request({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                          "clientInfo": {"name": "grader", "version": "1.0.0"}}
            })
            server.send_notification({"jsonrpc": "2.0", "method": "notifications/initialized"})
            
            response = server.send_request({
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
            })
            
            if not response or "result" not in response:
                return False, "Invalid or missing response", json.dumps(response)
            
            tools = response["result"].get("tools", [])
            tool_names = {t.get("name") for t in tools}
            
            # Required baseline tools
            required = {"login", "logout", "get_courses", "authstatus"}
            missing = required - tool_names
            
            if missing:
                return False, f"Missing required tools: {missing}", json.dumps(response)
            
            has_announcements = "get_course_announcements" in tool_names
            return True, f"Found {len(tools)} tools (announcements: {has_announcements})", json.dumps(response)
        finally:
            server.stop()
    
    # -------------------------------------------------------------------------
    # Login Tests (L1, L2, L3)
    # -------------------------------------------------------------------------
    
    def test_login_success(self, impl: str) -> Tuple[bool, str, str]:
        """L1: Test successful login."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            response = self._call_tool(server, "login", {})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            if "Login successful" in text and "testuser" in text:
                return True, f"Login successful: {text[:100]}", text
            
            return False, f"Unexpected response: {text[:200]}", text
        finally:
            server.stop()
    
    def test_login_already_logged_in(self, impl: str) -> Tuple[bool, str, str]:
        """L2: Test already logged in handling."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            # First login
            self._call_tool(server, "login", {})
            # Second login
            response = self._call_tool(server, "login", {})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            if "Already logged in" in text:
                return True, f"Already logged in detected: {text[:100]}", text
            
            return False, f"Expected 'Already logged in', got: {text[:200]}", text
        finally:
            server.stop()
    
    def test_login_missing_credentials(self, impl: str) -> Tuple[bool, str, str]:
        """L3: Test missing credentials error."""
        # Use empty credentials
        env_no_creds = dict(self.env_vars)
        env_no_creds["ECLASS_USERNAME"] = ""
        env_no_creds["ECLASS_PASSWORD"] = ""
        
        ctx = TestContext(impl, self.eclass_dir, env_no_creds, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            response = self._call_tool(server, "login", {})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            # Check for credentials error message
            if "Error" in text and ("must be provided" in text.lower() or 
                                    "credentials" in text.lower() or 
                                    "username" in text.lower()):
                return True, f"Missing credentials error: {text[:100]}", text
            
            return False, f"Expected credentials error, got: {text[:200]}", text
        finally:
            server.stop()
    
    # -------------------------------------------------------------------------
    # Logout Tests (O1, O2)
    # -------------------------------------------------------------------------
    
    def test_logout_success(self, impl: str) -> Tuple[bool, str, str]:
        """O1: Test successful logout."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            self._call_tool(server, "login", {})
            response = self._call_tool(server, "logout", {})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            if "Successfully logged out" in text and "testuser" in text:
                return True, f"Logout successful: {text[:100]}", text
            
            return False, f"Expected logout success, got: {text[:200]}", text
        finally:
            server.stop()
    
    def test_logout_not_logged_in(self, impl: str) -> Tuple[bool, str, str]:
        """O2: Test logout when not logged in."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            response = self._call_tool(server, "logout", {})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            if "Not logged in" in text or "nothing to do" in text.lower():
                return True, f"Not logged in response: {text[:100]}", text
            
            return False, f"Expected 'Not logged in', got: {text[:200]}", text
        finally:
            server.stop()
    
    # -------------------------------------------------------------------------
    # Courses Tests (C1, C2)
    # -------------------------------------------------------------------------
    
    def test_courses_logged_in(self, impl: str) -> Tuple[bool, str, str]:
        """C1: Test get courses when logged in."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            self._call_tool(server, "login", {})
            response = self._call_tool(server, "get_courses", {})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            if "Found" in text and "course" in text.lower():
                return True, f"Courses found: {text[:150]}", text
            
            return False, f"Expected courses list, got: {text[:200]}", text
        finally:
            server.stop()
    
    def test_courses_not_logged_in(self, impl: str) -> Tuple[bool, str, str]:
        """C2: Test get courses when not logged in."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            response = self._call_tool(server, "get_courses", {})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            if "Error" in text and ("Not logged in" in text or "log in" in text.lower()):
                return True, f"Not logged in error: {text[:100]}", text
            
            return False, f"Expected not logged in error, got: {text[:200]}", text
        finally:
            server.stop()
    
    # -------------------------------------------------------------------------
    # Authstatus Tests (A1)
    # -------------------------------------------------------------------------
    
    def test_authstatus_not_logged_in(self, impl: str) -> Tuple[bool, str, str]:
        """A1: Test authstatus when not logged in."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            response = self._call_tool(server, "authstatus", {})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            if "Status:" in text and "Not logged in" in text:
                return True, f"Not logged in status: {text[:100]}", text
            
            return False, f"Expected 'Not logged in' status, got: {text[:200]}", text
        finally:
            server.stop()
    
    # -------------------------------------------------------------------------
    # Announcements Tests (AN1-AN5)
    # -------------------------------------------------------------------------
    
    def test_announcements_not_logged_in(self, impl: str) -> Tuple[bool, str, str]:
        """AN1: Test announcements when not logged in (exact error string)."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            
            # Check if tool exists
            if not self._tool_exists(server, "get_course_announcements"):
                return False, "get_course_announcements tool not implemented", "Tool not found in tools/list"
            
            response = self._call_tool(server, "get_course_announcements", 
                                       {"course_url": "http://localhost/courses/TEST101/"})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            # Must be exact match per spec
            if text == "Error: Not logged in.":
                return True, "Exact error string matched", text
            
            return False, f"Expected exact 'Error: Not logged in.', got: '{text}'", text
        finally:
            server.stop()
    
    def test_announcements_invalid_url(self, impl: str) -> Tuple[bool, str, str]:
        """AN2: Test announcements with invalid course URL (exact error string)."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            
            if not self._tool_exists(server, "get_course_announcements"):
                return False, "get_course_announcements tool not implemented", "Tool not found"
            
            self._call_tool(server, "login", {})
            response = self._call_tool(server, "get_course_announcements", 
                                       {"course_url": "invalid-url"})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            # Must be exact match per spec
            if text == "Error: Could not extract course code.":
                return True, "Exact error string matched", text
            
            return False, f"Expected exact 'Error: Could not extract course code.', got: '{text}'", text
        finally:
            server.stop()
    
    def test_announcements_none_found(self, impl: str) -> Tuple[bool, str, str]:
        """AN3: Test announcements with no results (exact string)."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            
            if not self._tool_exists(server, "get_course_announcements"):
                return False, "get_course_announcements tool not implemented", "Tool not found"
            
            self._call_tool(server, "login", {})
            # MATH301 has no announcements in test data
            response = self._call_tool(server, "get_course_announcements", 
                                       {"course_url": "http://localhost/courses/MATH301/"})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            # Must be exact match per spec
            if text == "No announcements found.":
                return True, "Exact string matched", text
            
            return False, f"Expected exact 'No announcements found.', got: '{text}'", text
        finally:
            server.stop()
    
    def test_announcements_default_days(self, impl: str) -> Tuple[bool, str, str]:
        """AN4: Test announcements with default days_back (30 days)."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            
            if not self._tool_exists(server, "get_course_announcements"):
                return False, "get_course_announcements tool not implemented", "Tool not found"
            
            self._call_tool(server, "login", {})
            # TEST101 has announcements in test data
            response = self._call_tool(server, "get_course_announcements", 
                                       {"course_url": "http://localhost/courses/TEST101/"})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            # Check for expected format
            if "Found" in text and "announcement" in text.lower():
                # Verify format: numbered items, Date:, Content:
                if "1." in text and "Date:" in text:
                    return True, f"Correct format: {text[:150]}", text
                return False, f"Missing format elements (1., Date:): {text[:200]}", text
            
            return False, f"Expected announcements, got: '{text[:200]}'", text
        finally:
            server.stop()
    
    def test_announcements_custom_days(self, impl: str) -> Tuple[bool, str, str]:
        """AN5: Test announcements with custom days_back parameter."""
        ctx = TestContext(impl, self.eclass_dir, self.env_vars, self.debug)
        server = ServerProcess(ctx)
        
        if not server.start():
            return False, "Could not start server", "Server failed to start"
        
        try:
            self._initialize_server(server)
            
            if not self._tool_exists(server, "get_course_announcements"):
                return False, "get_course_announcements tool not implemented", "Tool not found"
            
            self._call_tool(server, "login", {})
            # days_back=7 should filter to recent announcements only
            response = self._call_tool(server, "get_course_announcements", 
                                       {"course_url": "http://localhost/courses/TEST101/", 
                                        "days_back": 7})
            text = self._extract_text(response)
            
            if not text:
                return False, "Empty or invalid response", json.dumps(response)
            
            # Either we get filtered announcements or "No announcements found."
            if "Found" in text and "announcement" in text.lower():
                return True, f"Filtered results: {text[:150]}", text
            elif text == "No announcements found.":
                return True, "days_back filter working (no recent announcements)", text
            
            return False, f"Unexpected response: '{text[:200]}'", text
        finally:
            server.stop()
    
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    
    def _initialize_server(self, server: ServerProcess) -> None:
        """Send initialize and initialized notification to server."""
        server.send_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                      "clientInfo": {"name": "grader", "version": "1.0.0"}}
        })
        server.send_notification({"jsonrpc": "2.0", "method": "notifications/initialized"})
    
    def _call_tool(self, server: ServerProcess, tool: str, args: dict) -> Optional[dict]:
        """Call a tool and return the response."""
        # Add dummy random_string parameter for tools that require it (baseline tools)
        if tool in ("login", "logout", "get_courses", "authstatus") and "random_string" not in args:
            args = {**args, "random_string": "test"}
        return server.send_request({
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args}
        })
    
    def _extract_text(self, response: Optional[dict]) -> str:
        """Extract text content from tool response."""
        if not response or "result" not in response:
            return ""
        content = response["result"].get("content", [])
        if content and len(content) > 0:
            return content[0].get("text", "")
        return ""
    
    def _tool_exists(self, server: ServerProcess, tool_name: str) -> bool:
        """Check if a tool exists in tools/list."""
        response = server.send_request({
            "jsonrpc": "2.0", "id": 98, "method": "tools/list", "params": {}
        })
        if not response or "result" not in response:
            return False
        tools = response["result"].get("tools", [])
        return any(t.get("name") == tool_name for t in tools)
    
    # -------------------------------------------------------------------------
    # Batch Test Runners
    # -------------------------------------------------------------------------
    
    def run_python_baseline_tests(self) -> Dict[str, Tuple[bool, str, str]]:
        """Run all Python baseline tests. Returns {test_id: (passed, message, full_output)}."""
        return {
            "P1": self.test_initialize("python"),
            "P2": self.test_tools_list("python"),
            "L1": self.test_login_success("python"),
            "L2": self.test_login_already_logged_in("python"),
            "L3": self.test_login_missing_credentials("python"),
            "O1": self.test_logout_success("python"),
            "O2": self.test_logout_not_logged_in("python"),
            "C1": self.test_courses_logged_in("python"),
            "C2": self.test_courses_not_logged_in("python"),
            "A1": self.test_authstatus_not_logged_in("python"),
        }
    
    def run_python_feature_tests(self) -> Dict[str, Tuple[bool, str, str]]:
        """Run all Python feature tests. Returns {test_id: (passed, message, full_output)}."""
        return {
            "AN1": self.test_announcements_not_logged_in("python"),
            "AN2": self.test_announcements_invalid_url("python"),
            "AN3": self.test_announcements_none_found("python"),
            "AN4": self.test_announcements_default_days("python"),
            "AN5": self.test_announcements_custom_days("python"),
        }
    
    def run_c_baseline_tests(self) -> Dict[str, Tuple[bool, str, str]]:
        """Run all C baseline tests. Returns {test_id: (passed, message, full_output)}."""
        return {
            "P1_c": self.test_initialize("c"),
            "P2_c": self.test_tools_list("c"),
            "L1_c": self.test_login_success("c"),
            "L2_c": self.test_login_already_logged_in("c"),
            "L3_c": self.test_login_missing_credentials("c"),
            "O1_c": self.test_logout_success("c"),
            "O2_c": self.test_logout_not_logged_in("c"),
            "C1_c": self.test_courses_logged_in("c"),
            "C2_c": self.test_courses_not_logged_in("c"),
            "A1_c": self.test_authstatus_not_logged_in("c"),
        }
    
    def run_c_feature_tests(self) -> Dict[str, Tuple[bool, str, str]]:
        """Run all C feature tests. Returns {test_id: (passed, message, full_output)}."""
        return {
            "AN1_c": self.test_announcements_not_logged_in("c"),
            "AN2_c": self.test_announcements_invalid_url("c"),
            "AN3_c": self.test_announcements_none_found("c"),
            "AN4_c": self.test_announcements_default_days("c"),
            "AN5_c": self.test_announcements_custom_days("c"),
        }
