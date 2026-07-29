"""src/core/policy.py unit tests (REL-007 E7.5, SEC-017) -- pure enforcer logic against the real
policy.csv/model.conf files, no HTTP/DB involved.
"""

from src.core.policy import is_allowed


def test_a_granted_role_route_method_combination_is_allowed():
    assert is_allowed("SystemAdministrator", "/api/v1/users", "GET") is True


def test_an_ungranted_role_is_denied():
    assert is_allowed("PortfolioManager", "/api/v1/users", "GET") is False


def test_method_matters_not_just_role_and_route():
    assert is_allowed("RiskManager", "/api/v1/system/kill-switch", "POST") is True
    assert is_allowed("RiskManager", "/api/v1/system/kill-switch", "DELETE") is False


def test_an_entirely_unknown_route_is_denied_for_every_role():
    assert is_allowed("SystemAdministrator", "/api/v1/nonexistent", "GET") is False


def test_method_is_case_insensitive():
    assert is_allowed("SystemAdministrator", "/api/v1/users", "get") is True


def test_a_route_with_a_real_path_param_placeholder_matches_the_template_exactly():
    assert (
        is_allowed("SystemAdministrator", "/api/v1/strategies/{strategy_id}/promote", "POST")
        is True
    )
    # The template, not a real substituted UUID -- confirms this is exact-match, not a glob that
    # would also (incorrectly) match a literal path segment named "{strategy_id}".
    assert (
        is_allowed(
            "SystemAdministrator",
            "/api/v1/strategies/11111111-1111-1111-1111-111111111111/promote",
            "POST",
        )
        is False
    )
