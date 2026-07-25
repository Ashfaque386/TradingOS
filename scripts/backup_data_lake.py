"""Nightly Parquet snapshot backup job with DuckDB checksum validation (Phase 1 Epic E1.3 exit
criterion, Phase_14_Master_Development_Roadmap.md §2.2 -- mitigates the "Data Lake Corruption"
risk named in Phase_9_Master_Implementation_Guide.md §5).

Real behavior, no fabricated success:
  1. Walks `Settings.data_lake_root` for every real `*.parquet` file (today: the E1.3 EOD
     ingestion output under `ohlcv_daily/<year>/<month>/<symbol>.parquet`).
  2. Copies each to a dated snapshot directory (`{data_lake_root.parent}/backups/<YYYY-MM-DD>/`),
     preserving its relative partition path.
  3. Hashes both the source and the copied file (SHA-256) and compares them -- catches
     corruption introduced by the copy itself, not just a hypothetical future one.
  4. Opens each copied file with DuckDB and runs a real `SELECT COUNT(*)` against it -- proves
     the backup is a genuinely readable, structurally valid Parquet file, not just a
     byte-for-byte copy of something already broken. This is the "DuckDB checksum validation"
     step the roadmap's exit criterion names.
  5. Writes a JSON manifest (`_manifest.json` in the snapshot directory) recording every file's
     relative path, byte size, SHA-256, and row count -- a real, inspectable record, not just a
     console log that vanishes.

Exits non-zero if the data lake is empty (nothing to back up is itself worth flagging, not
silently treated as success) or if any file fails either the hash or DuckDB read-back check.

No scheduler exists yet to run this automatically (Phase_14 REL-005 E5.6) -- meant to run once
per real day via `docker exec tradingos-app python scripts/backup_data_lake.py`, same manual
pattern as scripts/run_daily_shadow_mode.py until a real Scheduler exists to replace it.
"""

import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from src.core.config import get_settings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duckdb_row_count(path: Path) -> int:
    with duckdb.connect() as conn:
        result = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{path.as_posix()}')").fetchone()
    assert result is not None
    return int(result[0])


def main() -> int:
    settings = get_settings()
    lake_root = settings.data_lake_root
    source_files = sorted(lake_root.rglob("*.parquet"))

    if not source_files:
        print(f"No Parquet files found under {lake_root} -- nothing to back up.")
        return 1

    snapshot_date = datetime.now(UTC).date().isoformat()
    backup_root = lake_root.parent / "backups" / snapshot_date
    backup_root.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, object]] = []
    failures: list[str] = []

    for source_path in source_files:
        relative_path = source_path.relative_to(lake_root)
        dest_path = backup_root / relative_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        source_hash = _sha256(source_path)
        shutil.copy2(source_path, dest_path)
        dest_hash = _sha256(dest_path)

        if source_hash != dest_hash:
            failures.append(f"{relative_path}: SHA-256 mismatch after copy (source != backup)")
            continue

        try:
            row_count = _duckdb_row_count(dest_path)
        except duckdb.Error as exc:
            failures.append(f"{relative_path}: DuckDB could not read the backed-up file -- {exc}")
            continue

        manifest.append(
            {
                "relative_path": str(relative_path),
                "size_bytes": dest_path.stat().st_size,
                "sha256": dest_hash,
                "row_count": row_count,
            }
        )

    manifest_path = backup_root / "_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "snapshot_date": snapshot_date,
                "source_root": str(lake_root),
                "file_count": len(manifest),
                "failure_count": len(failures),
                "files": manifest,
                "failures": failures,
            },
            indent=2,
        )
    )

    print(f"Backed up {len(manifest)} of {len(source_files)} Parquet file(s) to {backup_root}")
    print(f"Manifest: {manifest_path}")
    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("All backed-up files passed SHA-256 + DuckDB read-back validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
