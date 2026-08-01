"""Compliance checks (Phase 4 AI Agent Design §20, AGT-020; REL-006 E6.1) -- part of the
**hardcoded** Risk & Portfolio Engine, same package/style as `naked_options_scanner.py` and
`kill_switch_service.py`.

Three checks, per Phase_14_Master_Development_Roadmap.md §7 E6.1:
  1. SEBI position-limit check -- against `PLACEHOLDER_SEBI_POSITION_LIMITS` below.
  2. Circuit-filter (price-band) check -- against `PLACEHOLDER_CIRCUIT_BAND_PCT` below.
  3. No-naked-options (Business Rule 2) -- delegates to `naked_options_scanner`, unmodified.

Honest gap, confirmed during REL-006 research and RE-confirmed during REL-016 E16.4 (GLH-10),
still unchanged by this file: no real SEBI position-limit or circuit-filter feed exists anywhere
in this codebase, config, or DB, and none is legitimately available to integrate. SEBI itself is
a regulator, not a data provider -- it publishes no live per-client/per-symbol position-limit API
at all; individual position data is confidential to the broker/clearing corp, never broadcast.
For circuit-filter bands, NSE's own website exposes per-symbol data, but every real access path
found (nsepython, nsetools, nsepy, NseIndiaApi) is an unofficial scraper of nseindia.com with no
SEBI/NSE endorsement, subject to anti-bot blocking and undocumented breaking changes -- not a
dependency this codebase's own "real code, real reliability" bar would accept for a live
risk-compliance gate. Commercial vendors (TrueData, Global Datafeeds, Breeze, etc.) do offer real
paid feeds, but adopting one is a budget/procurement decision, not a code change this pass can
make unilaterally. This is therefore closed out as a permanent, documented constraint (GLH-10),
not an indefinitely-open item -- re-open only if a genuine official feed or an approved paid
vendor contract materializes. The two placeholder tables below remain the right honest choice:
real code, real enforcement, real tests, but the reference data itself is illustrative, not a
live regulatory feed. Scoped to the 5 symbols the data lake already has real OHLCV for (confirmed
by the user as the intended REL-006 scope, rather than a broader config-driven table). Extend
this dict if a real feed ever does become available; don't rebuild the checking logic around it.

Per the confirmed product decision for REL-006: when naked-options exposure can't be verified
(no structured `OptionLeg` data available -- e.g. StrategyLogic is plain-text/code, not
structured legs, the same gap already documented in `src/agents/nodes/risk_manager.py`), this
checker reports `naked_options_checked=False` and does NOT fail the verdict on that basis alone
-- matching `RiskAssessment`'s established "never fabricate an unconditional Pass on unchecked
data, but don't block on an inability to check either" pattern.
"""

from dataclasses import dataclass, field
from typing import Literal

from src.engine.risk.naked_options_scanner import OptionLeg, scan_for_naked_options

# NOT a live SEBI/exchange feed -- no such feed exists anywhere in this codebase, config, or DB
# (confirmed by REL-006 research). Illustrative net-quantity ceilings for the 5 symbols the data
# lake already has real OHLCV for. Real code, real tests, real enforcement against this data --
# but the data itself is not live.
PLACEHOLDER_SEBI_POSITION_LIMITS: dict[str, int] = {
    "RELIANCE": 50_000,
    "TCS": 40_000,
    "INFY": 60_000,
    "HDFCBANK": 55_000,
    "ICICIBANK": 55_000,
}

# NSE's commonly published default equity circuit band -- illustrative default, not fetched from
# a live per-symbol circular. A real implementation would look this up per-symbol per-day.
PLACEHOLDER_CIRCUIT_BAND_PCT = 0.20


@dataclass(frozen=True)
class ComplianceViolation:
    rule: str  # "BR-02_NAKED_OPTIONS" | "SEBI_POSITION_LIMIT" | "CIRCUIT_FILTER"
    detail: str
    remediation: str


@dataclass(frozen=True)
class ComplianceVerdict:
    """Engine-layer dataclass -- src/agents/state.py defines its own Pydantic StrictModel twin
    of the same name for the LangGraph state (same "two same-named classes in different layers"
    precedent this codebase already has for EquityCurvePoint, in src/agents/state.py and
    src/api/routers/strategies.py independently)."""

    verdict: Literal["Pass", "Block"]
    violations: list[ComplianceViolation] = field(default_factory=list)
    naked_options_checked: bool = False
    position_limit_checked: bool = False
    circuit_filter_checked: bool = False


def check_position_limit(
    symbol: str, quantity: int, limits: dict[str, int] | None = None
) -> ComplianceViolation | None:
    limits = PLACEHOLDER_SEBI_POSITION_LIMITS if limits is None else limits
    limit = limits.get(symbol)
    if limit is None:
        return None  # no placeholder data for this symbol -- not checked, not fabricated
    if abs(quantity) > limit:
        return ComplianceViolation(
            rule="SEBI_POSITION_LIMIT",
            detail=f"{symbol}: requested quantity {quantity} exceeds placeholder limit {limit}",
            remediation=f"Reduce order quantity to at most {limit} for {symbol}",
        )
    return None


def check_circuit_filter(
    symbol: str,
    reference_price: float,
    limit_price: float | None,
    band_pct: float = PLACEHOLDER_CIRCUIT_BAND_PCT,
) -> ComplianceViolation | None:
    if limit_price is None:
        return None  # market orders have no limit price to band-check
    upper = reference_price * (1 + band_pct)
    lower = reference_price * (1 - band_pct)
    if not (lower <= limit_price <= upper):
        return ComplianceViolation(
            rule="CIRCUIT_FILTER",
            detail=(
                f"{symbol}: limit price {limit_price} outside the placeholder "
                f"+/-{band_pct:.0%} band [{lower:.2f}, {upper:.2f}] around reference "
                f"{reference_price}"
            ),
            remediation=f"Set a limit price within [{lower:.2f}, {upper:.2f}]",
        )
    return None


def evaluate_compliance(
    *,
    symbol: str,
    quantity: int | None = None,
    reference_price: float | None = None,
    limit_price: float | None = None,
    option_legs: list[OptionLeg] | None = None,
) -> ComplianceVerdict:
    """Runs whichever checks the supplied data actually supports. Never fabricates a Pass on a
    check it couldn't run -- the corresponding `*_checked` flag stays False instead, and the
    caller's narrative/UI is responsible for surfacing that honestly.

    `quantity=None` (the LangGraph node's case: no concrete order quantity exists yet at the
    pre-deployment strategy-review stage -- Position Sizing isn't threaded into
    TradingOSGraphState, the same gap already documented in risk_manager.py) skips the
    position-limit check entirely rather than fabricating a check against a made-up quantity
    like 0. The live execution pipeline always has a real `TradeSignal.quantity`, so this branch
    is a no-op there."""
    violations: list[ComplianceViolation] = []

    position_limit_checked = quantity is not None
    if position_limit_checked:
        position_violation = check_position_limit(symbol, quantity)  # type: ignore[arg-type]
        if position_violation is not None:
            violations.append(position_violation)

    circuit_filter_checked = limit_price is not None and reference_price is not None
    if circuit_filter_checked:
        circuit_violation = check_circuit_filter(
            symbol, reference_price, limit_price  # type: ignore[arg-type]
        )
        if circuit_violation is not None:
            violations.append(circuit_violation)

    naked_options_checked = option_legs is not None
    if naked_options_checked:
        scan_result = scan_for_naked_options(option_legs)  # type: ignore[arg-type]
        for leg in scan_result.naked_legs:
            violations.append(
                ComplianceViolation(
                    rule="BR-02_NAKED_OPTIONS",
                    detail=(
                        f"{leg.symbol} {leg.option_type} strike {leg.strike}: sold leg has no "
                        f"same-underlying OTM hedge"
                    ),
                    remediation="Add a same-underlying, same-type hedge leg at the correct OTM "
                    "strike, or remove this leg",
                )
            )
    # naked_options_checked is False (not verified) does NOT itself produce a violation -- per
    # the confirmed product decision, an unverifiable check reports honestly, it doesn't block.

    verdict: Literal["Pass", "Block"] = "Block" if violations else "Pass"
    return ComplianceVerdict(
        verdict=verdict,
        violations=violations,
        naked_options_checked=naked_options_checked,
        position_limit_checked=position_limit_checked,
        circuit_filter_checked=circuit_filter_checked,
    )
