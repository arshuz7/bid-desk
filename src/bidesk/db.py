"""Database access. For now: applying the numbered migrations in `sql/`.

Usage: python -m bidesk.db migrate
"""

import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg

from bidesk.config import database_url

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


def migration_files(sql_dir: Path = SQL_DIR) -> list[Path]:
    """The `NNNN_name.sql` files in version order."""
    files = sorted(sql_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    versions = [f.name[:4] for f in files]
    if len(set(versions)) != len(versions):
        raise ValueError(f"two migrations share a number in {sql_dir}: {versions}")
    return files


def migrate(url: str, sql_dir: Path = SQL_DIR) -> list[str]:
    """Apply every migration not yet applied, each in its own transaction. Returns the names
    applied; running it again applies nothing."""
    applied: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(CREATE_MIGRATIONS_TABLE)
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in migration_files(sql_dir):
            version = path.name[:4]  # by number, so renaming an applied file never re-runs it
            if version in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())  # type: ignore[arg-type]
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied.append(path.name)
    return applied


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["migrate"]:
        print("usage: python -m bidesk.db migrate", file=sys.stderr)
        return 2
    applied = migrate(database_url())
    print("\n".join(f"applied {name}" for name in applied) or "database is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
