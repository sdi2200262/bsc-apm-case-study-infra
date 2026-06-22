#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""HTTP request dispatch for the mock CAS service.

Each request lands on :class:`MockCASHandler`, which routes it to a
method per CAS, SAML, or admin endpoint and emits the matching response body.
Body rendering lives in :mod:`mock_cas.rendering`; this module focuses
on the dispatch and on the shared response-header surface.
"""

from __future__ import annotations

import base64
import logging
import secrets
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler

from .admin import is_bridge_request
from .config import Config
from .rendering import (
    append_query,
    extract_saml_artifact,
    extract_saml_request_id,
    render_cas_invalid_request_xml,
    render_cas_invalid_ticket_xml,
    render_cas_success_xml,
    render_login_html,
    render_logout_html,
    render_not_found_html,
    render_saml_failure_envelope,
    render_saml_success_envelope,
    xml_comment_marker,
)
from .tickets import TicketStore


logger = logging.getLogger("mock_cas.handlers")


class MockCASHandler(BaseHTTPRequestHandler):
    """HTTP handler dispatching the CAS / SAML 1.1 surface.

    The handler is constructed per-request by ``http.server``; shared
    state (config, ticket store) lives on class attributes injected by
    :func:`mock_cas.server.run`.

    Attributes:
        config: The runtime :class:`Config` injected at server start.
        tickets: The shared :class:`TicketStore` injected at server start.
    """

    config: Config = None  # type: ignore[assignment]
    tickets: TicketStore = None  # type: ignore[assignment]

    def version_string(self) -> str:
        """Override the stdlib server-string to the mock's identifying value."""
        return "bsc-apm-mock-cas"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (stdlib signature)
        """Route stdlib log messages through the package logger."""
        logger.info("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802 (stdlib spelling)
        """Dispatch GET requests by path."""
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            self._handle_login_get()
        elif path == "/logout":
            self._handle_logout_get()
        elif path in ("/serviceValidate", "/proxyValidate"):
            self._handle_service_validate(cas_v3=False)
        elif path == "/p3/serviceValidate":
            self._handle_service_validate(cas_v3=True)
        elif path == "/health":
            self._handle_health()
        else:
            self._handle_not_found()

    def do_POST(self) -> None:  # noqa: N802
        """Dispatch POST requests by path."""
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            self._handle_login_post()
        elif path == "/samlValidate":
            self._handle_saml_validate()
        elif path == "/admin/reset":
            self._handle_admin_reset()
        else:
            self._handle_method_not_allowed()

    def _handle_login_get(self) -> None:
        """Render the mock login form."""
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        service = query.get("service", [""])[0]
        execution = self._mint_execution(service)
        body = render_login_html(service=service, execution=execution, error=None)
        self._send_html(200, body)

    def _handle_login_post(self) -> None:
        """Process credentials and either redirect with a ticket or re-render the form."""
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        form = urllib.parse.parse_qs(raw)
        username = (form.get("username") or [""])[0]
        password = (form.get("password") or [""])[0]
        execution = (form.get("execution") or [""])[0]
        service = (form.get("service") or [""])[0]
        if not service:
            service = self._service_from_execution(execution)

        user = self.config.find_credentials(username, password)
        if user is not None:
            ticket = self.tickets.mint(service=service, username=user.username)
            redirect = append_query(service, "ticket", ticket) if service else "/login"
            self.send_response(302)
            self._send_common_headers()
            self.send_header("Location", redirect)
            self.send_header(
                "Set-Cookie",
                "TGC=mock-tgc-do-not-trust; Path=/; Secure; HttpOnly; SameSite=None",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        execution = self._mint_execution(service)
        body = render_login_html(
            service=service,
            execution=execution,
            error="Mock CAS could not authenticate the supplied credentials.",
        )
        self._send_html(401, body)

    @staticmethod
    def _mint_execution(service: str) -> str:
        """Bind the service URL into a flow-state token, Apereo-CAS style.

        The token format is ``<random-nonce>.<base64-service>``. A POST that
        omits the form's hidden ``service`` field can recover it from the
        token, matching Apereo CAS's stateful execution semantics.
        """
        nonce = secrets.token_urlsafe(48)
        encoded = base64.urlsafe_b64encode(service.encode("utf-8")).decode("ascii").rstrip("=")
        return f"{nonce}.{encoded}"

    @staticmethod
    def _service_from_execution(execution: str) -> str:
        """Recover the service URL bound into the execution token, or empty string."""
        if "." not in execution:
            return ""
        encoded = execution.rsplit(".", 1)[1]
        padding = "=" * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ""

    def _handle_logout_get(self) -> None:
        """Render the mock logout confirmation and clear the TGC cookie."""
        body = render_logout_html().encode("utf-8")
        self.send_response(200)
        self._send_common_headers()
        self.send_header("Content-Type", "text/html;charset=UTF-8")
        self.send_header(
            "Set-Cookie",
            "TGC=; Max-Age=0; Expires=Thu, 01-Jan-1970 00:00:10 GMT; "
            "Path=/; Secure; HttpOnly",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_service_validate(self, *, cas_v3: bool) -> None:
        """Validate a CAS 2.0 or 3.0 service ticket and emit a CAS XML response."""
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        ticket = (query.get("ticket") or [""])[0]
        service = (query.get("service") or [""])[0]
        marker = xml_comment_marker()

        if not ticket or not service:
            self._send_cas_xml(200, render_cas_invalid_request_xml(marker))
            return

        record = self.tickets.consume(ticket)
        if record is None or record.service != service:
            self._send_cas_xml(200, render_cas_invalid_ticket_xml(marker, ticket))
            return

        body = render_cas_success_xml(
            marker=marker,
            user=self.config.require_user(record.username),
            cas_v3=cas_v3,
        )
        self._send_cas_xml(200, body)

    def _handle_saml_validate(self) -> None:
        """Validate a SAML 1.1 SOAP request and emit a SAML SOAP response."""
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        artifact = extract_saml_artifact(raw)
        request_id = extract_saml_request_id(raw) or "UNKNOWN"
        marker = xml_comment_marker()

        if not artifact:
            body = render_saml_failure_envelope(
                request_id=request_id, marker=marker, status_message=None
            )
            self._send_saml_xml(200, body)
            return

        record = self.tickets.consume(artifact)
        if record is None:
            body = render_saml_failure_envelope(
                request_id=request_id,
                marker=marker,
                status_message=f"Ticket '{artifact}' not recognized",
            )
            self._send_saml_xml(200, body)
            return

        body = render_saml_success_envelope(
            request_id=request_id,
            marker=marker,
            user=self.config.require_user(record.username),
        )
        self._send_saml_xml(200, body)

    def _handle_admin_reset(self) -> None:
        """Drop ticket state when the request originates from the docker bridge."""
        client_ip = self.client_address[0]
        if not is_bridge_request(client_ip, self.config.bridge_subnet):
            self.send_response(403)
            self._send_common_headers()
            self.send_header("Content-Type", "text/plain;charset=UTF-8")
            payload = b"forbidden: /admin/reset is bridge-network-only on the mock CAS\n"
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        dropped = self.tickets.reset()
        self.send_response(200)
        self._send_common_headers()
        self.send_header("Content-Type", "application/json;charset=UTF-8")
        payload = (
            "{"
            "\"status\": \"reset\", "
            f"\"tickets_dropped\": {dropped}"
            "}\n"
        ).encode("utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle_health(self) -> None:
        """Emit a simple OK for the lifecycle scripts' status probe."""
        self.send_response(200)
        self._send_common_headers()
        self.send_header("Content-Type", "text/plain;charset=UTF-8")
        payload = b"ok\n"
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle_not_found(self) -> None:
        """Emit a mock-identifying 404 page."""
        body = render_not_found_html(self.path).encode("utf-8")
        self.send_response(404)
        self._send_common_headers()
        self.send_header("Content-Type", "text/html;charset=UTF-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_method_not_allowed(self) -> None:
        """Emit a 405 for known endpoints that do not allow this method."""
        self.send_response(405)
        self._send_common_headers()
        self.send_header("Content-Type", "text/plain;charset=UTF-8")
        payload = b"method not allowed on the mock CAS\n"
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, status: int, body: str) -> None:
        """Write an HTML response body with the shared header surface."""
        encoded = body.encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "text/html;charset=UTF-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_cas_xml(self, status: int, body: str) -> None:
        """Write a CAS XML response body with the shared header surface."""
        encoded = body.encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "application/xml;charset=UTF-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_saml_xml(self, status: int, body: str) -> None:
        """Write a SAML 1.1 XML response body with the shared header surface."""
        encoded = body.encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "text/xml;charset=UTF-8")
        self.send_header("SOAPAction", "http://www.oasis-open.org/committees/security")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_common_headers(self) -> None:
        """Emit the shared no-cache and security headers attached to every response.

        Sets cache-busting headers (``Cache-Control``, ``Pragma``,
        ``Expires``) and a small security-header surface
        (``Strict-Transport-Security``, ``X-Content-Type-Options``,
        ``X-Frame-Options``, ``X-XSS-Protection``) plus a per-request
        ``requestId`` so log lines can be correlated.
        """
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Strict-Transport-Security", "max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Content-Language", "en")
        self.send_header("requestId", str(uuid.uuid4()))
