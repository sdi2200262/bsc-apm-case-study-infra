#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Generate seed.json from seed.yaml for the php seeder to consume.

The php seeder runs inside the eclass container and has no YAML
parser available; this generator emits an equivalent JSON file so
the runtime side can use ``json_decode``. Greek strings stay
readable by writing UTF-8 with non-ASCII passthrough. The output is
deterministic given identical input.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
INPUT_PATH = HERE / "seed.yaml"
OUTPUT_PATH = HERE / "seed.json"


def main() -> None:
    """Read seed.yaml, write seed.json next to it.

    Raises:
        SystemExit: If ``seed.yaml`` is not present next to this script.
    """
    if not INPUT_PATH.is_file():
        print(f"seed input not found: {INPUT_PATH}", file=sys.stderr)
        sys.exit(1)
    data = yaml.safe_load(INPUT_PATH.read_text(encoding="utf-8"))
    OUTPUT_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
