#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Memory Tester - Runs Valgrind memory leak detection on C implementation.

Per the specification, the C replica must be memory-safe with zero leaks:
- "definitely lost: 0 bytes, indirectly lost: 0 bytes"
"""

import subprocess
import os
import re
from pathlib import Path
from typing import Tuple


class MemoryTester:
    """Tests memory safety of C implementation using Valgrind."""
    
    def __init__(self, eclass_dir: Path, env_vars: dict = None):
        """
        Initialize MemoryTester.
        
        Args:
            eclass_dir: Path to eclass-mcp-server directory
            env_vars: Environment variables for server (from MockServerManager.get_env())
        """
        self.eclass_dir = Path(eclass_dir).resolve()
        self.c_replica_dir = self.eclass_dir / "c-replica"
        self.server_binary = self.c_replica_dir / "server"
        self.env_vars = env_vars or {}
    
    def test_valgrind(self) -> Tuple[bool, str, str]:
        """
        Run Valgrind on the C server with a full session sequence.
        
        Tests: initialize -> login -> get_courses -> authstatus -> logout
        
        Returns:
            (success, message, full_output)
        """
        if not self.server_binary.exists():
            return False, "Server binary not found", "Server binary not found at c-replica/server"
        
        # Check Valgrind availability
        try:
            subprocess.run(["valgrind", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False, "Valgrind not available", "Valgrind not installed or not in PATH"
        
        # JSON-RPC sequence for testing
        sequence = self._build_test_sequence()
        
        try:
            result = subprocess.run(
                [
                    "valgrind",
                    "--leak-check=full",
                    "--show-leak-kinds=all",
                    "--track-origins=yes",
                    "--error-exitcode=1",
                    str(self.server_binary)
                ],
                input=sequence,
                capture_output=True,
                text=True,
                timeout=60,
                env=self._get_env(),
                cwd=self.c_replica_dir
            )
            
            # Parse Valgrind output
            output = result.stderr
            definitely_lost = self._parse_leak(output, "definitely lost")
            indirectly_lost = self._parse_leak(output, "indirectly lost")
            
            if definitely_lost == 0 and indirectly_lost == 0:
                return True, "Memory clean: 0 bytes definitely lost, 0 bytes indirectly lost", output
            
            return False, f"Memory leaks: {definitely_lost} bytes definitely lost, {indirectly_lost} bytes indirectly lost", output
            
        except subprocess.TimeoutExpired:
            return False, "Valgrind timed out (60s)", "Valgrind timed out after 60 seconds"
        except Exception as e:
            return False, f"Valgrind error: {e}", str(e)
    
    def _build_test_sequence(self) -> str:
        """Build JSON-RPC test sequence for memory testing."""
        messages = [
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"grader","version":"1.0.0"}}}',
            '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}',
            '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"login","arguments":{"random_string":"test"}}}',
            '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_courses","arguments":{"random_string":"test"}}}',
            '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"authstatus","arguments":{"random_string":"test"}}}',
            '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"logout","arguments":{"random_string":"test"}}}',
        ]
        return "\n".join(messages) + "\n"
    
    def _get_env(self) -> dict:
        """Get environment variables for testing."""
        env = os.environ.copy()
        # Apply provided environment variables (from MockServerManager)
        env.update(self.env_vars)
        return env
    
    def _parse_leak(self, output: str, leak_type: str) -> int:
        """Parse leak amount from Valgrind output."""
        pattern = rf"{leak_type}:\s*([\d,]+)\s*bytes"
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
        return 0
