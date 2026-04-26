#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Data-processing pipeline for participant submissions.

The pipeline is invoked stage-by-stage as ``python -m pipeline.<stage>``;
no external caller imports from this module. ``__init__`` is here so
that ``pipeline`` is a proper Python package and the intra-package
relative imports (``from .errors import ...``,
``from .submissions import ...``) resolve uniformly.
"""

from __future__ import annotations
