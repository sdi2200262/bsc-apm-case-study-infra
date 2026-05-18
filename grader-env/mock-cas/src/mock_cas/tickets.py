#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Service-ticket lifecycle for the mock CAS service.

Tickets are short-lived, single-use, and held in process memory. Each
ticket is minted at credentials POST and consumed at the matching
samlValidate (or serviceValidate) call. The store is reset by the
/admin/reset endpoint when the testbed's reset script invokes it.
"""

from __future__ import annotations

import itertools
import secrets
import threading
import time
from dataclasses import dataclass


_TICKET_PREFIX = "ST"
_TICKET_SUFFIX = "mockcas"
_INITIAL_SEQUENCE = 4076681


@dataclass(frozen=True)
class ServiceTicket:
    """A single-use service ticket bound to a (service, username) pair.

    Attributes:
        ticket_id: The opaque ticket identifier returned to the relying party.
        service: The service URL the ticket was issued for.
        username: The authenticated username the ticket attests to.
        issued_at: Unix timestamp at issuance (seconds since the epoch).
    """

    ticket_id: str
    service: str
    username: str
    issued_at: float


class TicketStore:
    """In-memory store for service tickets.

    The store is thread-safe; the HTTP server runs each request on its
    own thread, so mint/consume calls can race. A simple lock around the
    backing dict is sufficient for the request volume this service handles.
    """

    def __init__(self) -> None:
        self._tickets: dict[str, ServiceTicket] = {}
        self._counter = itertools.count(start=_INITIAL_SEQUENCE)
        self._lock = threading.Lock()

    def mint(self, service: str, username: str) -> str:
        """Mint a new ticket bound to ``service`` and ``username``.

        Args:
            service: The service URL the relying party will redirect back to.
            username: The username that just authenticated.

        Returns:
            The ticket identifier in the form ``ST-<seq>-<random>-mockcas``.
        """
        with self._lock:
            seq = next(self._counter)
            random_part = secrets.token_urlsafe(20)
            ticket_id = f"{_TICKET_PREFIX}-{seq}-{random_part}-{_TICKET_SUFFIX}"
            self._tickets[ticket_id] = ServiceTicket(
                ticket_id=ticket_id,
                service=service,
                username=username,
                issued_at=time.time(),
            )
            return ticket_id

    def consume(self, ticket_id: str) -> ServiceTicket | None:
        """Atomically validate and remove a ticket.

        The ticket is removed regardless of whether the caller passes the
        service-URL match check; CAS service tickets are single-use by
        protocol, so a presented-but-invalid ticket is still consumed.

        Args:
            ticket_id: The ticket identifier presented by the relying party.

        Returns:
            The :class:`ServiceTicket` if the ticket existed, ``None`` otherwise.
        """
        with self._lock:
            return self._tickets.pop(ticket_id, None)

    def reset(self) -> int:
        """Drop every ticket in the store.

        Returns:
            The number of tickets that were dropped.
        """
        with self._lock:
            count = len(self._tickets)
            self._tickets.clear()
            return count

    def size(self) -> int:
        """Return the current number of tickets held."""
        with self._lock:
            return len(self._tickets)
