"""REL-010 E10.4: real Black-Scholes IV solver, verified against a well-known textbook case
(S=100, K=100, T=1yr, r=5%, sigma=20% -> real call price ~10.4506, a commonly-cited reference
value for this exact parameter set)."""

from src.engine.options.greeks import implied_volatility


def test_recovers_the_known_volatility_from_a_textbook_call_price():
    iv = implied_volatility(
        spot=100.0,
        strike=100.0,
        expiry_days=365.0,
        rate=0.05,
        option_price=10.4506,
        option_type="CE",
    )
    assert iv is not None
    assert abs(iv - 0.20) < 0.001


def test_recovers_the_known_volatility_from_a_textbook_put_price():
    # Put-call parity for the same ATM case:
    # P = C - S + K*e^(-rT) ~= 10.4506 - 100 + 95.1229 = 5.5735
    iv = implied_volatility(
        spot=100.0,
        strike=100.0,
        expiry_days=365.0,
        rate=0.05,
        option_price=5.5735,
        option_type="PE",
    )
    assert iv is not None
    assert abs(iv - 0.20) < 0.001


def test_returns_none_for_a_non_physical_zero_price():
    assert (
        implied_volatility(
            spot=100.0,
            strike=100.0,
            expiry_days=30.0,
            rate=0.05,
            option_price=0.0,
            option_type="CE",
        )
        is None
    )


def test_returns_none_for_a_zero_expiry():
    assert (
        implied_volatility(
            spot=100.0, strike=100.0, expiry_days=0.0, rate=0.05, option_price=5.0, option_type="CE"
        )
        is None
    )


def test_returns_none_for_an_arbitrage_violating_price_too_high_for_any_volatility():
    # A call can never be worth more than the spot price itself -- no volatility reprices this.
    result = implied_volatility(
        spot=100.0, strike=100.0, expiry_days=30.0, rate=0.05, option_price=999.0, option_type="CE"
    )
    assert result is None
