"""Qdrant upsert/delete/scroll helpers for docs collection."""
import logging
import random
import time

import requests

import config

log = logging.getLogger(__name__)

UPSERT_BATCH = 100  # points per upsert call


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if config.QDRANT_API_KEY:
        h["api-key"] = config.QDRANT_API_KEY
    return h


def _api(method: str, path: str, json_data: dict | None = None, timeout: int = 30):
    url = f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}{path}"
    resp = requests.request(method, url, headers=_headers(), json=json_data, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_existing_hashes(source: str) -> dict[str, int]:
    """Scroll all points for a source, return {content_hash: point_id}."""
    hashes: dict[str, int] = {}
    offset = None

    while True:
        body: dict = {
            "filter": {"must": [{"key": "source", "match": {"value": source}}]},
            "limit": 250,
            "with_payload": ["content_hash"],
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset

        data = _api("POST", "/points/scroll", body, timeout=60)
        result = data.get("result", {})
        points = result.get("points", [])

        for p in points:
            h = p.get("payload", {}).get("content_hash", "")
            if h:
                hashes[h] = p["id"]

        next_offset = result.get("next_page_offset")
        if next_offset is None or not points:
            break
        offset = next_offset

    return hashes


def upsert_points(points: list[dict]) -> int:
    """Upsert points in batches. Each point: {id, vector, payload}.

    Returns number of points upserted.
    """
    total = 0
    for batch_start in range(0, len(points), UPSERT_BATCH):
        batch = points[batch_start:batch_start + UPSERT_BATCH]

        for attempt in range(3):
            try:
                _api("PUT", "/points", {"points": batch}, timeout=60)
                total += len(batch)
                break
            except Exception as e:
                log.warning("Upsert batch %d attempt %d failed: %s", batch_start, attempt + 1, e)
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise

        if batch_start + len(batch) < len(points):
            log.info("Upserted %d/%d points...", total, len(points))

    return total


def delete_points(point_ids: list[int]) -> int:
    """Delete points by ID list."""
    if not point_ids:
        return 0

    for batch_start in range(0, len(point_ids), 500):
        batch = point_ids[batch_start:batch_start + 500]
        _api("POST", "/points/delete", {"points": batch}, timeout=30)

    return len(point_ids)


def generate_point_id() -> int:
    """Generate a random uint64-safe point ID."""
    return random.randint(1_000_000_000_000, 999_999_999_999_999_999)


def collection_info() -> dict:
    """Get collection info (point count, status, etc.)."""
    url = f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json().get("result", {})
