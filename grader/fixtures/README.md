# SSO Mock Server Fixtures

HTML templates for the CAS (Central Authentication Service) mock server used in grading tests.

## Overview

These fixtures replicate OpenEclass's CAS login page structure to enable authentication testing without requiring a real SSO server. The mock server (`src/mock_server.py`) loads these templates and injects dynamic values.

## Files

- **sso_login.html** - CAS login form template
- **sso_login_error.html** - CAS login error page template

## Template Variables

Both templates support the following placeholders that are replaced at runtime:

- `{{EXECUTION_TOKEN}}` - Unique execution token for CSRF protection
- `{{SERVICE_URL}}` - Service URL for redirect after authentication

## Important Notes

**Do not modify these files** unless OpenEclass's CAS login page structure changes.

These fixtures must match OpenEclass's expected HTML structure exactly. Any changes to form field names, IDs, or structure may break the authentication flow during grading tests.

The templates are loaded by `MockServerManager` in `src/mock_server.py` via the `_load_fixture()` method.

## Usage

These fixtures are automatically used by the mock SSO server when running grading tests. No manual intervention required.

