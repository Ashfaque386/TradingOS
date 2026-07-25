from abc import ABC, abstractmethod
from datetime import date

import polars as pl

EOD_SCHEMA = ["symbol", "date", "open", "high", "low", "close", "volume"]


class EODDataSourceAdapter(ABC):
    """Produces long-format EOD OHLCV rows (columns: EOD_SCHEMA) for a symbol set and date range."""

    @abstractmethod
    def fetch(self, symbols: list[str], start: date, end: date) -> pl.DataFrame: ...
