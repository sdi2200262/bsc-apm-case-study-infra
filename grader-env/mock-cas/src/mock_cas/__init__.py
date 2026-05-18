#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Mock CAS authentication service for the BSc APM Case Study testing environment.

The package implements a small CAS / SAML 1.1 server that satisfies the
surface the eclass-mcp-server reference client expects against the
University of Athens deployment. The service identifies itself as a mock
to inspecting agents through the Server header, page copy, and inline XML
comments inside its CAS and SAML responses.
"""

from __future__ import annotations
