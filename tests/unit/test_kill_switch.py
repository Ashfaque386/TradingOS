"""Max Drawdown Kill Switch tests (Phase 3 Epic E3.4 exit criterion, Rule 1), per
Phase_6_Trading_Engine_Design.md §4: configurable threshold (default 15%), latches until reset.
"""

import pytest

from src.engine.risk.kill_switch import DEFAULT_KILL_SWITCH_THRESHOLD, MaxDrawdownKillSwitch


def test_default_threshold_is_15_percent():
    assert DEFAULT_KILL_SWITCH_THRESHOLD == 0.15


def test_not_triggered_below_threshold():
    switch = MaxDrawdownKillSwitch(threshold=0.15)
    switch.update(100_000)
    result = switch.update(90_000)  # 10% drawdown

    assert result.drawdown == pytest.approx(0.10)
    assert result.triggered is False
    assert switch.triggered is False


def test_triggers_at_exactly_the_threshold():
    switch = MaxDrawdownKillSwitch(threshold=0.15)
    switch.update(100_000)
    result = switch.update(85_000)  # exactly 15% drawdown

    assert result.drawdown == pytest.approx(0.15)
    assert result.triggered is True


def test_triggers_above_the_threshold():
    switch = MaxDrawdownKillSwitch(threshold=0.15)
    switch.update(100_000)
    result = switch.update(70_000)  # 30% drawdown

    assert result.triggered is True


def test_tracks_running_peak_not_just_the_first_value():
    switch = MaxDrawdownKillSwitch(threshold=0.15)
    switch.update(100_000)
    switch.update(120_000)  # new peak
    result = switch.update(105_000)  # 12.5% drawdown from the NEW peak, not the original 100k

    assert result.drawdown == pytest.approx((120_000 - 105_000) / 120_000)
    assert result.triggered is False


def test_latches_once_triggered_even_if_equity_recovers():
    switch = MaxDrawdownKillSwitch(threshold=0.15)
    switch.update(100_000)
    switch.update(80_000)  # 20% drawdown -- triggers
    assert switch.triggered is True

    result = switch.update(150_000)  # equity fully recovers past the original peak

    assert switch.triggered is True
    assert result.triggered is True


def test_reset_clears_the_latch_and_starts_a_fresh_peak():
    switch = MaxDrawdownKillSwitch(threshold=0.15)
    switch.update(100_000)
    switch.update(80_000)  # triggers
    assert switch.triggered is True

    switch.reset()
    assert switch.triggered is False

    result = switch.update(80_000)  # first update after reset establishes a fresh peak
    assert result.drawdown == pytest.approx(0.0)
    assert result.triggered is False


def test_custom_threshold_is_respected():
    switch = MaxDrawdownKillSwitch(threshold=0.05)
    switch.update(100_000)
    result = switch.update(94_000)  # 6% drawdown, above the tighter 5% threshold

    assert result.triggered is True


def test_manual_trip_forces_the_triggered_state_regardless_of_drawdown():
    switch = MaxDrawdownKillSwitch(threshold=0.15)
    switch.update(100_000)  # no drawdown at all yet

    switch.trip()

    assert switch.triggered is True
