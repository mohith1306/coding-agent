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


MAX_CONSECUTIVE_FAILURES = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill missing memory embeddings")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="Max rows to process (0 = all)")
    args = parser.parse_args()

    if args.batch_size <= 0:
        print("ERROR: --batch-size must be positive")
        return 1
    if args.limit < 0:
        print("ERROR: --limit must be non-negative")
        return 1

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
    consecutive_failures = 0

    while True:
        # Remaining allowance computed BEFORE fetching so --limit is exact.
        remaining = args.batch_size
        if args.limit:
            remaining = args.limit - processed
            if remaining <= 0:
                break
            remaining = min(remaining, args.batch_size)

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
                    (remaining,),
                )
                batch = cur.fetchall()
        finally:
            return_connection(conn)

        if not batch:
            break

        texts = [row[1] for row in batch]
        vectors = client.embed_batch(texts)

        batch_embedded = sum(1 for v in vectors if v and len(v) == embed_dim())
        if batch_embedded == 0:
            # No progress: API outage/rate-limit would otherwise reselect
            # the same NULL rows forever.
            consecutive_failures += 1
            logger.warning(
                "Batch embedded 0/%d (failure %d/%d)",
                len(batch), consecutive_failures, MAX_CONSECUTIVE_FAILURES,
            )
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"ERROR: {consecutive_failures} consecutive batches embedded nothing; aborting")
                return 1
            continue
        consecutive_failures = 0

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
                processed += len(batch)
            conn.commit()
        except Exception as error:
            conn.rollback()
            # Rolled back: nothing was persisted, so report failure loudly
            # instead of printing Done/success or retrying the same rows.
            print(f"ERROR: batch update failed and was rolled back: {error}")
            return 1
        finally:
            return_connection(conn)

        logger.info("Progress: %d processed, %d embedded", processed, embedded)
        if len(batch) < remaining:
            break

    print(f"Done: {processed} processed, {embedded} embedded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
