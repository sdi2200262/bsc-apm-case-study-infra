#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
SSO Mock Server - CAS 2.0 / SAML 1.1 authentication mock for testing.

Provides a lightweight HTTPS server that simulates CAS authentication.
Used alongside a real OpenEclass instance for comprehensive testing.
"""

import os
import ssl
import uuid
import re
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional


# File paths
GRADER_DIR = Path(__file__).parent.parent 
FIXTURES_DIR = GRADER_DIR / "fixtures"
CERT_FILE = GRADER_DIR / "sso_cert.pem"
KEY_FILE = GRADER_DIR / "sso_key.pem"

# Service ticket storage: ST-{uuid} -> validation data
service_tickets: Dict[str, dict] = {}

# Test credentials
TEST_USER = "testuser"
TEST_PASS = "testpass"


class CasHandler(BaseHTTPRequestHandler):
    """HTTP request handler for CAS authentication server."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def _send_response(self, code: int, content: str, content_type: str = "text/html"):
        """Send HTTP response."""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(content.encode()))
        self.end_headers()
        self.wfile.write(content.encode())

    def _send_redirect(self, location: str):
        """Send redirect response."""
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/sso/login", "/cas/login"):
            self._handle_login_form(path, query, parsed.query)
        elif path == "/cas/serviceValidate":
            self._handle_cas_validate(query)
        elif path == "/cas/samlValidate":
            self._handle_saml_validate(query, "")
        else:
            self._send_response(404, "Not Found")

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode()
        post_params = parse_qs(post_data)

        if path in ("/sso/login", "/cas/login"):
            self._handle_login_submit(post_params, query)
        elif path == "/cas/samlValidate":
            self._handle_saml_validate(query, post_data)
        else:
            self._send_response(404, "Not Found")
    
    def _handle_login_form(self, path: str, query: dict, raw_query: str):
        """Display CAS login form."""
        service = query.get("service", [""])[0]
        execution = str(uuid.uuid4())

        html = self._load_fixture("sso_login.html")
        html = html.replace("{{EXECUTION_TOKEN}}", execution)
        html = html.replace("{{SERVICE_URL}}", service)
        
        # Update form action to preserve query params
        action_url = f"{path}?{raw_query}" if raw_query else path
        html = re.sub(r'action="[^"]+"', f'action="{action_url}"', html, count=1)

        self._send_response(200, html)

    def _handle_login_submit(self, params: dict, query: dict):
        """Process CAS login form submission."""
        username = params.get("username", [""])[0]
        password = params.get("password", [""])[0]
        service = params.get("service", [None])[0] or query.get("service", [""])[0]

        if username == TEST_USER and password == TEST_PASS:
            # Generate service ticket
            ticket = f"ST-{uuid.uuid4()}"
            service_tickets[ticket] = {
                "username": username,
                "service": service,
                "created": datetime.now().isoformat(),
                "valid": True
            }

            # Redirect to service with ticket
            separator = "&" if "?" in service else "?"
            redirect_url = f"{service}{separator}ticket={ticket}"
            self._send_redirect(redirect_url)
        else:
            html = self._load_fixture("sso_login_error.html")
            self._send_response(200, html)

    def _handle_saml_validate(self, query: dict, post_data: str):
        """Handle SAML 1.1 ticket validation."""
        target = query.get("TARGET", [""])[0]
        
        # Extract ticket from SOAP envelope
        ticket = ""
        match = re.search(r'<samlp:AssertionArtifact[^>]*>([^<]+)</samlp:AssertionArtifact>', post_data)
        if match:
            ticket = match.group(1).strip()
        
        ticket_data = service_tickets.get(ticket)
        
        if ticket_data and ticket_data["valid"] and ticket_data["service"] == target:
            ticket_data["valid"] = False  # Single use
            username = ticket_data["username"]
            now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            
            response = f'''<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
  <SOAP-ENV:Body>
    <Response xmlns="urn:oasis:names:tc:SAML:1.0:protocol" 
              xmlns:saml="urn:oasis:names:tc:SAML:1.0:assertion"
              IssueInstant="{now}" MajorVersion="1" MinorVersion="1">
      <Status><StatusCode Value="samlp:Success"/></Status>
      <Assertion xmlns="urn:oasis:names:tc:SAML:1.0:assertion"
                 IssueInstant="{now}" MajorVersion="1" MinorVersion="1">
        <Conditions NotBefore="{now}" NotOnOrAfter="{now}">
          <AudienceRestrictionCondition><Audience>{target}</Audience></AudienceRestrictionCondition>
        </Conditions>
        <AuthenticationStatement AuthenticationInstant="{now}" 
                                 AuthenticationMethod="urn:oasis:names:tc:SAML:1.0:am:unspecified">
          <Subject>
            <NameIdentifier>{username}</NameIdentifier>
            <SubjectConfirmation>
              <ConfirmationMethod>urn:oasis:names:tc:SAML:1.0:cm:artifact</ConfirmationMethod>
            </SubjectConfirmation>
          </Subject>
        </AuthenticationStatement>
      </Assertion>
    </Response>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>'''
            self._send_response(200, response, "text/xml")
        else:
            error = '''<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
  <SOAP-ENV:Body>
    <Response xmlns="urn:oasis:names:tc:SAML:1.0:protocol">
      <Status><StatusCode Value="samlp:RequestDenied"/></Status>
    </Response>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>'''
            self._send_response(200, error, "text/xml")

    def _handle_cas_validate(self, query: dict):
        """Handle CAS 2.0 service ticket validation."""
        service = query.get("service", [""])[0]
        ticket = query.get("ticket", [""])[0]

        ticket_data = service_tickets.get(ticket)
        if ticket_data and ticket_data["valid"] and ticket_data["service"] == service:
            ticket_data["valid"] = False  # Single use
            
            response = f'''<?xml version="1.0" encoding="UTF-8"?>
<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
    <cas:authenticationSuccess>
        <cas:user>{ticket_data["username"]}</cas:user>
    </cas:authenticationSuccess>
</cas:serviceResponse>'''
            self._send_response(200, response, "text/xml")
        else:
            response = '''<?xml version="1.0" encoding="UTF-8"?>
<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
    <cas:authenticationFailure code="INVALID_TICKET">Ticket is invalid</cas:authenticationFailure>
</cas:serviceResponse>'''
            self._send_response(200, response, "text/xml")
    
    def _load_fixture(self, filename: str) -> str:
        """Load HTML fixture file."""
        path = FIXTURES_DIR / filename
        if path.exists():
            return path.read_text()
        return f"<html><body>Fixture {filename} not found</body></html>"


class MockServerManager:
    """Manages SSO mock server lifecycle."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8082, use_https: bool = True):
        self.host = host
        self.port = port
        self.use_https = use_https
        self.sso_domain = os.getenv("SSO_DOMAIN", "172.17.0.1")
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the SSO mock server in a background thread."""
        self.server = HTTPServer((self.host, self.port), CasHandler)
        
        if self.use_https:
            if not CERT_FILE.exists() or not KEY_FILE.exists():
                raise FileNotFoundError(
                    f"SSL certificates not found. Generate with:\n"
                    f"  openssl req -x509 -newkey rsa:2048 -keyout {KEY_FILE} "
                    f"-out {CERT_FILE} -days 365 -nodes -subj '/CN=172.17.0.1' "
                    f"-addext 'subjectAltName=IP:172.17.0.1'"
                )
            
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(CERT_FILE), str(KEY_FILE))
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.1)

    def stop(self) -> None:
        """Stop the SSO mock server."""
        if self.server:
            self.server.shutdown()
            self.server = None
        if self.thread:
            self.thread.join(timeout=1)
            self.thread = None
        service_tickets.clear()

    def get_base_url(self) -> str:
        """Get base URL of the SSO mock server."""
        protocol = "https" if self.use_https else "http"
        return f"{protocol}://{self.host}:{self.port}"

    def get_env(self) -> dict:
        """Get environment variables for MCP server configuration."""
        env = {
            "ECLASS_URL": "http://localhost",
            "ECLASS_USERNAME": TEST_USER,
            "ECLASS_PASSWORD": TEST_PASS,
            "ECLASS_SSO_DOMAIN": f"{self.sso_domain}:{self.port}",
            "ECLASS_SSO_PROTOCOL": "https" if self.use_https else "http",
        }
        
        if self.use_https:
            # Disable SSL verification for self-signed cert
            env["PYTHONHTTPSVERIFY"] = "0"
            env["SSL_CERT_FILE"] = str(CERT_FILE)
            env["REQUESTS_CA_BUNDLE"] = str(CERT_FILE)
            env["CURL_CA_BUNDLE"] = str(CERT_FILE)
        
        return env


if __name__ == "__main__":
    # Allow standalone testing
    manager = MockServerManager()
    protocol = "https" if manager.use_https else "http"
    print(f"Starting SSO mock server on {protocol}://0.0.0.0:{manager.port}")
    manager.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        manager.stop()
