#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Eclass Manager - OpenEclass availability checker.

Verifies that OpenEclass is running and accessible. Does NOT manage Docker
containers - they must be started manually before running the grader.
"""

import subprocess
import requests
from urllib.parse import urljoin


class EclassManager:
    """Checks OpenEclass availability for testing."""

    def __init__(self, base_url: str = "http://localhost"):
        self.base_url = base_url

    def start(self) -> bool:
        """
        Check if OpenEclass is running.
        
        Does NOT start containers - only verifies service is available.
        
        Returns:
            True if OpenEclass is accessible
        """
        print("  Checking OpenEclass...")
        
        if not self._is_accessible():
            print("  ERROR: OpenEclass not accessible at http://localhost")
            print("  Start with: docker start grader_db_1 grader_eclass_1")
            return False
        
        print("  OK: OpenEclass is accessible")
        
        # Clear cache
        self._clear_cache()
        
        # Check CAS configuration
        if self._is_cas_enabled():
            print("  OK: CAS authentication detected")
        else:
            print("  WARN: CAS authentication not detected on login page")
        
        return True

    def stop(self) -> None:
        """No-op. Containers are managed externally."""
        pass

    def _is_accessible(self) -> bool:
        """Check if OpenEclass is responding."""
        try:
            response = requests.get(self.base_url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def _is_cas_enabled(self) -> bool:
        """Check if CAS is enabled on login page."""
        try:
            url = urljoin(self.base_url + "/", "main/login_form.php")
            response = requests.get(url, timeout=5)
            if response.status_code != 200:
                return False
            return "modules/auth/cas.php" in response.text
        except Exception:
            return False

    def _clear_cache(self) -> bool:
        """Clear OpenEclass config cache."""
        try:
            subprocess.run(
                ["docker", "exec", "grader_eclass_1", "find", "/tmp", 
                 "-name", "*cache*", "-delete"],
                capture_output=True,
                timeout=10
            )
            return True
        except Exception:
            return False
