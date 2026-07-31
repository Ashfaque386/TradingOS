from datetime import date

from sqlalchemy import CheckConstraint, Date, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class CorporateAction(Base, UUIDPKMixin, TimestampMixin):
    """DB-021 CORPORATE_ACTIONS (REL-010 E10.7). Real splits/bonuses/dividends, sourced from a
    real NSE corporate-actions feed (src/data/ingest/corporate_actions.py) -- previously zero
    code existed for this table, meaning backtests were not split/dividend-adjusted (a real
    correctness gap, closed by src/engine/backtest/corporate_actions_adjust.py consuming these
    rows).

    `ratio_numerator`/`ratio_denominator` are the OLD:NEW share-count ratio for SPLIT/BONUS rows
    (e.g. a 1:5 split, where each old share becomes 5 new shares, has numerator=1,
    denominator=5) -- back-adjust a pre-action price to the post-action scale by multiplying by
    (numerator/denominator): a share price is inversely proportional to share count, so 5x more
    shares means 1/5 the price. `dividend_amount` applies to DIVIDEND rows only; recorded for
    completeness but NOT applied as a price adjustment yet (no total-return series exists in
    this codebase -- see corporate_actions_adjust.py's own docstring for why that's an honest,
    stated gap)."""

    __tablename__ = "corporate_actions"
    __table_args__ = (
        CheckConstraint("action_type IN ('SPLIT', 'BONUS', 'DIVIDEND')", name="ck_action_type"),
        UniqueConstraint("symbol", "ex_date", "action_type"),
    )

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ratio_numerator: Mapped[float | None] = mapped_column(Numeric(10, 4))
    ratio_denominator: Mapped[float | None] = mapped_column(Numeric(10, 4))
    dividend_amount: Mapped[float | None] = mapped_column(Numeric(12, 4))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
