#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Seed-data loader for grader assertions.

Loads the grading environment's ``grader-env/seed/seed.yaml``, which
defines the users, courses, and announcements the rubric assertions
are built from. The grader and the grading environment ship in the
same repository, so this module reads the seed file directly rather
than a transcribed copy.

The seed carries two users with disjoint enrolment; the grader
authenticates as one of them per scenario group (the course and
baseline suites as ``student_courses``, the general suite as
``student_general``). That authenticated user is the scenario's
principal: the seeded identity the grader logs in as. A scenario
selects its principal and the loader answers per-principal enrolment
and window queries.

Boundary semantics: ``days_back=N`` is an inclusive filter on
``days_ago``. An announcement at ``days_ago=K`` is in scope iff
``K <= N``. The per-course endpoint applies no backend date floor,
matching openeclass, whose per-course announcements page filters on
visibility only, so the course helper is a straight ``K <= N``.

The general endpoint is different. openeclass builds the general
view from a portfolio query that floors every row at
``date >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH)``, a MySQL
calendar-month subtraction whose span is 28 to 31 days depending on
the month, not a flat 30. The general helper models that floor as a
flat ``GENERAL_BACKEND_FLOOR_DAYS``-day clamp. That is a deliberate
approximation, exact for this seed because the general view's union
(the system-wide announcements plus the general principal's
enrolled-course announcements) has its oldest member at 20 days,
inside even the shortest 28-day (February) calendar month, so the
flat clamp and the calendar-month floor select the same set for
every seed-apply date. The approximation holds only while the
oldest general-union announcement stays below the 28-to-31-day
band; a seed that places a general-union announcement in that band
would make this model and openeclass diverge, and the helper would
then have to implement the calendar-month floor itself.

Ordering: announcements are ordered newest first, i.e. by
``days_ago`` ascending. The general endpoint orders the union of
system-wide and enrolled-course announcements newest first across
both sources, not source-blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Flat-day stand-in for openeclass's calendar-month general-view
# floor (``DATE_SUB(CURDATE(), INTERVAL 1 MONTH)``, 28 to 31 days).
# Exact for this seed only; see the module docstring for the
# invariant that keeps it exact and when it must be replaced.
GENERAL_BACKEND_FLOOR_DAYS = 30

# The grading environment's seed lives beside the grader in the same
# repository: <infra>/grader-env/seed/seed.yaml, three parents up
# from this file (grader/protocol/seed.py -> grader/protocol -> grader -> infra).
_GRADER_ENV_SEED = (
    Path(__file__).resolve().parent.parent.parent / "grader-env" / "seed" / "seed.yaml"
)


class SeedError(Exception):
    """Raised when the seed file is missing, malformed, or incomplete."""


@dataclass(frozen=True)
class User:
    """One seeded principal.

    Attributes:
        username: CAS / openeclass login name.
        password: CAS password for that user.
    """

    username: str
    password: str


@dataclass(frozen=True)
class Announcement:
    """One seeded announcement, course or system-wide.

    Attributes:
        course_code: Course code the announcement belongs to, or
            ``None`` for a system-wide (admin) announcement.
        days_ago: Age of the announcement in whole days. Matches
            the seed YAML's ``days_ago`` field; the seed loader at
            reset time anchors the row date to
            ``NOW() - days_ago days``.
        title: Title text as seeded.
        body: Body text as seeded.
    """

    course_code: str | None
    days_ago: int
    title: str
    body: str


@dataclass(frozen=True)
class Course:
    """One seeded course.

    Attributes:
        code: Course code (``"CS101"``).
        title: Human course title as seeded; the expected
            ``get_courses`` response lists courses alphabetically by
            this value.
        enrolled_users: Usernames enrolled in the course, in seed
            order.
        announcements: The course's announcements, ordered by
            ``days_ago`` ascending (newest first).
    """

    code: str
    title: str
    enrolled_users: tuple[str, ...]
    announcements: tuple[Announcement, ...]


@dataclass(frozen=True)
class SeedData:
    """Parsed contents of the grading environment seed.

    Attributes:
        users: Mapping of username to ``User``.
        courses: Mapping of course code to ``Course``, in seed
            order of insertion.
        admin_announcements: System-wide announcements ordered by
            ``days_ago`` ascending (newest first).
    """

    users: dict[str, User]
    courses: dict[str, Course]
    admin_announcements: tuple[Announcement, ...]


def load_seed(path: Path | None = None) -> SeedData:
    """Load the grading-environment seed YAML and return a ``SeedData``.

    Args:
        path: Optional path to a seed file. Defaults to the
            in-repository ``grader-env/seed/seed.yaml``.

    Returns:
        Parsed seed data.

    Raises:
        SeedError: When the file is missing, cannot be parsed, or
            does not carry the required keys.
    """
    seed_path = path or _GRADER_ENV_SEED
    if not seed_path.is_file():
        raise SeedError(f"seed file not found: {seed_path}")
    try:
        raw = yaml.safe_load(seed_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise SeedError(f"seed file malformed: {error}") from error
    if not isinstance(raw, dict):
        raise SeedError("seed file root must be a mapping")
    return _build_seed_data(raw)


def user(seed: SeedData, username: str) -> User:
    """Return the seeded ``User`` for ``username``.

    Args:
        seed: Loaded seed data.
        username: The principal to look up.

    Returns:
        The matching user.

    Raises:
        SeedError: When the seed carries no such user.
    """
    found = seed.users.get(username)
    if found is None:
        raise SeedError(f"seed: no user {username!r}")
    return found


def enrolled_courses(seed: SeedData, username: str) -> tuple[Course, ...]:
    """Return the courses ``username`` is enrolled in, ``get_courses`` order.

    The openeclass 4.3.3 portfolio course-link list the reference parser
    walks is alphabetical by course title, so the expected
    ``get_courses`` response orders the user's courses by title;
    this helper returns them in that order.

    Args:
        seed: Loaded seed data.
        username: The enrolled principal.

    Returns:
        The user's courses ordered alphabetically by title.
    """
    courses = [course for course in seed.courses.values() if username in course.enrolled_users]
    courses.sort(key=lambda c: c.title)
    return tuple(courses)


def course_announcements_in_window(
    seed: SeedData, course_code: str, days_back: int
) -> tuple[Announcement, ...]:
    """Return one course's announcements visible at ``days_back``.

    openeclass's per-course announcements page floors on visibility
    only, with no date cutoff, so the helper is a straight inclusive
    filter on ``days_ago <= days_back``.

    Args:
        seed: Loaded seed data.
        course_code: Course to filter on.
        days_back: Inclusive upper bound on ``days_ago``.

    Returns:
        Tuple of announcements in scope, ordered by ``days_ago``
        ascending (newest first). Empty when the course has no seed
        entries or every entry is older than the window.
    """
    course = seed.courses.get(course_code)
    if course is None:
        return ()
    return tuple(a for a in course.announcements if a.days_ago <= days_back)


def general_announcements_in_window(
    seed: SeedData, username: str, days_back: int
) -> tuple[Announcement, ...]:
    """Return the general-endpoint union for ``username`` at ``days_back``.

    openeclass floors the general view at a calendar month
    (``DATE_SUB(CURDATE(), INTERVAL 1 MONTH)``); this helper uses the
    flat ``GENERAL_BACKEND_FLOOR_DAYS``-day approximation the module
    docstring describes, then unions the system-wide announcements
    with the announcements of every course the user is enrolled in,
    ordered newest first across both sources.

    Args:
        seed: Loaded seed data.
        username: The authenticated principal whose enrolment
            scopes the course side of the union.
        days_back: Inclusive upper bound on ``days_ago``, clamped
            to ``GENERAL_BACKEND_FLOOR_DAYS``.

    Returns:
        Tuple of announcements in scope, ordered by ``days_ago``
        ascending (newest first) across system-wide and
        enrolled-course entries together.
    """
    effective = min(days_back, GENERAL_BACKEND_FLOOR_DAYS)
    in_scope: list[Announcement] = [a for a in seed.admin_announcements if a.days_ago <= effective]
    for course in seed.courses.values():
        if username in course.enrolled_users:
            in_scope.extend(a for a in course.announcements if a.days_ago <= effective)
    in_scope.sort(key=lambda a: a.days_ago)
    return tuple(in_scope)


def _build_seed_data(raw: dict[str, Any]) -> SeedData:
    """Validate the parsed YAML and construct a ``SeedData``.

    Args:
        raw: The YAML mapping at the seed file's top level.

    Returns:
        The validated ``SeedData``.

    Raises:
        SeedError: When any required key is missing, malformed, or
            of the wrong type.
    """
    raw_users = raw.get("users")
    if not isinstance(raw_users, list) or not raw_users:
        raise SeedError("seed: 'users' must be a non-empty list")
    users: dict[str, User] = {}
    for index, entry in enumerate(raw_users):
        if not isinstance(entry, dict):
            raise SeedError(f"seed: users[{index}] must be a mapping")
        location = f"users[{index}]"
        username = _require_str(entry, "username", parent=location)
        password = _require_str(entry, "cas_password", parent=location)
        users[username] = User(username=username, password=password)

    raw_courses = raw.get("courses")
    if not isinstance(raw_courses, list):
        raise SeedError("seed: 'courses' must be a list")
    courses: dict[str, Course] = {}
    for index, entry in enumerate(raw_courses):
        if not isinstance(entry, dict):
            raise SeedError(f"seed: courses[{index}] must be a mapping")
        location = f"courses[{index}]"
        code = _require_str(entry, "code", parent=location)
        title = _require_str(entry, "title", parent=location)
        enrolled = entry.get("enrolled_users") or []
        if not isinstance(enrolled, list):
            raise SeedError(f"seed: {location}.enrolled_users must be a list")
        courses[code] = Course(
            code=code,
            title=title,
            enrolled_users=tuple(str(u) for u in enrolled),
            announcements=_parse_announcements(
                entry.get("announcements") or [],
                course_code=code,
                parent=f"{location}.announcements",
            ),
        )

    admin = _parse_announcements(
        raw.get("admin_announcements") or [],
        course_code=None,
        parent="admin_announcements",
    )

    return SeedData(
        users=users,
        courses=courses,
        admin_announcements=admin,
    )


def _parse_announcements(
    entries: list[Any],
    course_code: str | None,
    parent: str,
) -> tuple[Announcement, ...]:
    """Parse announcement entries into ``Announcement`` tuples, newest first.

    Args:
        entries: Raw announcement entries from the YAML.
        course_code: Course code each entry belongs to, or ``None``
            for system-wide entries.
        parent: Dotted path used in error messages.

    Returns:
        The parsed announcements ordered by ``days_ago`` ascending
        (newest first).

    Raises:
        SeedError: When any entry is missing required fields or has
            a malformed ``days_ago``/``title``/``body``.
    """
    if not isinstance(entries, list):
        raise SeedError(f"seed: {parent} must be a list")
    parsed: list[Announcement] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SeedError(f"seed: {parent}[{index}] must be a mapping")
        location = f"{parent}[{index}]"
        days_ago = entry.get("days_ago")
        if not isinstance(days_ago, int) or days_ago < 0:
            raise SeedError(f"seed: {location}.days_ago must be a non-negative integer")
        parsed.append(
            Announcement(
                course_code=course_code,
                days_ago=days_ago,
                title=_require_str(entry, "title", parent=location),
                body=_require_str(entry, "body", parent=location),
            )
        )
    parsed.sort(key=lambda a: a.days_ago)
    return tuple(parsed)


def _require_str(mapping: dict[str, Any], key: str, parent: str) -> str:
    """Return ``mapping[key]`` if it is a non-empty string; raise otherwise.

    Args:
        mapping: Parent YAML mapping the value is read from.
        key: Required key.
        parent: Dotted path used in error messages.

    Returns:
        The string value at ``mapping[key]``.

    Raises:
        SeedError: When the value is missing, not a string, or empty.
    """
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise SeedError(f"seed: {parent}.{key} must be a non-empty string")
    return value


SEED: SeedData = load_seed()
