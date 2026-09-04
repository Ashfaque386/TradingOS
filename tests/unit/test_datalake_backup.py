"""REL-081: `src/data/datalake/backup.py::run_backup_cycle` unit tests -- the real logic
extracted (unchanged) from `scripts/backup_data_lake.py::main()`, now shared by that script and
`src.agents.scheduler.run_data_lake_backup_job`. No mocking: writes a real small Parquet file and
runs the real walk/copy/hash/DuckDB-validate/manifest-write pass against it.
"""

import json

import polars as pl

from src.data.datalake.backup import run_backup_cycle


def _write_parquet(path, rows: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["TEST"] * rows,
            "close": [100.0 + i for i in range(rows)],
        }
    ).write_parquet(path)


def test_empty_lake_is_a_real_honest_failure(tmp_path):
    result = run_backup_cycle(tmp_path / "ohlcv_daily")
    assert result.files_found == 0
    assert result.files_backed_up == 0
    assert result.failures  # non-empty -- an empty lake is worth flagging, not silent success


def test_real_files_are_copied_hashed_and_manifest_written(tmp_path):
    lake_root = tmp_path / "ohlcv_daily"
    _write_parquet(lake_root / "2026" / "01" / "TCS.parquet")
    _write_parquet(lake_root / "2026" / "01" / "INFY.parquet", rows=5)

    result = run_backup_cycle(lake_root)

    assert result.files_found == 2
    assert result.files_backed_up == 2
    assert result.failures == []
    assert result.manifest_path.exists()

    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["file_count"] == 2
    row_counts = {entry["relative_path"]: entry["row_count"] for entry in manifest["files"]}
    assert row_counts[str((lake_root / "2026" / "01" / "TCS.parquet").relative_to(lake_root))] == 3
    assert row_counts[str((lake_root / "2026" / "01" / "INFY.parquet").relative_to(lake_root))] == 5

    # Real backed-up files actually exist on disk under the dated snapshot directory.
    backed_up = list(result.backup_root.rglob("*.parquet"))
    assert len(backed_up) == 2
