#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Runtime configuration loader for the grading mock CAS service.

Reads a JSON configuration file describing the mock test users and the
runtime parameters of the service. The grading environment seeds two
users with disjoint enrolment, so the credential store is a list rather
than a single pair. When the configuration file is absent, built-in
defaults are returned so the service is runnable without a mounted
config file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG_PATH = "/etc/mock-cas/cas-config.json"


@dataclass(frozen=True)
class User:
    """One mock test user and the attributes the CAS returns for it.

    Attributes:
        username: The username the user submits at the CAS form.
        password: Plaintext password the user submits at the CAS form.
        display_name: Human-readable display name.
        email: Email attribute returned in CAS and SAML assertions.
        givenname: Given-name attribute returned in CAS and SAML assertions.
        surname: Surname attribute returned in CAS and SAML assertions.
        studentid: Student-id attribute returned in CAS and SAML assertions.
    """

    username: str
    password: str
    display_name: str
    email: str
    givenname: str
    surname: str
    studentid: str


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the grading mock CAS service.

    Attributes:
        users: The mock test users the service authenticates.
        port: The TCP port the service binds to.
        cert_path: Path to the TLS certificate file mounted into the image.
        key_path: Path to the TLS private-key file mounted into the image.
        bridge_subnet: CIDR for /admin/reset source-IP gating.
    """

    users: tuple[User, ...]
    port: int = 8082
    cert_path: str = "/etc/mock-cas/certs/sso_cert.pem"
    key_path: str = "/etc/mock-cas/certs/sso_key.pem"
    bridge_subnet: str = "172.16.0.0/12"

    def find_credentials(self, username: str, password: str) -> User | None:
        """Return the user matching both username and password, or None.

        Args:
            username: The submitted username.
            password: The submitted plaintext password.

        Returns:
            The matching :class:`User`, or ``None`` when no user matches
            both fields.
        """
        for user in self.users:
            if user.username == username and user.password == password:
                return user
        return None

    def require_user(self, username: str) -> User:
        """Return the user with this username.

        Used by the validation endpoints, where a ticket is only ever
        minted for a user that exists in this config, so absence is an
        invariant breach rather than a recoverable state.

        Args:
            username: The username bound into a previously minted ticket.

        Returns:
            The matching :class:`User`.

        Raises:
            KeyError: If no configured user has this username.
        """
        for user in self.users:
            if user.username == username:
                return user
        raise KeyError(
            f"mock CAS: ticket bound to unknown user {username!r}; "
            "ticket minting and the user set are out of sync"
        )


_DEFAULTS = Config(
    users=(
        User(
            username="student_courses",
            password="coursepass123",
            display_name="Demo Student",
            email="student_courses@example.edu",
            givenname="Demo",
            surname="Student",
            studentid="STU1001",
        ),
        User(
            username="student_general",
            password="generalpass123",
            display_name="Demo Student",
            email="student_general@example.edu",
            givenname="Demo",
            surname="Student",
            studentid="STU1002",
        ),
    ),
)


def load_config(path: str | None = None) -> Config:
    """Load the runtime configuration.

    Args:
        path: Path to the JSON config file. Falls back to the value of the
            ``MOCK_CAS_CONFIG`` environment variable, then to
            ``DEFAULT_CONFIG_PATH``. If the resolved path does not exist,
            the built-in defaults are returned and the caller can run the
            service standalone.

    Returns:
        A populated :class:`Config` instance.

    Raises:
        ValueError: If the JSON file is present but cannot be parsed, is
            missing the ``users`` list, or carries unknown or missing
            fields.
    """
    import os

    resolved = path or os.environ.get("MOCK_CAS_CONFIG") or DEFAULT_CONFIG_PATH
    file_path = Path(resolved)
    if not file_path.is_file():
        return _DEFAULTS

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"mock CAS config at {file_path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "users" not in data:
        raise ValueError(
            f"mock CAS config at {file_path} must be a JSON object with a 'users' list"
        )

    raw_users = data.pop("users")
    try:
        users = tuple(User(**entry) for entry in raw_users)
    except TypeError as exc:
        raise ValueError(
            f"mock CAS config at {file_path} has a malformed user entry: {exc}"
        ) from exc

    try:
        return Config(users=users, **data)
    except TypeError as exc:
        raise ValueError(
            f"mock CAS config at {file_path} has unknown or missing fields: {exc}"
        ) from exc
