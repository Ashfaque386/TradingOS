"""Compliance checker (AGT-020, REL-006 E6.1): position-limit, circuit-filter, and naked-options
checks against the deterministic engine-layer core.
"""

from src.engine.risk.compliance_checker import (
    PLACEHOLDER_SEBI_POSITION_LIMITS,
    check_circuit_filter,
    check_position_limit,
    evaluate_compliance,
)
from src.engine.risk.naked_options_scanner import OptionLeg


def test_position_limit_passes_under_the_placeholder_ceiling():
    assert check_position_limit("RELIANCE", 1_000) is None


def test_position_limit_flags_a_quantity_over_the_placeholder_ceiling():
    limit = PLACEHOLDER_SEBI_POSITION_LIMITS["RELIANCE"]
    violation = check_position_limit("RELIANCE", limit + 1)
    assert violation is not None
    assert violation.rule == "SEBI_POSITION_LIMIT"


def test_position_limit_not_checked_for_a_symbol_with_no_placeholder_data():
    assert check_position_limit("UNKNOWN_SYMBOL", 10_000_000) is None


def test_circuit_filter_passes_within_the_band():
    assert check_circuit_filter("RELIANCE", 2500.0, 2550.0, band_pct=0.20) is None


def test_circuit_filter_flags_a_limit_price_outside_the_band():
    violation = check_circuit_filter("RELIANCE", 2500.0, 3500.0, band_pct=0.20)
    assert violation is not None
    assert violation.rule == "CIRCUIT_FILTER"


def test_circuit_filter_not_checked_for_a_market_order_with_no_limit_price():
    assert check_circuit_filter("RELIANCE", 2500.0, None) is None


def test_evaluate_compliance_passes_a_clean_equity_order():
    verdict = evaluate_compliance(
        symbol="RELIANCE", quantity=100, reference_price=2500.0, limit_price=2510.0
    )
    assert verdict.verdict == "Pass"
    assert verdict.violations == []
    assert verdict.position_limit_checked is True
    assert verdict.circuit_filter_checked is True


def test_evaluate_compliance_blocks_a_position_limit_breach():
    limit = PLACEHOLDER_SEBI_POSITION_LIMITS["TCS"]
    verdict = evaluate_compliance(symbol="TCS", quantity=limit + 1)
    assert verdict.verdict == "Block"
    assert any(v.rule == "SEBI_POSITION_LIMIT" for v in verdict.violations)


def test_evaluate_compliance_naked_options_not_checked_without_leg_data_and_still_passes():
    """Confirmed product decision: an F&O strategy with no structured OptionLeg data available
    (the real, pre-existing gap -- StrategyLogic is plain-text, not structured legs) Passes with
    naked_options_checked=False rather than Blocking outright."""
    verdict = evaluate_compliance(symbol="RELIANCE", quantity=100)
    assert verdict.naked_options_checked is False
    assert verdict.verdict == "Pass"


def test_evaluate_compliance_blocks_a_real_naked_short_option():
    naked_call = OptionLeg(
        symbol="RELIANCE", option_type="CE", strike=2600, side="sell", quantity=50
    )
    verdict = evaluate_compliance(symbol="RELIANCE", quantity=50, option_legs=[naked_call])
    assert verdict.naked_options_checked is True
    assert verdict.verdict == "Block"
    assert any(v.rule == "BR-02_NAKED_OPTIONS" for v in verdict.violations)


def test_evaluate_compliance_position_limit_not_checked_without_a_real_quantity():
    """The LangGraph node's case: no concrete order quantity exists yet at the pre-deployment
    strategy-review stage -- must not fabricate a check against a made-up quantity."""
    verdict = evaluate_compliance(symbol="RELIANCE")
    assert verdict.position_limit_checked is False
    assert verdict.verdict == "Pass"


def test_evaluate_compliance_passes_a_properly_hedged_option_spread():
    sold_call = OptionLeg(
        symbol="RELIANCE", option_type="CE", strike=2600, side="sell", quantity=50
    )
    hedge_call = OptionLeg(
        symbol="RELIANCE", option_type="CE", strike=2700, side="buy", quantity=50
    )
    verdict = evaluate_compliance(
        symbol="RELIANCE", quantity=50, option_legs=[sold_call, hedge_call]
    )
    assert verdict.naked_options_checked is True
    assert verdict.verdict == "Pass"
    assert verdict.violations == []
