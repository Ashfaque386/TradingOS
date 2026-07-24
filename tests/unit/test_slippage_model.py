"""Slippage model unit tests (Phase 4 Epic E4.4): pure math, no broker/network involved -- these
verify the depth-walking logic against manually-derived reference figures, same convention as
tests/unit/test_friction.py's Indian tax math tests.
"""

import pytest

from src.brokers.base import DepthLevel
from src.engine.paper_trading.slippage_model import simulate_fill


def _levels(*price_qty_pairs: tuple[float, int]) -> list[DepthLevel]:
    return [DepthLevel(price=p, quantity=q, orders=1) for p, q in price_qty_pairs]


def test_fully_filled_at_a_single_level_has_zero_slippage():
    depth = _levels((100.0, 500))
    result = simulate_fill(side="BUY", quantity=200, depth=depth)

    assert result.filled_quantity == 200
    assert result.average_fill_price == 100.0
    assert result.slippage_bps == 0.0
    assert result.fully_filled is True


def test_buy_walks_multiple_ask_levels_and_computes_a_real_weighted_average():
    # 100 @ 50.00, then 50 more needed from the next level @ 50.10
    depth = _levels((50.00, 100), (50.10, 200))
    result = simulate_fill(side="BUY", quantity=150, depth=depth)

    expected_avg = (100 * 50.00 + 50 * 50.10) / 150
    assert result.filled_quantity == 150
    assert result.average_fill_price == pytest.approx(expected_avg)
    assert result.fully_filled is True
    # Paying more than the best (touch) price of 50.00 is a real cost.
    expected_bps = (expected_avg - 50.00) / 50.00 * 10_000
    assert result.slippage_bps == pytest.approx(expected_bps)
    assert result.slippage_bps > 0


def test_sell_walks_multiple_bid_levels_and_slippage_is_still_a_positive_cost():
    depth = _levels((49.90, 100), (49.80, 200))
    result = simulate_fill(side="SELL", quantity=150, depth=depth)

    expected_avg = (100 * 49.90 + 50 * 49.80) / 150
    assert result.average_fill_price == pytest.approx(expected_avg)
    # Receiving less than the best bid (49.90) is a real cost -- still reported as positive bps.
    assert result.slippage_bps > 0
    expected_bps = (49.90 - expected_avg) / 49.90 * 10_000
    assert result.slippage_bps == pytest.approx(expected_bps)


def test_quantity_exceeding_visible_depth_is_honestly_partially_filled():
    depth = _levels((50.00, 100), (50.10, 50))  # only 150 total visible liquidity
    result = simulate_fill(side="BUY", quantity=500, depth=depth)

    assert result.filled_quantity == 150
    assert result.fully_filled is False
    expected_avg = (100 * 50.00 + 50 * 50.10) / 150
    assert result.average_fill_price == pytest.approx(expected_avg)


def test_empty_depth_fills_nothing_rather_than_fabricating_a_price():
    result = simulate_fill(side="BUY", quantity=100, depth=[])
    assert result.filled_quantity == 0
    assert result.average_fill_price is None
    assert result.slippage_bps is None
    assert result.fully_filled is False


def test_a_zero_quantity_or_zero_price_level_is_skipped_not_divided_by():
    depth = _levels((0.0, 0), (50.00, 100))
    result = simulate_fill(side="BUY", quantity=50, depth=depth)
    assert result.filled_quantity == 50
    assert result.average_fill_price == 50.00


def test_negative_or_zero_requested_quantity_is_rejected():
    with pytest.raises(ValueError, match="quantity must be positive"):
        simulate_fill(side="BUY", quantity=0, depth=_levels((50.0, 100)))
