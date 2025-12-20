#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Build Tester - Verifies build/compilation for Python and C implementations.
"""

import subprocess
import os
from pathlib import Path
from typing import Tuple


def _get_extended_env() -> dict:
    """Get environment with extended PATH for uv and cargo binaries."""
    env = os.environ.copy()
    home = Path.home()
    extra_paths = [str(home / ".local" / "bin"), str(home / ".cargo" / "bin")]
    env["PATH"] = ":".join(extra_paths + [env.get("PATH", "")])
    return env


class BuildTester:
    """Tests build/compilation for Python and C implementations."""
    
    def __init__(self, eclass_dir: Path):
        self.eclass_dir = Path(eclass_dir).resolve()
        self.c_replica_dir = self.eclass_dir / "c-replica"
    
    def test_python_build(self) -> Tuple[bool, str, str]:
        """
        Test Python dependency installation with uv sync, falling back to pip.
        
        Returns:
            (success, message, full_output)
        """
        pyproject = self.eclass_dir / "pyproject.toml"
        if not pyproject.exists():
            return False, "pyproject.toml not found", "pyproject.toml not found in eclass-mcp-server directory"
        
        env = _get_extended_env()
        
        # Try uv sync first
        try:
            result = subprocess.run(
                ["uv", "sync"],
                cwd=self.eclass_dir,
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )
            if result.returncode == 0:
                return True, "uv sync completed successfully", result.stdout or "uv sync completed"
            return False, f"uv sync failed: {result.stderr[:300]}", result.stderr
            
        except FileNotFoundError:
            # Fall back to pip
            try:
                result = subprocess.run(
                    ["pip", "install", "-e", "."],
                    cwd=self.eclass_dir,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env
                )
                if result.returncode == 0:
                    return True, "pip install -e . completed (uv not found)", result.stdout or "pip install completed"
                return False, f"pip install failed: {result.stderr[:300]}", result.stderr
            except FileNotFoundError:
                return False, "Neither uv nor pip found", "Neither uv nor pip found in PATH"
            except subprocess.TimeoutExpired:
                return False, "pip install timed out (120s)", "pip install -e . timed out after 120 seconds"
                
        except subprocess.TimeoutExpired:
            return False, "uv sync timed out (120s)", "uv sync timed out after 120 seconds"
        except Exception as e:
            return False, f"Build error: {e}", str(e)
    
    def test_c_build(self) -> Tuple[bool, str, str]:
        """
        Test C compilation with make c-server.
        
        Returns:
            (success, message, full_output)
        """
        if not self.c_replica_dir.exists():
            return False, "c-replica/ directory not found", "c-replica/ directory not found in eclass-mcp-server"
        
        makefile = self.c_replica_dir / "Makefile"
        if not makefile.exists():
            return False, "Makefile not found in c-replica/", "Makefile not found in c-replica/ directory"
        
        # Clean previous builds
        subprocess.run(["make", "clean"], cwd=self.c_replica_dir, 
                      capture_output=True, timeout=30)
        
        try:
            result = subprocess.run(
                ["make", "c-server"],
                cwd=self.c_replica_dir,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode != 0:
                err = result.stderr or result.stdout
                if "libxml" in err:
                    return False, "make c-server failed: missing libxml2-dev", err
                if "curl" in err:
                    return False, "make c-server failed: missing libcurl-dev", err
                return False, f"make c-server failed: {err[:300]}", err
            
            # Verify binary exists
            server_binary = self.c_replica_dir / "server"
            if not server_binary.exists():
                return False, "Compilation succeeded but 'server' binary not found", "make c-server completed but server binary was not created"
            
            if not os.access(server_binary, os.X_OK):
                return False, "'server' binary exists but is not executable", "server binary exists but lacks execute permission"
            
            return True, "make c-server completed, server binary created", result.stdout or "Compilation successful"
            
        except subprocess.TimeoutExpired:
            return False, "make c-server timed out (120s)", "make c-server timed out after 120 seconds"
        except FileNotFoundError:
            return False, "make command not found", "make command not found in PATH"
        except Exception as e:
            return False, f"C build error: {e}", str(e)
