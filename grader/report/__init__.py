# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Report layer: serialises the results artifact and renders the run view; computes nothing.

This layer wraps the scorer's aggregated output into the JSON results
artefact and renders the terminal grading summary; it derives no score
of its own. It imports ``scoring`` and the root leaves and reads
``protocol.matching`` only to phrase a lenient-acceptance notice;
nothing in ``scoring`` or ``protocol`` imports from it.

Submodules:

- ``build``: resolve the report path and write the JSON results artefact.
- ``render``: the console grading summary, with optional per-row detail.
- ``notices``: review and warning ``Notice`` collection.
"""

from __future__ import annotations
