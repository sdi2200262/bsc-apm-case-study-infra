# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Protocol-test subpackage.

Submodules:

- ``runner``: server-spawn helpers, JSON-RPC framing, seed-data
  constants the assertions depend on.
- ``baseline_tests``: ten baseline assertion functions parameterised
  by implementation (P1, P2, L1-L3, O1-O2, C1-C2, A1).
- ``feature_tests``: twelve feature assertion functions parameterised
  by implementation (AN1-AN6, GAN1-GAN6).
- ``python_baseline`` / ``python_feature`` / ``c_baseline`` /
  ``c_feature``: thin aggregators that call the assertions with the
  matching ``impl`` and return the per-test-id result mapping the
  grader and downstream consumers expect.
"""
