"""No Naked Options scanner (Phase 3 Epic E3.4, Rule 2), per Phase_6_Trading_Engine_Design.md
§4 -- part of the **hardcoded** Risk & Portfolio Engine:

  "No Naked Options: Scans strategy logic. If options selling is involved, the engine verifies
  that a corresponding hedge (e.g., buying OTM wings) is executed simultaneously."

Operates on a strategy's declared list of option legs -- not the raw generated Python code
(that's the AST-level static safety scan in src/engine/tools/skills.py). A SOLD call must be
paired with a BOUGHT call at a strictly higher strike on the same underlying (a bear call
spread); a SOLD put must be paired with a BOUGHT put at a strictly lower strike (a bull put
spread). Either pairing caps the sold leg's otherwise theoretically unlimited loss -- the "OTM
wing" the design doc names. A bought option at the wrong side of the strike (e.g. a call bought
below a sold call's strike) doesn't count: it's a different position, not this leg's hedge.
"""

from dataclasses import dataclass
from typing import Literal

OptionType = Literal["CE", "PE"]  # NSE convention: Call European / Put European
Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class OptionLeg:
    symbol: str
    option_type: OptionType
    strike: float
    side: Side
    quantity: int


@dataclass(frozen=True)
class NakedOptionsScanResult:
    naked_legs: list[OptionLeg]

    @property
    def passed(self) -> bool:
        return len(self.naked_legs) == 0


def scan_for_naked_options(legs: list[OptionLeg]) -> NakedOptionsScanResult:
    """Flags every SOLD leg in `legs` that lacks a same-underlying, same-type hedge leg on the
    correct OTM side (higher strike for a sold call, lower strike for a sold put)."""
    naked_legs = [leg for leg in legs if leg.side == "sell" and not _has_hedge(leg, legs)]
    return NakedOptionsScanResult(naked_legs=naked_legs)


def _has_hedge(sold_leg: OptionLeg, legs: list[OptionLeg]) -> bool:
    for other in legs:
        if other is sold_leg or other.symbol != sold_leg.symbol:
            continue
        if other.side != "buy" or other.option_type != sold_leg.option_type:
            continue
        if sold_leg.option_type == "CE" and other.strike > sold_leg.strike:
            return True
        if sold_leg.option_type == "PE" and other.strike < sold_leg.strike:
            return True
    return False
