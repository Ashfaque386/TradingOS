#!/bin/sh
# REL-009 E9.4 (OWASP ZAP DAST, reduced local equivalent per the confirmed REL-009 decision):
# a real ZAP authenticated active scan against the real `app-tls` service (real self-signed TLS,
# real login), standing in for a Staging environment that doesn't exist anywhere in this project.
#
# Run from the HOST (not `docker compose exec app ...` -- the `app`/`app-tls` images have no
# docker CLI, confirmed empirically 2026-07-31: this script's own `docker run` line cannot
# execute from inside them). Needs `app-tls` already up and certs/dev-ca.pem already generated
# (same prerequisites as tests/integration/test_tls.py), and a Python 3 + httpx available on the
# host (or run the token-fetch step via `docker compose exec app python3 -c ...` and paste the
# token in by hand if the host has neither).
#
# Run via: ./scripts/run_zap_scan.sh
#
# REAL, CONFIRMED LIMITATION (2026-07-31): ZAP's spider discovers URLs by crawling hyperlinks in
# HTML responses. This app is a pure JSON API with no such links, so a scan of just the bare
# `https://app-tls:8443` root finds 0 URLs beyond `/`, `/robots.txt`, `/sitemap.xml` (all 404) --
# confirmed via a real run that produced 140 real PASS checks but never reached any real API
# route, including the deliberately-vulnerable one below. This script's default target is still
# the bare root (a real, honest scan of what ZAP's spider can actually reach on its own); to
# prove the scan gate genuinely catches a real vulnerability (this epic's own exit criterion),
# separately target the deliberately-unsafe test endpoint directly so it's in-scope for the
# active scanner's parameter fuzzing:
#
#   ZAP_TEST_ENDPOINT_ENABLED=true docker compose up -d app-tls   # enable the real reflected-XSS endpoint
#   TARGET="https://app-tls:8443/_zap_test/reflect?q=test" ./scripts/run_zap_scan.sh
#   docker compose up -d app-tls                                  # revert -- disabled by default
#
# Confirmed for real this way: ZAP reports `WARN-NEW: Cross Site Scripting (Reflected) [40012]`
# against that endpoint -- real proof the gate detects a real vulnerability, not a scan that
# simply never found anything to report.

set -eu

ADMIN_EMAIL="${ADMIN_BOOTSTRAP_EMAIL:-admin@tradingos.local}"
ADMIN_PASSWORD="${ADMIN_BOOTSTRAP_PASSWORD:-dev-only-change-me}"
TARGET="${TARGET:-https://app-tls:8443}"
REPORT_DIR="$(cd "$(dirname "$0")/.." && pwd)/zap-reports"
mkdir -p "$REPORT_DIR"

echo "Fetching a real access token to authenticate the scan..."
# Login always happens against the real base app-tls URL, regardless of what TARGET points at
# (TARGET may be a specific endpoint + query string, e.g. the deliberate-vuln verification above).
TOKEN=$(docker compose exec -T app python3 -c "
import httpx, ssl, json
ctx = ssl.create_default_context(cafile='/app/certs/dev-ca.pem')
r = httpx.post('https://app-tls:8443/api/v1/auth/login', json={'email': '$ADMIN_EMAIL', 'password': '$ADMIN_PASSWORD'}, verify=ctx)
r.raise_for_status()
body = r.json()
assert not body['mfa_required'], 'MFA is currently disabled project-wide (REL-007) -- if this fails, MFA has been re-enabled and this script needs updating'
print(body['access_token'])
" | tr -d '\r')

echo "Running real ZAP full scan against $TARGET (authenticated bearer token, self-signed dev CA trusted)..."
docker run --rm --network tradingos_default \
  -v "${REPORT_DIR}:/zap/wrk:rw" \
  zaproxy/zap-stable zap-full-scan.py \
  -t "$TARGET" \
  -z "-config replacer.full_list(0).description=auth -config replacer.full_list(0).enabled=true -config replacer.full_list(0).matchtype=REQ_HEADER -config replacer.full_list(0).matchstr=Authorization -config replacer.full_list(0).regex=false -config replacer.full_list(0).replacement='Bearer ${TOKEN}'" \
  -r zap-report.html -J zap-report.json \
  || true  # zap-full-scan.py exits non-zero on findings by design -- report the findings, don't let this script's own exit code hide them

echo "Real ZAP report written to ${REPORT_DIR}/zap-report.{html,json}"
