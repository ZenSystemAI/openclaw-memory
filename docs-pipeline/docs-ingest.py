#!/usr/bin/env python3
"""Docs knowledge base ingest pipeline for Morpheus.

Usage:
    python3 docs-ingest.py --source n8n           # Ingest one source
    python3 docs-ingest.py --source all            # Ingest all sources
    python3 docs-ingest.py --source n8n --mode incremental  # Hash-based delta
    python3 docs-ingest.py --source n8n --mode full         # Delete + reindex
    python3 docs-ingest.py --stats                 # Show collection stats
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone

# Add pipeline dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from config import CLONE_DIR, LOG_DIR
from chunker import Chunk, chunk_markdown, chunk_openapi_yaml
from embedder import embed_texts
from qdrant_ops import (
    collection_info,
    delete_points,
    generate_point_id,
    get_existing_hashes,
    upsert_points,
)
from sources import ALL_SOURCES


def setup_logging(source_name: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"ingest_{source_name}_{timestamp}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ],
    )
    return logging.getLogger("docs-ingest")


def ingest_source(source_name: str, mode: str, log: logging.Logger) -> dict:
    """Ingest a single doc source. Returns stats dict."""
    source_cls = ALL_SOURCES.get(source_name)
    if not source_cls:
        log.error("Unknown source: %s (available: %s)", source_name, list(ALL_SOURCES.keys()))
        return {"error": f"Unknown source: {source_name}"}

    source = source_cls()
    stats = {
        "source": source_name,
        "mode": mode,
        "docs_fetched": 0,
        "chunks_total": 0,
        "chunks_new": 0,
        "chunks_unchanged": 0,
        "chunks_deleted": 0,
        "errors": 0,
    }

    # Step 1: Fetch docs
    log.info("=== Fetching %s docs ===", source_name)
    os.makedirs(CLONE_DIR, exist_ok=True)
    try:
        doc_files = source.fetch_docs()
    except Exception as e:
        log.error("Fetch failed for %s: %s", source_name, e)
        stats["errors"] += 1
        return stats

    stats["docs_fetched"] = len(doc_files)
    log.info("Fetched %d doc files from %s", len(doc_files), source_name)

    if not doc_files:
        log.warning("No docs found for %s — skipping", source_name)
        return stats

    # Step 2: Chunk all docs
    log.info("=== Chunking %s docs ===", source_name)
    all_chunks: list[tuple[Chunk, str, str]] = []  # (chunk, doc_path, url)

    for doc in doc_files:
        if doc.path.endswith((".yaml", ".yml")):
            chunks = chunk_openapi_yaml(doc.content, source_name)
        else:
            chunks = chunk_markdown(doc.content, source_name)

        for chunk in chunks:
            all_chunks.append((chunk, doc.path, doc.url))

    stats["chunks_total"] = len(all_chunks)
    log.info("Generated %d chunks from %d docs", len(all_chunks), len(doc_files))

    # Step 3: Incremental diff (if mode=incremental)
    new_hashes = {c.content_hash for c, _, _ in all_chunks}

    if mode == "incremental":
        log.info("=== Computing incremental diff ===")
        existing = get_existing_hashes(source_name)
        existing_hashes = set(existing.keys())

        to_add = [
            (c, dp, u) for c, dp, u in all_chunks
            if c.content_hash not in existing_hashes
        ]
        to_delete_ids = [
            pid for h, pid in existing.items()
            if h not in new_hashes
        ]
        stats["chunks_unchanged"] = len(all_chunks) - len(to_add)
        stats["chunks_deleted"] = len(to_delete_ids)
        stats["chunks_new"] = len(to_add)

        log.info(
            "Diff: %d new, %d unchanged, %d to delete",
            len(to_add), stats["chunks_unchanged"], len(to_delete_ids),
        )

        # Delete stale
        if to_delete_ids:
            log.info("Deleting %d stale points", len(to_delete_ids))
            delete_points(to_delete_ids)

        chunks_to_embed = to_add
    else:
        # Full mode: delete all existing, re-ingest everything
        log.info("=== Full re-index mode — deleting existing %s points ===", source_name)
        existing = get_existing_hashes(source_name)
        if existing:
            delete_points(list(existing.values()))
            log.info("Deleted %d existing points", len(existing))

        chunks_to_embed = all_chunks
        stats["chunks_new"] = len(all_chunks)
        stats["chunks_deleted"] = len(existing)

    if not chunks_to_embed:
        log.info("Nothing to embed — all chunks up to date")
        return stats

    # Step 4: Embed
    log.info("=== Embedding %d chunks ===", len(chunks_to_embed))
    texts = [c.text for c, _, _ in chunks_to_embed]
    try:
        embeddings = embed_texts(texts)
    except Exception as e:
        log.error("Embedding failed: %s", e)
        stats["errors"] += 1
        return stats

    # Step 5: Upsert to Qdrant (skip chunks that failed to embed)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    points = []
    embed_skipped = 0
    for (chunk, doc_path, url), embedding in zip(chunks_to_embed, embeddings):
        if embedding is None:
            embed_skipped += 1
            continue
        points.append({
            "id": generate_point_id(),
            "vector": embedding,
            "payload": {
                "text": chunk.text,
                "source": source_name,
                "doc_path": doc_path,
                "section": chunk.section,
                "url": url,
                "chunk_index": chunk.chunk_index,
                "content_hash": chunk.content_hash,
                "content_type": chunk.content_type,
                "doc_version": today,
                "indexed_at": now,
            },
        })

    if embed_skipped:
        log.warning("Skipped %d chunks that failed to embed", embed_skipped)

    if not points:
        log.warning("All chunks failed to embed — nothing to upsert")
        stats["errors"] += 1
        return stats

    log.info("=== Upserting %d points to Qdrant ===", len(points))

    try:
        upsert_points(points)
    except Exception as e:
        log.error("Upsert failed: %s", e)
        stats["errors"] += 1
        return stats

    log.info("=== Done: %s ===", source_name)
    return stats


def show_stats(log: logging.Logger):
    """Print collection stats."""
    info = collection_info()
    log.info("Collection: docs")
    log.info("Status: %s", info.get("status"))
    log.info("Points: %d", info.get("points_count", 0))
    log.info("Indexed vectors: %d", info.get("indexed_vectors_count", 0))

    # Count per source
    for source_name in ALL_SOURCES:
        hashes = get_existing_hashes(source_name)
        log.info("  %s: %d points", source_name, len(hashes))


def main():
    parser = argparse.ArgumentParser(description="Docs knowledge base ingest pipeline")
    parser.add_argument("--source", type=str, help="Source name or 'all'")
    parser.add_argument("--mode", type=str, default="incremental", choices=["incremental", "full"])
    parser.add_argument("--stats", action="store_true", help="Show collection stats")
    args = parser.parse_args()

    if args.stats:
        log = setup_logging("stats")
        show_stats(log)
        return

    if not args.source:
        parser.error("--source is required (or use --stats)")

    source_name = args.source.lower()
    log = setup_logging(source_name)

    if source_name == "all":
        sources = list(ALL_SOURCES.keys())
    else:
        sources = [source_name]

    all_stats = []
    for src in sources:
        log.info("=" * 60)
        log.info("Processing source: %s", src)
        log.info("=" * 60)
        stats = ingest_source(src, args.mode, log)
        all_stats.append(stats)
        log.info("Stats: %s", stats)

    # Summary
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)
    total_new = sum(s.get("chunks_new", 0) for s in all_stats)
    total_del = sum(s.get("chunks_deleted", 0) for s in all_stats)
    total_unchanged = sum(s.get("chunks_unchanged", 0) for s in all_stats)
    total_errors = sum(s.get("errors", 0) for s in all_stats)
    log.info("New: %d | Deleted: %d | Unchanged: %d | Errors: %d",
             total_new, total_del, total_unchanged, total_errors)

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
