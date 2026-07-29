"""One-time, idempotent setup for the MLflow tracking server's Postgres backend store
(REL-008, see docker-compose.yml's `mlflow` service and src/core/config.py::mlflow_tracking_uri).

MLflow gets its own Postgres *database* (`mlflow`), not a schema inside `tradingos` -- a clean
backup/migration boundary, since MLflow runs its own internal Alembic migrations against whatever
backend-store URI it's given and expects to own the full schema search path.

Because the existing `postgres_data` named volume already has data, Postgres's
`/docker-entrypoint-initdb.d/` auto-init mechanism will NOT run for this new database (that only
fires against a fresh, empty volume) -- this script does the `CREATE DATABASE` for real instead.

Run once via `docker compose exec app python scripts/setup_mlflow_database.py`, before
`docker compose up mlflow` -- the mlflow server container will fail to start cleanly against a
backend-store database that doesn't exist yet.
"""

from sqlalchemy import create_engine, text

from src.core.config import get_settings

MLFLOW_DATABASE_NAME = "mlflow"


def main() -> None:
    settings = get_settings()
    # Connect to the existing `tradingos` database (any existing database works for issuing
    # CREATE DATABASE, as long as the connection is autocommit -- it cannot run inside a
    # transaction block, which SQLAlchemy's default isolation level would otherwise wrap it in).
    engine = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": MLFLOW_DATABASE_NAME},
        ).scalar()

        if exists:
            print(f"Database {MLFLOW_DATABASE_NAME!r} already exists -- nothing to do.")
            return

        conn.execute(text(f"CREATE DATABASE {MLFLOW_DATABASE_NAME}"))
        print(f"Created database {MLFLOW_DATABASE_NAME!r} for the MLflow tracking server.")


if __name__ == "__main__":
    main()
