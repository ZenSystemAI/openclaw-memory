<p align="center">
  <img src=".github/logo.svg" alt="ZenSystem" width="120" />
  <h1 align="center">OpenClaw Memory Toolkit</h1>
  <p align="center">
    Production-grade long-term memory, documentation search, and cross-agent knowledge sharing for OpenClaw
  </p>
  <p align="center">
    <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg" />
    <img alt="Shell" src="https://img.shields.io/badge/shell-bash-green.svg" />
    <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue.svg" />
  </p>
</p>

---

OpenClaw's built-in memory indexes your markdown files. This toolkit goes further — it **extracts structured knowledge** from your sessions, builds a searchable documentation knowledge base, and optionally bridges your agent's memory to other systems.

## What OpenClaw Gives You vs. What This Adds

| Capability | OpenClaw Built-in | This Toolkit |
|------------|:-:|:-:|
| Session context (conversation history) | **Yes** | — (uses native) |
| Markdown file indexing | **Yes** (sqlite-vec) | — (uses native) |
| Auto-compaction with memory flush | **Yes** | — (uses native) |
| **Structured fact extraction from sessions** | No | **Yes** — LLM extracts discrete facts from session noise |
| **Long-term vector memory (Qdrant)** | No | **Yes** — separate from session SQLite |
| **Documentation knowledge base** | No | **Yes** — embed any docs, 45K+ vectors |
| **Client data isolation** | No | **Yes** — mandatory client_id on every memory |
| **Credential scrubbing** | No | **Yes** — API keys, tokens, emails redacted before storage |
| **GDPR-compliant bulk deletion** | No | **Yes** — per-client erasure with audit log |
| **Cross-agent memory bridge** | No | **Yes** — optional bridge to Multi-Agent Memory |
| **Encrypted backups** | No | **Yes** — GPG-encrypted Qdrant snapshots |
| **Importance classification** | No | **Yes** — critical/high/medium/low per fact |
| **Category tagging** | No | **Yes** — semantic/episodic/procedural |
| **Access tracking & decay** | Temporal decay on files | **Yes** — per-fact access count + last_accessed |

## The Key Difference

OpenClaw's native memory is **file-based** — it indexes the markdown you write. That's good for recent context but terrible for long-term knowledge. After 100 sessions, your daily logs are a haystack.

This toolkit is **fact-based** — an LLM reads your session transcripts, extracts the knowledge that actually matters, classifies it, scrubs credentials, and stores structured facts in a vector database. Six months later, you can ask "what does this client prefer?" and get a precise answer, not a wall of old conversation.

## Components

### Skills (drop-in OpenClaw skills)

| Skill | What it does |
|-------|-------------|
| `memory-store` | Store a fact with embeddings, credential scrubbing, client isolation |
| `memory-query` | Semantic search over stored facts (+ optional Shared Brain) |
| `memory-delete` | Delete by ID or bulk client erasure (GDPR) with audit logging |
| `docs-query` | Search embedded documentation (any source) |

### Scripts

| Script | What it does |
|--------|-------------|
| `memory-consolidate.sh` | **The core engine.** Reads OpenClaw session chunks → LLM extracts facts (JSON mode) → stores in Qdrant. Runs on cron. |
| `backup-vectordb.sh` | Qdrant snapshot → GPG encrypt → rotate (keep N). Runs on cron. |

### Docs Pipeline

| File | What it does |
|------|-------------|
| `docs-ingest.py` | Main pipeline: git clone → chunk → embed → upsert |
| `chunker.py` | Header-aware markdown splitter. Preserves code blocks, adds breadcrumb context. |
| `embedder.py` | Batch embedding via OpenAI (with retry, fallback to single-item on failure) |
| `qdrant_ops.py` | Qdrant CRUD helpers (upsert, delete, scroll, stats) |
| `config.py` | All configuration in one place, reads from `.env` |

## Quick Start

### Prerequisites

- A running [Qdrant](https://qdrant.tech/) instance (Docker recommended)
- OpenAI API key (for embeddings + fact extraction)
- OpenClaw installed and running

### 1. Install Qdrant

```bash
docker run -d --name qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/qdrant-data:/qdrant/storage \
  -e QDRANT__SERVICE__API_KEY=your-qdrant-key \
  qdrant/qdrant:latest
```

### 2. Configure

```bash
git clone https://github.com/ZenSystemAI/openclaw-memory.git
cd openclaw-memory
cp .env.example .env
# Edit .env — set OPENAI_API_KEY and QDRANT_API_KEY
```

### 3. Install Skills

```bash
# Copy skills into your OpenClaw workspace
cp -r skills/memory-store ~/.openclaw/skills/
cp -r skills/memory-query ~/.openclaw/skills/
cp -r skills/memory-delete ~/.openclaw/skills/
cp -r skills/docs-query ~/.openclaw/skills/

# Copy the consolidation script
cp scripts/memory-consolidate.sh ~/.openclaw/scripts/
chmod +x ~/.openclaw/scripts/memory-consolidate.sh
```

### 4. Set Up Cron (Automatic Consolidation)

```bash
# Extract facts from sessions twice daily (adjust times as needed)
crontab -e
# Add:
0 11,23 * * * /bin/bash ~/.openclaw/scripts/memory-consolidate.sh >> ~/.openclaw/memory-audit.log 2>&1
```

### 5. Test

```bash
# Store a memory
bash ~/.openclaw/skills/memory-store/store.sh \
  --text "Production database runs on port 5432" \
  --client_id "global" \
  --category "semantic" \
  --importance "high"

# Query it back
bash ~/.openclaw/skills/memory-query/query.sh \
  --query "database port" \
  --client_id "global"
```

## Documentation Knowledge Base (Optional)

Embed any documentation into a searchable knowledge base your agent can query.

```bash
# Install Python dependencies
cd docs-pipeline
pip install -r requirements.txt

# Ingest documentation
python3 docs-ingest.py --source all --mode full

# Search from your agent
bash ~/.openclaw/skills/docs-query/search.sh \
  --query "How do I configure webhooks?" \
  --source n8n
```

### Adding Your Own Doc Sources

Edit `docs-ingest.py` to add new sources. Each source needs:
- A git repo URL (or local path)
- A glob pattern for markdown files
- A source name for filtering

The chunker handles markdown intelligently — splits by headers, preserves code blocks, adds section breadcrumbs, and deduplicates by content hash.

## Cross-Agent Bridge (Optional)

If you run [Multi-Agent Memory](https://github.com/ZenSystemAI/multi-agent-memory), the consolidation script can automatically push cross-agent-relevant facts to the shared brain.

```bash
# Add to your .env
BRAIN_API_KEY=your-shared-brain-key
BRAIN_API_URL=http://your-server:8084
```

Facts marked as `cross_agent: true` by the LLM during extraction are automatically bridged. Deduplication is handled by the shared brain — safe to run on every consolidation cycle.

## Backup & Recovery

```bash
# Set up automated encrypted backups
cp scripts/backup-vectordb.sh ~/.openclaw/scripts/
chmod +x ~/.openclaw/scripts/backup-vectordb.sh

# Add to cron (daily at 3 AM)
0 3 * * * /bin/bash ~/.openclaw/scripts/backup-vectordb.sh >> ~/backups/vectordb/backup.log 2>&1
```

Backups are GPG-encrypted using your Qdrant API key as the passphrase. Last 7 snapshots are retained automatically.

## Configuration

All configuration is via environment variables in `.env`:

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `OPENAI_API_KEY` | Yes | — | For embeddings and fact extraction |
| `QDRANT_API_KEY` | Yes | — | Qdrant authentication |
| `QDRANT_URL` | No | `http://127.0.0.1:6333` | Qdrant instance URL |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | LLM for fact extraction |
| `BRAIN_API_KEY` | No | — | Multi-Agent Memory API key (enables bridge) |
| `BRAIN_API_URL` | No | — | Multi-Agent Memory API URL |

## Project Structure

```
openclaw-memory/
├── skills/
│   ├── memory-store/      # Store facts with embeddings
│   │   ├── store.sh
│   │   └── SKILL.md
│   ├── memory-query/      # Semantic search over facts
│   │   ├── query.sh
│   │   └── SKILL.md
│   ├── memory-delete/     # Delete facts (single or GDPR bulk)
│   │   ├── delete.sh
│   │   └── SKILL.md
│   └── docs-query/        # Search embedded documentation
│       ├── search.sh
│       └── SKILL.md
├── scripts/
│   ├── memory-consolidate.sh   # Session → fact extraction → Qdrant
│   └── backup-vectordb.sh      # Encrypted Qdrant backups
├── docs-pipeline/
│   ├── docs-ingest.py     # Main ingestion pipeline
│   ├── chunker.py         # Header-aware markdown splitter
│   ├── embedder.py        # Batch OpenAI embeddings
│   ├── qdrant_ops.py      # Qdrant CRUD helpers
│   ├── config.py          # Configuration
│   └── requirements.txt
├── .env.example
├── LICENSE
└── README.md
```

## How It Works With OpenClaw's Native Memory

This toolkit **complements** OpenClaw's built-in memory — it doesn't replace it.

```
OpenClaw Native                    This Toolkit
─────────────────                  ──────────────────────
Session context ──► Compaction     Session chunks ──► LLM Extraction
                    │                                    │
              MEMORY.md                          Structured facts
              memory/*.md                        in Qdrant (vector DB)
                    │                                    │
              memory_search                    memory-query skill
              (recent context)                 (long-term knowledge)
                                                         │
                                               Optional: bridge to
                                               Multi-Agent Memory
```

Use OpenClaw's native `memory_search` for recent session context. Use this toolkit's `memory-query` for long-term facts, client knowledge, and documentation.

## License

MIT — see [LICENSE](LICENSE).

## See Also

- **[Multi-Agent Memory](https://github.com/ZenSystemAI/multi-agent-memory)** — Cross-machine, cross-agent persistent memory for AI systems. The shared brain that this toolkit bridges to.

---

<p align="center">
  Built by <a href="https://zensystem.ai">ZenSystem</a> &mdash; Open Source from Quebec, Canada
</p>
