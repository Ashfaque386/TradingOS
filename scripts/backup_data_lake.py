"""Nightly Parquet snapshot backup job with DuckDB checksum validation (Phase 1 Epic E1.3 exit
criterion, Phase_14_Master_Development_Roadmap.md §2.2 -- mitigates the "Data Lake Corruption"
risk named in Phase_9_Master_Implementation_Guide.md §5).

REL-081: the real logic moved (unchanged) to `src/data/datalake/backup.py::run_backup_cycle` --
see that module's own docstring for the 5 real steps. This script is now a thin CLI wrapper over
that same function, which is also what the in-process scheduler job
(src/agents/scheduler.py::run_data_lake_backup_job) calls. Kept as a manual/CLI escape hatch for
running an on-demand backup without going through the API:
    docker exec tradingos-app python scripts/backup_data_lake.py

Exits non-zero if the data lake is empty (nothing to back up is itself worth flagging, not
silently treated as success) or if any file fails either the hash or DuckDB read-back check.
"""

import sys

from src.core.config import get_settings
from src.data.datalake.backup import run_backup_cycle


def main() -> int:
    result = run_backup_cycle(get_settings().data_lake_root)

    print(
        f"Backed up {result.files_backed_up} of {result.files_found} Parquet file(s) "
        f"to {result.backup_root}"
    )
    print(f"Manifest: {result.manifest_path}")
    if result.failures:
        print(f"\n{len(result.failures)} FAILURE(S):")
        for failure in result.failures:
            print(f"  - {failure}")
        return 1

    print("All backed-up files passed SHA-256 + DuckDB read-back validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
