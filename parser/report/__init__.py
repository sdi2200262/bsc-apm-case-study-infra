# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Report layer: serialises artifacts and renders human views; computes nothing.

This layer assembles the canonical metrics artifact from the data and
metrics layers, formats leaf values, and renders the terminal summary
modes. It imports ``data`` and ``metrics`` and the root leaves; no value
in this layer is derived from the transcript here, only assembled.

Submodules:

- ``build``: assemble the scope-nested metrics artifact.
- ``leaves``: value formatting for the artifact leaves.
- ``render``: the ``--inspect`` / ``--economic`` / ``--process`` views.
- ``notices``: session-attention ``Notice`` collection and rendering.
"""
