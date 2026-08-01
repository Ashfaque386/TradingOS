"""REL-014 E14.2 (GLH-03) integration test: the real security response headers a real OWASP ZAP
scan (REL-009 E9.4) found missing against `app-tls`, now added via
src/core/security_headers.py's real middleware, verified against the real running app.
"""

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.security_headers import SECURITY_HEADERS

client = TestClient(app)


def test_all_security_headers_present_on_a_real_response():
    response = client.get("/health")
    assert response.status_code == 200
    for header, expected_value in SECURITY_HEADERS.items():
        assert (
            response.headers.get(header) == expected_value
        ), f"missing or wrong value for {header!r}"


def test_security_headers_present_on_an_error_response_too():
    # A 404 still goes through the same middleware stack -- headers must not be conditional on
    # a successful response, since an attacker-relevant page (e.g. a reflected error) is exactly
    # the case these headers matter most for.
    response = client.get("/api/v1/this-route-does-not-exist")
    assert response.status_code == 404
    for header in SECURITY_HEADERS:
        assert header in response.headers
