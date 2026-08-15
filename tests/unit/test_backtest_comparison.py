"""Multi-run backtest return-correlation tests (REL-069)."""

from src.engine.backtest.comparison import (
    MIN_OVERLAP_DAYS,
    EquityCurveSeries,
    compute_return_correlation_matrix,
)


def _series(run_id: str, equities: list[float], start_day: int = 1) -> EquityCurveSeries:
    dates = [f"2026-08-{start_day + i:02d}" for i in range(len(equities))]
    return EquityCurveSeries(run_id=run_id, points=list(zip(dates, equities, strict=True)))


def test_identical_curves_are_perfectly_correlated():
    equities = [100.0, 102.0, 101.0, 105.0, 103.0, 108.0, 106.0, 110.0, 109.0, 112.0, 115.0]
    a = _series("A", equities)
    b = _series("B", equities)

    matrix = compute_return_correlation_matrix([a, b])

    assert matrix[("A", "B")] is not None
    assert matrix[("A", "B")] == matrix[("B", "A")]
    assert abs(matrix[("A", "B")] - 1.0) < 1e-9


def test_inverted_curves_are_perfectly_anti_correlated():
    up = [100.0, 102.0, 101.0, 105.0, 103.0, 108.0, 106.0, 110.0, 109.0, 112.0, 115.0]
    down = [100.0]
    for i in range(1, len(up)):
        pct = (up[i] - up[i - 1]) / up[i - 1]
        down.append(down[-1] * (1 - pct))
    a = _series("A", up)
    b = _series("B", down)

    matrix = compute_return_correlation_matrix([a, b])

    assert matrix[("A", "B")] < -0.99


def test_self_correlation_is_always_one():
    a = _series("A", [100.0, 101.0, 99.0])
    matrix = compute_return_correlation_matrix([a])
    assert matrix[("A", "A")] == 1.0


def test_self_correlation_is_none_for_a_curve_with_no_return_days():
    a = _series("A", [100.0])
    matrix = compute_return_correlation_matrix([a])
    assert matrix[("A", "A")] is None


def test_insufficient_overlap_is_none_not_a_fabricated_zero():
    # Two runs whose real calendar windows barely overlap (well under MIN_OVERLAP_DAYS).
    a = _series("A", [100.0, 101.0, 102.0, 103.0], start_day=1)
    b = _series("B", [50.0, 51.0, 52.0, 53.0], start_day=4)

    matrix = compute_return_correlation_matrix([a, b])

    assert matrix[("A", "B")] is None
    assert matrix[("B", "A")] is None


def test_min_overlap_days_constant_is_ten():
    assert MIN_OVERLAP_DAYS == 10


def test_zero_variance_curve_yields_none_not_a_divide_by_zero_crash():
    flat = _series("A", [100.0] * 15)
    varying = _series("B", [100.0 + i for i in range(15)])

    matrix = compute_return_correlation_matrix([flat, varying])

    assert matrix[("A", "B")] is None
