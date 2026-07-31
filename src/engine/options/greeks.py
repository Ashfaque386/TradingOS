"""Real Black-Scholes implied-volatility solver (REL-010 E10.4).

Used only for brokers that don't return IV directly (Kite Connect's real `/instruments` +
`/quote` endpoints carry strike/OI/LTP but no Greeks at all). Upstox's real `/option/chain`
endpoint DOES return IV/Greeks directly (confirmed against Upstox's own docs) -- that adapter
parses Upstox's own real values instead of re-deriving them here.

Pure stdlib (`math.erf` for the standard normal CDF) -- no `scipy` dependency, which was removed
from this project entirely alongside the ML platform (Phase_5's removal, 2026-07-30). A
Newton-Raphson solve is more than adequate for a single-variable, well-behaved root find like
this.
"""

import math

_MAX_ITERATIONS = 100
_TOLERANCE = 1e-6
_MIN_VOLATILITY = 1e-4
_MAX_VOLATILITY = 5.0  # 500% -- a generous upper bound for a NIFTY/BANKNIFTY option


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_price(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    rate: float,
    volatility: float,
    option_type: str,
) -> float:
    if time_to_expiry_years <= 0 or volatility <= 0:
        # Real intrinsic value at/after expiry or with zero volatility -- not a fabricated price.
        intrinsic = max(spot - strike, 0.0) if option_type == "CE" else max(strike - spot, 0.0)
        return intrinsic

    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility**2) * time_to_expiry_years) / (
        volatility * math.sqrt(time_to_expiry_years)
    )
    d2 = d1 - volatility * math.sqrt(time_to_expiry_years)

    if option_type == "CE":
        return spot * _norm_cdf(d1) - strike * math.exp(-rate * time_to_expiry_years) * _norm_cdf(
            d2
        )
    return strike * math.exp(-rate * time_to_expiry_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def _vega(
    *, spot: float, strike: float, time_to_expiry_years: float, rate: float, volatility: float
) -> float:
    if time_to_expiry_years <= 0 or volatility <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility**2) * time_to_expiry_years) / (
        volatility * math.sqrt(time_to_expiry_years)
    )
    return spot * _norm_pdf(d1) * math.sqrt(time_to_expiry_years)


def implied_volatility(
    *,
    spot: float,
    strike: float,
    expiry_days: float,
    rate: float,
    option_price: float,
    option_type: str,
) -> float | None:
    """Newton-Raphson solve for the volatility that reprices `option_price` under Black-Scholes.
    Returns `None` (never a fabricated number) if the inputs are non-physical (non-positive
    price/spot/strike/expiry) or the solve fails to converge within `_MAX_ITERATIONS`."""
    if option_price <= 0 or spot <= 0 or strike <= 0 or expiry_days <= 0:
        return None

    time_to_expiry_years = expiry_days / 365.0
    volatility = 0.3  # a reasonable real-world starting guess for NSE equity/index options

    for _ in range(_MAX_ITERATIONS):
        price = _bs_price(
            spot=spot,
            strike=strike,
            time_to_expiry_years=time_to_expiry_years,
            rate=rate,
            volatility=volatility,
            option_type=option_type,
        )
        diff = price - option_price
        if abs(diff) < _TOLERANCE:
            return volatility

        vega = _vega(
            spot=spot,
            strike=strike,
            time_to_expiry_years=time_to_expiry_years,
            rate=rate,
            volatility=volatility,
        )
        if vega < _TOLERANCE:
            return None  # flat vega -- Newton-Raphson can't make progress, don't guess further

        volatility -= diff / vega
        volatility = max(_MIN_VOLATILITY, min(_MAX_VOLATILITY, volatility))

    return None  # did not converge within _MAX_ITERATIONS -- honestly unresolved, not guessed
