#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Per-run seed-instant calibration.

The grader's openeclass instance anchors every announcement date to
``NOW() - days_ago days`` at seed-apply time. The maximum stored
announcement date is the seed-apply instant (the day-0 row); the
expected date strings are constructed from it. The value is read as
the literal stored ``DATETIME`` and parsed without a timezone
conversion, because the server renders that same stored wall-clock;
routing through a Unix epoch would shift it by any offset between
the database and the host.

This module owns the single call that reads the seed instant from the
grading environment's MariaDB container. The instant is read once per
aggregator run and threaded into every row that constructs an
announcement date string.
"""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

from ..errors import GraderError

CALIBRATION_TIMEOUT_SECONDS = 60

_DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")


class CalibrationError(GraderError):
    """Raised when the seed instant cannot be read from the database.

    The message carries one actionable line naming the failure cause:
    the docker-exec command failed, the query returned no row, or the
    output was not a parseable ``DATETIME``.
    """


def seed_instant(mock_root: Path) -> datetime.datetime:
    """Return the per-run seed-apply instant from the grading environment.

    Queries the MariaDB container for the maximum announcement date
    and parses the stored ``DATETIME`` as a naive datetime, with no
    timezone conversion: the server renders that same wall-clock, so
    a byte-exact date match requires the unconverted value. All
    announcement dates in the grading environment share its time
    component; only the day shifts per ``days_ago``.

    Args:
        mock_root: Resolved path to the grading environment install
            whose ``compose.yaml`` defines the ``db`` service.

    Returns:
        Naive ``datetime.datetime`` at the seed-apply instant.

    Raises:
        CalibrationError: When the docker-exec command fails, the
            query returns no row, or the output is not a parseable
            ``DATETIME``.
    """
    compose_file = Path(mock_root).resolve() / "compose.yaml"
    sql = "SELECT MAX(`date`) FROM announcement;"
    cmd = [
        "docker", "compose",
        "-f", str(compose_file),
        "exec", "-T", "db",
        "mariadb", "-uroot", "-psecret", "-N", "-B",
        "-e", sql,
        "eclass",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CALIBRATION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise CalibrationError(  # noqa: B904 (re-raised as a clean domain error)
            "docker not on PATH; cannot calibrate the seed instant"
        )
    except subprocess.TimeoutExpired:
        raise CalibrationError(  # noqa: B904 (re-raised as a clean domain error)
            f"docker compose exec timed out after {CALIBRATION_TIMEOUT_SECONDS}s "
            "while reading the seed instant"
        )
    if result.returncode < 0:
        combined = (result.stderr + result.stdout).strip()
        raise CalibrationError(
            f"docker compose exec killed by signal {-result.returncode} "
            f"while reading the seed instant: {combined[:200]}"
        )
    if result.returncode != 0:
        combined = (result.stderr + result.stdout).strip()
        raise CalibrationError(
            f"docker compose exec returned exit {result.returncode} "
            f"while reading the seed instant: {combined[:200]}"
        )
    raw = (result.stdout or "").strip()
    if not raw or raw == "NULL":
        raise CalibrationError(
            "the seed-instant query returned no row; the announcement "
            "table may be empty or the seed has not been applied"
        )
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise CalibrationError(
        f"seed-instant query returned an unparseable DATETIME: {raw[:80]!r}"
    )
