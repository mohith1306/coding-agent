#!/usr/bin/env python3
"""Backfill missing embeddings for existing agent_memory rows.

Usage:
    python3 scripts/backfill_embeddings.py [--batch-size 20] [--limit 0]

Embeds rows with NULL embedding in batches. Safe to re-run (skips
rows that already have vectors). Exits non-zero when the vector
path is unavailable (no pgvector / no API key).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("backfill")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill missing memory embeddings")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="Max rows to process (0 = all)")
    args = parser.parse_args()

    from coding_agent.db import ensure_vector_column, get_connection, init_db, return_connection
    from coding_agent.embeddings import EmbeddingClient, embed_dim, embeddings_enabled, to_pgvector

    if not embeddings_enabled():
        print("ERROR: embeddings disabled (set OPENROUTER_API_KEY, unset CODING_AGENT_EMBEDDINGS=off)")
        return 1

    init_db()
    if not ensure_vector_column(embed_dim()):
        print("ERROR: vector column unavailable (pgvector missing or dim mismatch)")
        return 1

    client = EmbeddingClient()
    processed = 0
    embedded = 0

    while True:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, content FROM agent_memory
                    WHERE embedding IS NULL
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (args.batch_size,),
                )
                batch = cur.fetchall()
        finally:
            return_connection(conn)

        if not batch:
            break

        texts = [row[1] for row in batch]
        vectors = client.embed_batch(texts)

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                for (row_id, _), vec in zip(batch, vectors):
                    if vec and len(vec) == embed_dim():
                        cur.execute(
                            "UPDATE agent_memory SET embedding = %s::vector WHERE id = %s",
                            (to_pgvector(vec), row_id),
                        )
                        embedded += 1
                    processed += 1
            conn.commit()
        except Exception as error:
            conn.rollback()
            logger.warning("Batch update failed: %s", error)
        finally:
            return_connection(conn)

        logger.info("Progress: %d processed, %d embedded", processed, embedded)
        if args.limit and processed >= args.limit:
            break
        if len(batch) < args.batch_size:
            break

    print(f"Done: {processed} processed, {embedded} embedded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
