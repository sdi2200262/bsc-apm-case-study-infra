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
    """
    Get environment with extended PATH for uv and cargo binaries.
    
    Returns:
        Dictionary with modified PATH environment variable including
        ~/.local/bin and ~/.cargo/bin for uv and cargo tool access.
    """
    env = os.environ.copy()
    home = Path.home()
    extra_paths = [str(home / ".local" / "bin"), str(home / ".cargo" / "bin")]
    env["PATH"] = ":".join(extra_paths + [env.get("PATH", "")])
    return env


class BuildTester:
    """Tests build/compilation for Python and C implementations."""
    
    def __init__(self, eclass_dir: Path):
        """
        Initialize build tester for a repository.
        
        Args:
            eclass_dir: Path to the eclass-mcp-server repository directory.
        """
        self.eclass_dir = Path(eclass_dir).resolve()
        self.c_replica_dir = self.eclass_dir / "c-replica"
    
    def test_python_build(self) -> Tuple[bool, str, str]:
        """
        Test Python dependency installation with uv sync, falling back to pip.
        
        Returns:
            Tuple of (success: bool, message: str, full_output: str).
            success indicates if build succeeded, message is a brief summary,
            full_output contains complete command output for debugging.
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
    
    def _check_library_versions(self) -> Tuple[bool, str]:
        """
        Verify that required C library versions meet minimum requirements.
        
        This is a warning check only - builds are not failed based on versions alone.
        The actual build result determines success/failure (black-box testing principle).
        
        Returns:
            Tuple of (success: bool, message: str).
            success indicates if versions meet requirements, message describes the issue if not.
        """
        # Minimum required versions (as per specification)
        MIN_LIBCURL_VERSION = "7.81.0"
        MIN_LIBXML2_VERSION = "2.9.13"
        
        try:
            # Check libcurl version
            result = subprocess.run(
                ["pkg-config", "--modversion", "libcurl"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return False, "libcurl not found via pkg-config"
            
            curl_version = result.stdout.strip()
            
            # Check libxml2 version
            result = subprocess.run(
                ["pkg-config", "--modversion", "libxml-2.0"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return False, "libxml2 not found via pkg-config"
            
            xml2_version = result.stdout.strip()
            
            # Compare versions (simple string comparison works for semantic versions)
            def version_compare(v1: str, v2: str) -> int:
                """Compare two version strings. Returns -1 if v1 < v2, 0 if equal, 1 if v1 > v2."""
                v1_parts = [int(x) for x in v1.split('.')]
                v2_parts = [int(x) for x in v2.split('.')]
                # Pad shorter version with zeros
                max_len = max(len(v1_parts), len(v2_parts))
                v1_parts.extend([0] * (max_len - len(v1_parts)))
                v2_parts.extend([0] * (max_len - len(v2_parts)))
                for a, b in zip(v1_parts, v2_parts):
                    if a < b:
                        return -1
                    elif a > b:
                        return 1
                return 0
            
            # Check if versions meet minimum requirements
            if version_compare(curl_version, MIN_LIBCURL_VERSION) < 0:
                return False, f"libcurl version {curl_version} is below minimum required {MIN_LIBCURL_VERSION}"
            
            if version_compare(xml2_version, MIN_LIBXML2_VERSION) < 0:
                return False, f"libxml2 version {xml2_version} is below minimum required {MIN_LIBXML2_VERSION}"
            
            return True, f"libcurl {curl_version} (>= {MIN_LIBCURL_VERSION}), libxml2 {xml2_version} (>= {MIN_LIBXML2_VERSION})"
            
        except FileNotFoundError:
            return False, "pkg-config not found - cannot verify library versions"
        except subprocess.TimeoutExpired:
            return False, "pkg-config version check timed out"
        except Exception as e:
            return False, f"Error checking library versions: {e}"
    
    def test_c_build(self) -> Tuple[bool, str, str]:
        """
        Test C compilation with make c-server.
        
        Returns:
            Tuple of (success: bool, message: str, full_output: str).
            success indicates if compilation succeeded, message is a brief summary,
            full_output contains complete command output for debugging.
        """
        if not self.c_replica_dir.exists():
            return False, "c-replica/ directory not found", "c-replica/ directory not found in eclass-mcp-server"
        
        makefile = self.c_replica_dir / "Makefile"
        if not makefile.exists():
            return False, "Makefile not found in c-replica/", "Makefile not found in c-replica/ directory"
        
        # Check library versions (warning only - don't fail unless build actually fails)
        version_ok, version_msg = self._check_library_versions()
        version_warning = ""
        if not version_ok:
            version_warning = f"WARNING: {version_msg}. Attempting build anyway..."
        
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
                # If build failed and we had a version warning, include it in the error
                if not version_ok:
                    err = f"{version_warning}\n{err}"
                if "libxml" in err:
                    return False, "make c-server failed: missing libxml2-dev", err
                if "curl" in err:
                    return False, "make c-server failed: missing libcurl-dev", err
                return False, f"make c-server failed: {err[:300]}", err
            
            # Build succeeded - if we had a version warning, include it but don't fail
            if not version_ok:
                return True, f"make c-server completed (with version warning: {version_msg})", f"{version_warning}\n{result.stdout or 'Compilation successful'}"
            
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
