#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Source-IP gating for the /admin/reset endpoint.

The reset endpoint clears in-memory ticket state. To keep it from being
abused over the host port mapping, only requests whose source IP falls
inside the docker bridge subnet are accepted; requests from elsewhere
(including the host) get a 403.
"""

from __future__ import annotations

import ipaddress


def is_bridge_request(client_ip: str, bridge_subnet: str) -> bool:
    """Return True when ``client_ip`` is inside ``bridge_subnet``.

    Args:
        client_ip: The source IP string from the HTTP request.
        bridge_subnet: CIDR string describing the docker bridge network.

    Returns:
        True if the parsed source IP falls inside the parsed CIDR.
        False on parse failure or out-of-subnet.
    """
    try:
        ip = ipaddress.ip_address(client_ip)
        net = ipaddress.ip_network(bridge_subnet, strict=False)
    except ValueError:
        return False
    return ip in net
