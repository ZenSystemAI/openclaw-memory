"""Configuration for docs-ingest pipeline."""
import os

# Load .env early so all modules get the values
_env_path = os.path.expanduser("~/.openclaw/.env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                if _key.strip() not in os.environ:
                    os.environ[_key.strip()] = _val.strip()

# OpenAI embedding API (text-embedding-3-small)
OPENAI_URL = os.getenv("OPENAI_URL", "https://api.openai.com/v1/embeddings")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 768
EMBED_BATCH_SIZE = 32

# Qdrant vector DB
QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = "docs"

# Chunking
CHUNK_TARGET_TOKENS = 1000  # aim for 800-1200
CHUNK_MAX_TOKENS = 1500
CHUNK_OVERLAP_TOKENS = 100

# Paths
CLONE_DIR = os.path.expanduser("~/docs-pipeline/repos")
LOG_DIR = os.path.expanduser("~/docs-pipeline/logs")

# Approx 4 chars per token for English text
CHARS_PER_TOKEN = 4

# Search defaults
SEARCH_SCORE_THRESHOLD = 0.35
SEARCH_DEFAULT_LIMIT = 5
