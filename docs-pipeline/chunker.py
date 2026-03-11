"""Header-aware markdown chunker.

Splits markdown docs by headers, respects code blocks, and prepends
breadcrumb context to each chunk.
"""
import hashlib
import re
from dataclasses import dataclass, field

from config import CHARS_PER_TOKEN, CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS


@dataclass
class Chunk:
    text: str
    section: str          # "Config > Auth > API Keys"
    chunk_index: int
    content_hash: str
    content_type: str     # prose, code, api_endpoint, config_example

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = "sha256:" + hashlib.sha256(
                self.text.encode("utf-8")
            ).hexdigest()


def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def _classify_content(text: str) -> str:
    code_blocks = re.findall(r"```[\s\S]*?```", text)
    code_chars = sum(len(b) for b in code_blocks)
    total_chars = len(text) or 1

    if code_chars / total_chars > 0.6:
        # Mostly code — check if it looks like config or endpoint
        lower = text.lower()
        if any(kw in lower for kw in ["endpoint", "method:", "path:", "url:", "get ", "post ", "put ", "delete "]):
            return "api_endpoint"
        if any(kw in lower for kw in ["config", "yaml", "toml", ".env", "settings"]):
            return "config_example"
        return "code"
    return "prose"


def _split_preserving_code_blocks(text: str, max_chars: int) -> list[str]:
    """Split text into pieces of max_chars, never splitting inside fenced code blocks."""
    # Find all code block positions
    code_blocks = [(m.start(), m.end()) for m in re.finditer(r"```[\s\S]*?```", text)]

    def in_code_block(pos: int) -> bool:
        return any(start <= pos < end for start, end in code_blocks)

    pieces = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end >= len(text):
            pieces.append(text[start:])
            break

        # Find a good split point: paragraph break, then sentence, then word
        split_at = None

        # Try paragraph break (double newline)
        for i in range(end, max(start + max_chars // 2, start), -1):
            if text[i:i+2] == "\n\n" and not in_code_block(i):
                split_at = i + 2
                break

        # Try single newline
        if split_at is None:
            for i in range(end, max(start + max_chars // 2, start), -1):
                if text[i] == "\n" and not in_code_block(i):
                    split_at = i + 1
                    break

        # Try space
        if split_at is None:
            for i in range(end, max(start + max_chars // 2, start), -1):
                if text[i] == " " and not in_code_block(i):
                    split_at = i + 1
                    break

        # Last resort: force split at max_chars
        if split_at is None:
            split_at = end

        pieces.append(text[start:split_at])
        start = split_at

    return pieces


def _build_breadcrumb(headers: list[tuple[int, str]]) -> str:
    """Build 'H1 > H2 > H3' breadcrumb from active header stack."""
    if not headers:
        return ""
    return " > ".join(h[1] for h in headers)


def chunk_markdown(content: str, source_name: str = "") -> list[Chunk]:
    """Split markdown content into chunks by headers.

    Strategy:
    1. Split by H1/H2/H3 headers — each starts a new section
    2. If section > CHUNK_MAX_TOKENS, split by paragraphs
    3. Never split mid-code-block
    4. Prepend breadcrumb to each chunk
    5. SHA-256 hash for idempotent updates
    """
    lines = content.split("\n")
    sections: list[tuple[str, str]] = []  # (breadcrumb, text)

    header_stack: list[tuple[int, str]] = []  # [(level, title), ...]
    current_lines: list[str] = []

    def flush_section():
        text = "\n".join(current_lines).strip()
        if text:
            breadcrumb = _build_breadcrumb(header_stack)
            sections.append((breadcrumb, text))
        current_lines.clear()

    for line in lines:
        header_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if header_match:
            # Flush previous section
            flush_section()
            level = len(header_match.group(1))
            title = header_match.group(2).strip()
            # Pop headers at same or deeper level
            while header_stack and header_stack[-1][0] >= level:
                header_stack.pop()
            header_stack.append((level, title))
            current_lines.append(line)
        else:
            current_lines.append(line)

    flush_section()

    # Now chunk each section
    max_chars = CHUNK_MAX_TOKENS * CHARS_PER_TOKEN
    target_chars = CHUNK_TARGET_TOKENS * CHARS_PER_TOKEN
    overlap_chars = CHUNK_OVERLAP_TOKENS * CHARS_PER_TOKEN

    chunks: list[Chunk] = []
    global_idx = 0

    for breadcrumb, section_text in sections:
        section_tokens = _estimate_tokens(section_text)
        prefix = f"[{breadcrumb}]\n\n" if breadcrumb else ""

        if section_tokens <= CHUNK_MAX_TOKENS:
            full_text = prefix + section_text
            chunks.append(Chunk(
                text=full_text,
                section=breadcrumb,
                chunk_index=global_idx,
                content_hash="",
                content_type=_classify_content(section_text),
            ))
            global_idx += 1
        else:
            # Split large section
            pieces = _split_preserving_code_blocks(section_text, target_chars)

            for i, piece in enumerate(pieces):
                # Add overlap from previous piece
                if i > 0 and overlap_chars > 0:
                    prev = pieces[i - 1]
                    overlap_text = prev[-overlap_chars:] if len(prev) > overlap_chars else prev
                    # Find clean start for overlap (paragraph or newline)
                    nl_pos = overlap_text.find("\n")
                    if nl_pos > 0:
                        overlap_text = overlap_text[nl_pos + 1:]
                    piece = overlap_text + "\n" + piece

                full_text = prefix + piece.strip()
                chunks.append(Chunk(
                    text=full_text,
                    section=breadcrumb,
                    chunk_index=global_idx,
                    content_hash="",
                    content_type=_classify_content(piece),
                ))
                global_idx += 1

    # Compute hashes after all text is finalized
    for chunk in chunks:
        chunk.content_hash = "sha256:" + hashlib.sha256(
            chunk.text.encode("utf-8")
        ).hexdigest()

    return chunks


def chunk_openapi_yaml(content: str, source_name: str = "") -> list[Chunk]:
    """Chunk an OpenAPI spec — one chunk per endpoint."""
    import yaml

    try:
        spec = yaml.safe_load(content)
    except yaml.YAMLError:
        # Fallback to markdown-style chunking
        return chunk_markdown(content, source_name)

    if not isinstance(spec, dict) or "paths" not in spec:
        return chunk_markdown(content, source_name)

    chunks: list[Chunk] = []
    idx = 0
    info = spec.get("info", {})
    api_title = info.get("title", source_name)

    paths = spec.get("paths", {})
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, details in methods.items():
            if method.startswith("x-") or not isinstance(details, dict):
                continue

            summary = details.get("summary", "")
            description = details.get("description", "")
            params = details.get("parameters", [])
            request_body = details.get("requestBody", {})
            responses = details.get("responses", {})

            # Build readable text
            lines = [
                f"# {method.upper()} {path}",
                f"**API:** {api_title}",
            ]
            if summary:
                lines.append(f"**Summary:** {summary}")
            if description:
                lines.append(f"\n{description}")

            if params:
                lines.append("\n## Parameters")
                for p in params:
                    if isinstance(p, dict):
                        name = p.get("name", "?")
                        pin = p.get("in", "?")
                        required = p.get("required", False)
                        desc = p.get("description", "")
                        lines.append(f"- `{name}` ({pin}, {'required' if required else 'optional'}): {desc}")

            if request_body and isinstance(request_body, dict):
                lines.append("\n## Request Body")
                rb_content = request_body.get("content", {})
                for ct, schema in rb_content.items():
                    lines.append(f"Content-Type: `{ct}`")
                    if isinstance(schema, dict) and "schema" in schema:
                        lines.append(f"```json\n{yaml.dump(schema['schema'], default_flow_style=False)}```")

            if responses:
                lines.append("\n## Responses")
                for code, resp in responses.items():
                    if isinstance(resp, dict):
                        lines.append(f"- **{code}**: {resp.get('description', '')}")

            text = "\n".join(lines)
            section = f"{api_title} > {method.upper()} {path}"

            chunks.append(Chunk(
                text=text,
                section=section,
                chunk_index=idx,
                content_hash="",
                content_type="api_endpoint",
            ))
            idx += 1

    # Compute hashes
    for chunk in chunks:
        chunk.content_hash = "sha256:" + hashlib.sha256(
            chunk.text.encode("utf-8")
        ).hexdigest()

    return chunks
