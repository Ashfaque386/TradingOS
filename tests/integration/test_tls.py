"""REL-007 E7.6 (SEC-023/024, reduced local equivalent) against the real `app-tls` compose
service -- run via `docker compose exec app pytest tests/integration/test_tls.py`, so it reaches
`app-tls` by its real compose DNS name. `docker compose up -d app-tls` (and
`scripts/generate_dev_tls_cert.py` beforehand) must have already run -- this test proves the
real service is reachable over real TLS, it doesn't stand the service up itself.
"""

import socket
import ssl
from pathlib import Path

import httpx
import pytest

_DEV_CA_PATH = Path("/app/certs/dev-ca.pem")

pytestmark = pytest.mark.skipif(
    not _DEV_CA_PATH.exists(),
    reason="certs/dev-ca.pem not generated yet -- run scripts/generate_dev_tls_cert.py first",
)


def test_raw_tls_handshake_negotiates_tls_1_2_or_higher():
    ctx = ssl.create_default_context(cafile=str(_DEV_CA_PATH))
    with (
        socket.create_connection(("app-tls", 8443), timeout=5) as sock,
        ctx.wrap_socket(sock, server_hostname="app-tls") as ssock,
    ):
        version = ssock.version()
        assert version is not None
        # "TLSv1.3" / "TLSv1.2" -- string-sort happens to work for these two labels
        # specifically, but compare the actual minor version number to be explicit about it.
        assert version in ("TLSv1.2", "TLSv1.3")


def test_a_real_request_over_https_succeeds_trusting_the_dev_ca():
    trust_dev_ca = ssl.create_default_context(cafile=str(_DEV_CA_PATH))
    response = httpx.get("https://app-tls:8443/health", verify=trust_dev_ca)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_same_request_is_rejected_by_the_system_trust_store():
    """Negative proof this is genuinely self-signed, not accidentally trusted by something
    else -- the system's real CA bundle has never heard of this dev CA."""
    with pytest.raises(httpx.ConnectError):
        httpx.get("https://app-tls:8443/health", verify=True)
