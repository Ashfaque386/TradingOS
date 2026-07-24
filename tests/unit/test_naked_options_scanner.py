"""No Naked Options scanner tests (Phase 3 Epic E3.4 exit criterion, Rule 2), per
Phase_6_Trading_Engine_Design.md §4: a sold option must have a corresponding OTM-wing hedge.
"""

from src.engine.risk.naked_options_scanner import OptionLeg, scan_for_naked_options


def test_naked_short_call_without_hedge_is_flagged():
    legs = [OptionLeg("NIFTY", "CE", strike=20000, side="sell", quantity=50)]

    result = scan_for_naked_options(legs)

    assert result.passed is False
    assert legs[0] in result.naked_legs


def test_short_call_with_higher_strike_hedge_passes_bear_call_spread():
    legs = [
        OptionLeg("NIFTY", "CE", strike=20000, side="sell", quantity=50),
        OptionLeg("NIFTY", "CE", strike=20200, side="buy", quantity=50),  # OTM wing above
    ]

    result = scan_for_naked_options(legs)

    assert result.passed is True
    assert result.naked_legs == []


def test_naked_short_put_without_hedge_is_flagged():
    legs = [OptionLeg("NIFTY", "PE", strike=19800, side="sell", quantity=50)]

    result = scan_for_naked_options(legs)

    assert result.passed is False
    assert legs[0] in result.naked_legs


def test_short_put_with_lower_strike_hedge_passes_bull_put_spread():
    legs = [
        OptionLeg("NIFTY", "PE", strike=19800, side="sell", quantity=50),
        OptionLeg("NIFTY", "PE", strike=19600, side="buy", quantity=50),  # OTM wing below
    ]

    result = scan_for_naked_options(legs)

    assert result.passed is True


def test_hedge_on_the_wrong_side_of_the_strike_does_not_count():
    # A bought call BELOW the sold call's strike is a different (safer, fully-covered) trade,
    # not this leg's OTM-wing hedge -- the scanner must not silently accept it as one.
    legs = [
        OptionLeg("NIFTY", "CE", strike=20000, side="sell", quantity=50),
        OptionLeg("NIFTY", "CE", strike=19800, side="buy", quantity=50),
    ]

    result = scan_for_naked_options(legs)

    assert result.passed is False


def test_hedge_on_a_different_underlying_does_not_count():
    legs = [
        OptionLeg("NIFTY", "CE", strike=20000, side="sell", quantity=50),
        OptionLeg("BANKNIFTY", "CE", strike=20200, side="buy", quantity=50),
    ]

    result = scan_for_naked_options(legs)

    assert result.passed is False


def test_multiple_legs_only_flags_the_naked_ones():
    hedged_sell = OptionLeg("NIFTY", "CE", strike=20000, side="sell", quantity=50)
    hedge = OptionLeg("NIFTY", "CE", strike=20200, side="buy", quantity=50)
    naked_sell = OptionLeg("BANKNIFTY", "PE", strike=45000, side="sell", quantity=25)

    result = scan_for_naked_options([hedged_sell, hedge, naked_sell])

    assert result.naked_legs == [naked_sell]
    assert result.passed is False


def test_buy_only_legs_are_never_flagged():
    legs = [
        OptionLeg("NIFTY", "CE", strike=20000, side="buy", quantity=50),
        OptionLeg("NIFTY", "PE", strike=19800, side="buy", quantity=50),
    ]

    result = scan_for_naked_options(legs)

    assert result.passed is True
