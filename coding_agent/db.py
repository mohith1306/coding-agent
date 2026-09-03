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


_vector_available: Optional[bool] = None
_vector_lock = threading.Lock()


def vector_available() -> bool:
    """Whether pgvector is usable (extension installed + embedding column present)."""
    global _vector_available
    if _vector_available is not None:
        return _vector_available
    with _vector_lock:
        if _vector_available is not None:
            return _vector_available
        available = False
        try:
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    has_ext = cur.fetchone() is not None
                    cur.execute(
                        """
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'agent_memory' AND column_name = 'embedding'
                        """
                    )
                    has_col = cur.fetchone() is not None
                    available = bool(has_ext and has_col)
            finally:
                return_connection(conn)
        except Exception as error:
            logger.warning("pgvector availability check failed: %s", error)
        _vector_available = available
        logger.info("pgvector available: %s", available)
        return available


def ensure_vector_column(dim: int) -> bool:
    """Create the embedding column (+ index) if pgvector exists.

    Returns True when the vector path is usable. If an embedding column
    already exists with a different dimension (model changed), the vector
    path is disabled rather than corrupting data — caller falls back to
    keyword search until a re-migration + backfill is run.
    """
    global _vector_available
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                if cur.fetchone() is None:
                    logger.info("pgvector extension missing; vector search disabled")
                    with _vector_lock:
                        _vector_available = False
                    return False
                cur.execute(
                    """
                    SELECT format_type(a.atttypid, a.atttypmod)
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    WHERE c.relname = 'agent_memory' AND a.attname = 'embedding'
                    """
                )
                row = cur.fetchone()
                if row:
                    existing = str(row[0])
                    if f"vector({dim})" not in existing:
                        logger.warning(
                            "embedding column is %s, expected vector(%d); "
                            "vector search disabled until re-migration",
                            existing, dim,
                        )
                        with _vector_lock:
                            _vector_available = False
                        return False
                else:
                    cur.execute(f"ALTER TABLE agent_memory ADD COLUMN embedding vector({dim})")
                    logger.info("Added agent_memory.embedding vector(%d)", dim)
                # Best-effort approximate index (hnsw needs pgvector >= 0.7).
                # Savepoint: a failed CREATE INDEX must not poison the txn.
                try:
                    cur.execute("SAVEPOINT vec_idx")
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_memory_embedding
                        ON agent_memory USING hnsw (embedding vector_cosine_ops)
                        """
                    )
                    cur.execute("RELEASE SAVEPOINT vec_idx")
                except Exception as index_error:
                    cur.execute("ROLLBACK TO SAVEPOINT vec_idx")
                    logger.info("Skipping hnsw index (%s); exact scan will be used", index_error)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            return_connection(conn)
        with _vector_lock:
            _vector_available = True
        return True
    except Exception as error:
        logger.warning("ensure_vector_column failed: %s", error)
        with _vector_lock:
            _vector_available = False
        return False


def reset_vector_cache() -> None:
    """Reset cached availability (tests only)."""
    global _vector_available
    with _vector_lock:
        _vector_available = None


def close_pool() -> None:
    """Close all connections in the pool."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None
            logger.info("Database connection pool closed")
