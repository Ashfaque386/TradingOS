"""Generates a self-signed dev CA + server certificate for REL-007 E7.6 (SEC-023/024, reduced
local equivalent) -- real HTTPS on the `app-tls` compose service's externally-exposed port, no
host `openssl` dependency (this environment is a Windows host running Docker; `cryptography`,
already a pinned dependency for src/core/vault_transit.py, builds the certs directly).

Idempotent: does nothing if `certs/server.crt` already exists, unless `--force` is passed. Run
via `docker exec tradingos-app python scripts/generate_dev_tls_cert.py` (or on the host with a
local `cryptography` install) whenever certs need regenerating.

NOT a real CA anyone should trust -- see the CN below. Internal service-mesh mTLS (SEC-024) is
explicitly out of scope: it assumes a Kubernetes + Istio/Linkerd topology this project doesn't
have and won't (Docker Compose only, permanently). Datastore-level TLS (Postgres/Redis/Qdrant/
Vault) is also out of scope -- see docker-compose.yml's `app-tls` service comment for why.
"""

import argparse
import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

_CERTS_DIR = Path(__file__).resolve().parent.parent / "certs"
_CA_VALIDITY_DAYS = 365 * 10
_SERVER_VALIDITY_DAYS = 825  # under the ~825-day cap modern TLS clients enforce for leaf certs


def _write_private_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def generate(*, force: bool = False) -> None:
    _CERTS_DIR.mkdir(parents=True, exist_ok=True)
    server_crt_path = _CERTS_DIR / "server.crt"
    if server_crt_path.exists() and not force:
        print(f"{server_crt_path} already exists -- skipping (pass --force to regenerate).")
        return

    now = datetime.datetime.now(datetime.UTC)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name(
        [
            x509.NameAttribute(
                NameOID.COMMON_NAME, "TradingOS Dev CA -- DO NOT TRUST IN PRODUCTION"
            ),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TradingOS (local dev only)"),
        ]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=_CA_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = ec.generate_private_key(ec.SECP256R1())
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "app-tls")])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=_SERVER_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName("app"),
                    x509.DNSName("app-tls"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write_private_key(_CERTS_DIR / "dev-ca.key", ca_key)
    _write_cert(_CERTS_DIR / "dev-ca.pem", ca_cert)
    _write_private_key(_CERTS_DIR / "server.key", server_key)
    _write_cert(server_crt_path, server_cert)

    print(f"Wrote dev CA + server cert/key to {_CERTS_DIR}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Regenerate even if certs exist.")
    args = parser.parse_args()
    generate(force=args.force)
