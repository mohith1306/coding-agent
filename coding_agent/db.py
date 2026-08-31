"""PostgreSQL database connection and initialization."""

import logging
import os
import threading
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from psycopg2.pool import ThreadedConnectionPool


logger = logging.getLogger(__name__)

_pool: Optional[ThreadedConnectionPool] = None
_pool_lock = threading.Lock()

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
    return _pool.getconn()


def return_connection(conn) -> None:
    """Return a connection to the pool."""
    global _pool
    if _pool is not None and conn is not None:
        try:
            _pool.putconn(conn)
        except Exception:
            logger.warning("Failed to return connection to pool")


def init_db() -> None:
    """Initialize the connection pool and run migrations."""
    global _pool

    with _pool_lock:
        if _pool is not None:
            return

    _load_dotenv(Path.cwd() / ".env")
    _load_dotenv(Path(__file__).parent.parent / ".env")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL not set. Configure it in .env or environment.\n"
            "Example: DATABASE_URL=postgresql://postgres:postgres@localhost:5432/coding_agent"
        )

    # Create threaded connection pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadedConnectionPool(1, 10, database_url)
            logger.info("Database connection pool created")

    # Run migrations
    _run_migrations()


def _run_migrations() -> None:
    """Discover and run all pending SQL migration files in order."""
    global _pool

    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            # Create migrations tracking table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(50) PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # Discover migration files
            migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
            for migration_file in migration_files:
                version = migration_file.stem
                # Check if already applied
                cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s",
                    (version,),
                )
                if cur.fetchone():
                    continue

                # Apply migration
                sql = migration_file.read_text(encoding="utf-8")
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
                logger.info("Applied migration: %s", version)

        conn.commit()
    except Exception as error:
        conn.rollback()
        logger.error("Migration failed: %s", error)
        raise
    finally:
        _pool.putconn(conn)


def close_pool() -> None:
    """Close all connections in the pool."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None
            logger.info("Database connection pool closed")
