"""PostgreSQL database connection and initialization."""

import logging
import os
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from psycopg2.pool import SimpleConnectionPool


logger = logging.getLogger(__name__)

_pool: Optional[SimpleConnectionPool] = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _load_dotenv(path: Path) -> None:
    """Load .env file into environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_connection():
    """Get a database connection from the pool."""
    global _pool
    if _pool is None:
        init_db()
    return _pool.connection()


def init_db() -> None:
    """Initialize the connection pool and create tables."""
    global _pool

    _load_dotenv(Path.cwd() / ".env")
    _load_dotenv(Path(__file__).parent.parent / ".env")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL not set. Configure it in .env or environment.\n"
            "Example: DATABASE_URL=postgresql://postgres:postgres@localhost:5432/coding_agent"
        )

    # Create connection pool
    if _pool is None:
        _pool = SimpleConnectionPool(1, 10, database_url)
        logger.info("Database connection pool created")

    # Run migrations
    _run_migrations()


def _run_migrations() -> None:
    """Run SQL migration files."""
    conn = _pool.connection()
    try:
        with conn.cursor() as cur:
            # Read and execute migration files
            migration_file = MIGRATIONS_DIR / "001_init.sql"
            if migration_file.exists():
                sql = migration_file.read_text(encoding="utf-8")
                cur.execute(sql)
                logger.info("Applied migration: 001_init.sql")
        conn.commit()
    except Exception as error:
        conn.rollback()
        logger.error("Migration failed: %s", error)
        raise
    finally:
        conn.close()


def close_pool() -> None:
    """Close all connections in the pool."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")
