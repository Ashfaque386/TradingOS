"""Pure-logic MFA unit tests (REL-007 E7.1) -- the enroll/confirm/verify/disable flows
themselves need real Postgres + real Vault and live in tests/integration/test_mfa_api.py.
"""

import pytest
from pydantic import ValidationError

from src.api.routers.mfa import VerifyRequest
from src.core.security import MFA_MANDATORY_ROLES


def test_mfa_enforcement_is_currently_disabled_by_explicit_user_request():
    """MFA_MANDATORY_ROLES is temporarily empty (disabled 2026-07-28, per explicit user
    request) -- the enroll/confirm/verify machinery underneath is untouched and still fully
    real/tested (see tests/integration/test_mfa_api.py, which exercises it directly via
    create_mfa_pending_token rather than through this gate). Re-enabling is a one-line change in
    src/core/security.py; when that happens, restore this test to assert the real SEC-014 role
    set (SystemAdministrator/PortfolioManager/RiskManager, not ReadOnlyAuditor) instead."""
    assert frozenset() == MFA_MANDATORY_ROLES


def test_verify_request_accepts_totp_code_only():
    req = VerifyRequest(totp_code="123456")
    assert req.totp_code == "123456"
    assert req.backup_code is None


def test_verify_request_accepts_backup_code_only():
    req = VerifyRequest(backup_code="abcdef1234")
    assert req.backup_code == "abcdef1234"
    assert req.totp_code is None


def test_verify_request_rejects_neither_factor():
    with pytest.raises(ValidationError):
        VerifyRequest()


def test_verify_request_rejects_both_factors_at_once():
    with pytest.raises(ValidationError):
        VerifyRequest(totp_code="123456", backup_code="abcdef1234")
