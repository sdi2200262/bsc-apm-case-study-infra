#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Seed-data loader for grader assertions.

The testing environment's seed values are the ground truth every
implementation-tier assertion checks against: which courses are
enrolled, which announcements each course carries, which admin
announcements are posted, and at what relative ages. The grader
ships a pinned snapshot of the env package's ``seed/seed.yaml`` at
``grader/seed.yaml``; this module loads that file at import time
and exposes the values plus a few derived helpers.

Boundary semantics: ``days_back=N`` is inclusive against a
calendar-based cutoff at midnight of ``today - N days``. An
announcement at ``days_ago=K`` is in scope iff ``K <= N``.

The general-announcement endpoint additionally enforces a hardcoded
30-day backend floor; the helpers here clamp the window to 30 so a
caller asking for ``days_back=60`` on the general side still sees
only the announcements within 30.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_SEED_FILENAME = "seed.yaml"
GENERAL_BACKEND_FLOOR_DAYS = 30


class SeedError(Exception):
    """Raised when ``seed.yaml`` is missing, malformed, or incomplete."""


@dataclass(frozen=True)
class Announcement:
    """One seeded announcement, course or admin.

    Attributes:
        course_code: Course code the announcement belongs to, or
            ``None`` for an admin (system) announcement.
        days_ago: Age of the announcement in whole days. Matches
            the seed YAML's ``days_ago`` field.
        title: Title text as seeded.
        body: Body text as seeded; the grader's verbatim-body
            assertions check for this string in the response.
    """

    course_code: str | None
    days_ago: int
    title: str
    body: str


@dataclass(frozen=True)
class SeedData:
    """Parsed contents of ``seed.yaml``.

    Attributes:
        username: CAS / openeclass login name for the seeded user.
        password: CAS password for the seeded user.
        enrolled_course_codes: Course codes the seeded user is
            enrolled in, in the order they appear in the YAML.
        course_announcements: Mapping of course code to the
            announcements seeded for that course, ordered by
            ``days_ago`` ascending.
        admin_announcements: Admin (system) announcements ordered
            by ``days_ago`` ascending.
    """

    username: str
    password: str
    enrolled_course_codes: tuple[str, ...]
    course_announcements: dict[str, tuple[Announcement, ...]]
    admin_announcements: tuple[Announcement, ...]


def load_seed(path: Path | None = None) -> SeedData:
    """Load the seed YAML and return a :class:`SeedData`.

    Args:
        path: Optional path to a seed file. Defaults to
            ``seed.yaml`` next to the ``grader`` package root.

    Returns:
        Parsed seed data.

    Raises:
        SeedError: When the file is missing, cannot be parsed, or
            does not carry the required keys.
    """
    seed_path = path or _default_seed_path()
    if not seed_path.is_file():
        raise SeedError(f"seed file not found: {seed_path}")
    try:
        raw = yaml.safe_load(seed_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise SeedError(f"seed file malformed: {error}") from error
    if not isinstance(raw, dict):
        raise SeedError("seed file root must be a mapping")
    return _build_seed_data(raw)


def course_announcements_in_window(
    seed: SeedData, course_code: str, days_back: int
) -> tuple[Announcement, ...]:
    """Return the announcements visible for one course at ``days_back``.

    The per-course endpoint applies no backend floor, so the helper
    is a straight inclusive filter on ``days_ago <= days_back``.

    Args:
        seed: Loaded seed data.
        course_code: Course to filter on.
        days_back: Inclusive upper bound on ``days_ago``.

    Returns:
        Tuple of announcements in scope, ordered by ``days_ago``
        ascending. Empty when the course has no seed entries or
        every seed entry is older than the window.
    """
    announcements = seed.course_announcements.get(course_code, ())
    return tuple(a for a in announcements if a.days_ago <= days_back)


def general_announcements_in_window(
    seed: SeedData, days_back: int
) -> tuple[Announcement, ...]:
    """Return admin + enrolled-course announcements at ``days_back``.

    The general endpoint applies a hardcoded 30-day backend floor
    and filters to the user's enrolled courses; the helper clamps
    the effective window to 30 to mirror the backend.

    Args:
        seed: Loaded seed data.
        days_back: Inclusive upper bound on ``days_ago``, clamped
            to ``GENERAL_BACKEND_FLOOR_DAYS``.

    Returns:
        Tuple of announcements in scope, admin entries first then
        each enrolled course's entries in enrollment order; each
        block is ordered by ``days_ago`` ascending.
    """
    effective = min(days_back, GENERAL_BACKEND_FLOOR_DAYS)
    in_scope: list[Announcement] = [
        a for a in seed.admin_announcements if a.days_ago <= effective
    ]
    for code in seed.enrolled_course_codes:
        in_scope.extend(
            a
            for a in seed.course_announcements.get(code, ())
            if a.days_ago <= effective
        )
    return tuple(in_scope)


def expected_count_course(
    seed: SeedData, course_code: str, days_back: int
) -> int:
    """Return the number of announcements expected from the course endpoint."""
    return len(course_announcements_in_window(seed, course_code, days_back))


def expected_count_general(seed: SeedData, days_back: int) -> int:
    """Return the number of announcements expected from the general endpoint."""
    return len(general_announcements_in_window(seed, days_back))


def _default_seed_path() -> Path:
    """Return the default ``seed.yaml`` path next to the grader package root."""
    return Path(__file__).resolve().parent.parent / DEFAULT_SEED_FILENAME


def _build_seed_data(raw: dict) -> SeedData:
    """Validate the parsed YAML and construct a :class:`SeedData`."""
    user = _require_mapping(raw, "user")
    username = _require_str(user, "username", parent="user")
    password = _require_str(user, "cas_password", parent="user")

    courses = raw.get("courses")
    if not isinstance(courses, list):
        raise SeedError("seed: 'courses' must be a list")

    enrolled_codes: list[str] = []
    course_map: dict[str, tuple[Announcement, ...]] = {}
    for index, course in enumerate(courses):
        if not isinstance(course, dict):
            raise SeedError(f"seed: courses[{index}] must be a mapping")
        code = _require_str(course, "code", parent=f"courses[{index}]")
        if course.get("enrolled") is True:
            enrolled_codes.append(code)
        course_map[code] = _parse_announcements(
            course.get("announcements") or [],
            course_code=code,
            parent=f"courses[{index}].announcements",
        )

    admin = _parse_announcements(
        raw.get("admin_announcements") or [],
        course_code=None,
        parent="admin_announcements",
    )

    return SeedData(
        username=username,
        password=password,
        enrolled_course_codes=tuple(enrolled_codes),
        course_announcements=course_map,
        admin_announcements=admin,
    )


def _parse_announcements(
    entries: list,
    course_code: str | None,
    parent: str,
) -> tuple[Announcement, ...]:
    """Parse a list of announcement entries into ordered ``Announcement`` tuples."""
    if not isinstance(entries, list):
        raise SeedError(f"seed: {parent} must be a list")
    parsed: list[Announcement] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SeedError(f"seed: {parent}[{index}] must be a mapping")
        location = f"{parent}[{index}]"
        days_ago = entry.get("days_ago")
        if not isinstance(days_ago, int) or days_ago < 0:
            raise SeedError(
                f"seed: {location}.days_ago must be a non-negative integer"
            )
        title = _require_str(entry, "title", parent=location)
        body = _require_str(entry, "body", parent=location)
        parsed.append(
            Announcement(
                course_code=course_code,
                days_ago=days_ago,
                title=title,
                body=body,
            )
        )
    parsed.sort(key=lambda a: a.days_ago)
    return tuple(parsed)


def _require_mapping(raw: dict, key: str) -> dict:
    """Return ``raw[key]`` if it is a mapping; raise otherwise."""
    value = raw.get(key)
    if not isinstance(value, dict):
        raise SeedError(f"seed: '{key}' must be a mapping")
    return value


def _require_str(mapping: dict, key: str, parent: str) -> str:
    """Return ``mapping[key]`` if it is a non-empty string; raise otherwise."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise SeedError(f"seed: {parent}.{key} must be a non-empty string")
    return value


SEED: SeedData = load_seed()
