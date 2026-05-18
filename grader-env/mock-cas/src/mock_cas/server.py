#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""HTTPS server bootstrap for the mock CAS service.

Loads the runtime configuration, wires the shared ticket store into the
request handler class, and starts a threaded HTTPS server. The TLS
certificates are mounted into the container by the compose stack and are
read from the paths recorded in the configuration.
"""

from __future__ import annotations

import logging
import os
import ssl
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

from .config import Config, load_config
from .handlers import MockCASHandler
from .tickets import TicketStore


_DEFAULT_BIND_HOST = "0.0.0.0"


def run(config: Config | None = None) -> None:
    """Start the mock CAS HTTPS server and serve until interrupted.

    Args:
        config: Optional pre-loaded :class:`Config`. When omitted, the
            configuration is loaded from the path in ``MOCK_CAS_CONFIG`` or
            the built-in default path.

    Raises:
        FileNotFoundError: If the TLS certificate or key file is missing.
    """
    cfg = config if config is not None else load_config()
    _configure_logging()
    logger = logging.getLogger("mock_cas.server")

    cert = Path(cfg.cert_path)
    key = Path(cfg.key_path)
    if not cert.is_file() or not key.is_file():
        raise FileNotFoundError(
            f"mock CAS TLS material missing: cert={cert} key={key}; "
            "the install script generates these into <prefix>/certs/"
        )

    MockCASHandler.config = cfg
    MockCASHandler.tickets = TicketStore()

    bind_host = os.environ.get("MOCK_CAS_BIND_HOST", _DEFAULT_BIND_HOST)
    bind_port = int(os.environ.get("MOCK_CAS_PORT", str(cfg.port)))

    server = ThreadingHTTPServer((bind_host, bind_port), MockCASHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert), keyfile=str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)

    logger.info("mock CAS listening on https://%s:%d", bind_host, bind_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("mock CAS shutting down")
    finally:
        server.server_close()


def main() -> None:
    """Entry point used by the package script and the Dockerfile."""
    try:
        run()
    except FileNotFoundError as exc:
        print(f"mock CAS: {exc}", file=sys.stderr)
        sys.exit(1)


def _configure_logging() -> None:
    level_name = os.environ.get("MOCK_CAS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


if __name__ == "__main__":
    main()
