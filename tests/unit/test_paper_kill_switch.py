"""src/engine/paper_trading/paper_kill_switch.py unit tests (REL-034).

Confirms the one load-bearing correctness property: this is a genuinely SEPARATE
MaxDrawdownKillSwitch instance from src/engine/risk/kill_switch_service.py's shared production
singleton -- tripping/resetting one must never affect the other, except the documented
one-directional dependency (a tripped production switch also halts paper execution).
"""

from src.engine.paper_trading import paper_kill_switch
from src.engine.risk import kill_switch_service


def teardown_function() -> None:
    """Reset both singletons between tests -- module-level state, same convention every other
    test touching kill_switch_service's own singleton already has to follow."""
    paper_kill_switch.reset()
    kill_switch_service._kill_switch.reset()  # noqa: SLF001 -- test-only direct reset, no audit needed


def test_paper_switch_starts_armed():
    assert not paper_kill_switch.is_paper_trading_halted()


def test_paper_drawdown_breach_halts_paper_trading_only():
    switch = paper_kill_switch.get_paper_kill_switch()
    switch.update(100_000.0)  # peak
    switch.update(80_000.0)  # 20% drawdown > default 15% threshold

    assert paper_kill_switch.is_paper_trading_halted()
    assert not kill_switch_service.is_tripped()  # production switch untouched


def test_production_kill_switch_trip_also_halts_paper_trading():
    kill_switch_service._kill_switch.trip()  # noqa: SLF001 -- direct trip, no audit session needed here

    assert paper_kill_switch.is_paper_trading_halted()
    assert not paper_kill_switch.get_paper_kill_switch().triggered  # paper switch itself untouched


def test_update_and_check_returns_false_once_halted():
    assert paper_kill_switch.update_and_check(100_000.0) is True
    assert paper_kill_switch.update_and_check(80_000.0) is False


def test_reset_only_clears_the_paper_switch():
    switch = paper_kill_switch.get_paper_kill_switch()
    switch.update(100_000.0)
    switch.update(80_000.0)
    kill_switch_service._kill_switch.trip()  # noqa: SLF001

    paper_kill_switch.reset()

    assert not switch.triggered
    assert kill_switch_service.is_tripped()  # production switch stays tripped
