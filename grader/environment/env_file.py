# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Single-source ``.env`` reader shared by provisioning and the runner.

Both config surfaces derive from the grading environment's own
``<mock_root>/.env``: provisioning copies it verbatim, env-var
injection parses it, so neither is hand-maintained. A leaf module
(no intra-package imports) so ``provision`` and ``protocol.runner``
import ``parse_env_file`` without a cycle.
"""

from __future__ import annotations

from pathlib import Path


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` ``.env`` file into a mapping (file order).

    Blank lines, ``#`` comments, and lines with no ``=`` are
    skipped; a malformed line in this controlled input surfaces
    downstream as a failed login, not a parser exception here.

    Args:
        path: Path to the ``.env`` file to read.

    Returns:
        Mapping of configuration keys to values.

    Raises:
        FileNotFoundError: When ``path`` does not exist (the
            provisioning source check runs first; a raise here means
            it was bypassed).
    """
    pairs: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs
