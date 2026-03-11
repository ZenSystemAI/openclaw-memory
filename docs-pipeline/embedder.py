"""Batch embedding via OpenAI text-embedding-3-small."""
import logging
import time

import requests

from config import EMBED_BATCH_SIZE, EMBED_DIM, EMBED_MODEL, OPENAI_API_KEY, OPENAI_URL

log = logging.getLogger(__name__)

# text-embedding-3-small has 8191-token context
# Use conservative limit (markdown/code tokenizes at ~1-2 chars/token)
MAX_EMBED_CHARS = 6000


def _embed_batch(texts: list[str], batch_label: str) -> list[list[float]]:
    """Send a single batch to OpenAI. Returns list of embedding vectors.

    Raises on failure after 3 retries.
    """
    for attempt in range(3):
        try:
            resp = requests.post(
                OPENAI_URL,
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": EMBED_MODEL,
                    "input": texts,
                    "dimensions": EMBED_DIM,
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

            # OpenAI returns {"data": [{"embedding": [...], "index": 0}, ...]}
            items = sorted(data["data"], key=lambda x: x["index"])
            embeddings = [item["embedding"] for item in items]

            if len(embeddings) != len(texts):
                raise ValueError(
                    f"Expected {len(texts)} embeddings, got {len(embeddings)}"
                )

            # Validate dimensions
            for emb in embeddings:
                if len(emb) != EMBED_DIM:
                    raise ValueError(
                        f"Expected {EMBED_DIM}-dim vector, got {len(emb)}"
                    )

            return embeddings

        except Exception as e:
            log.warning(
                "Embed batch %s attempt %d failed: %s",
                batch_label, attempt + 1, e
            )
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def _embed_batch_with_fallback(
    texts: list[str], batch_start: int
) -> list[list[float] | None]:
    """Embed a batch; on failure, fall back to embedding one-by-one.

    Returns a list the same length as texts. Failed items get None.
    """
    label = f"{batch_start}-{batch_start + len(texts)}"
    try:
        return _embed_batch(texts, label)
    except Exception:
        pass

    # Batch failed after retries -- fall back to one-by-one
    log.warning(
        "Batch %s failed; falling back to one-by-one embedding (%d items)",
        label, len(texts),
    )
    results: list[list[float] | None] = []
    for i, text in enumerate(texts):
        idx = batch_start + i
        try:
            embs = _embed_batch([text], f"single-{idx}")
            results.append(embs[0])
        except Exception as e:
            log.warning("Skipping chunk %d (embed failed): %s", idx, e)
            results.append(None)
    return results


def embed_texts(texts: list[str], prefix: str = "") -> list[list[float] | None]:
    """Embed a list of texts using OpenAI, in batches.

    Args:
        texts: Raw texts to embed.
        prefix: Optional prefix prepended to each text before embedding.
                OpenAI text-embedding-3-small does not require task prefixes
                like nomic-embed-text did, so this defaults to empty string.

    Returns:
        List of embedding vectors (768-dim each) or None for chunks that
        failed to embed. Callers must check for None and skip those chunks
        rather than storing them.
    """
    all_embeddings: list[list[float] | None] = []
    skipped = 0

    for batch_start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[batch_start:batch_start + EMBED_BATCH_SIZE]
        # Truncate texts that exceed the model's context window
        prepared = [prefix + t[:MAX_EMBED_CHARS] for t in batch]

        results = _embed_batch_with_fallback(prepared, batch_start)

        for emb in results:
            if emb is None:
                log.warning("Chunk at index %d failed to embed — skipping (will not be stored)", batch_start + len(all_embeddings) % EMBED_BATCH_SIZE)
                all_embeddings.append(None)
                skipped += 1
            else:
                all_embeddings.append(emb)

        batch_end = batch_start + len(batch)
        total = len(texts)
        if batch_end < total:
            log.info("Embedded %d/%d chunks...", batch_end, total)

    if skipped:
        log.warning("Skipped %d chunks that failed to embed", skipped)

    return all_embeddings
