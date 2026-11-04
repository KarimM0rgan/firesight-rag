"""
Build the unstructured corpus: load documents -> chunk -> embed -> Chroma.

    uv run python -m firesight.ingest.documents
    uv run python -m firesight.ingest.documents --config small --rebuild

Idempotent. Chunk ids are a hash of (source, section, page, index), so a
re-run upserts in place rather than duplicating. `--rebuild` drops the
collection first.

Chunking is configurable because M4 has to compare at least two settings;
the configs live in CHUNK_CONFIGS and each gets its own Chroma collection so
both can be queried without a re-ingest.

COPYRIGHT. Only public-domain or own-work sources are ingested:
  * USFA / FEMA NFIRS documentation -- US government works, 17 USC 105
  * The NFIRS code dictionary shipped inside the Public Data Release
  * This project's own methodology notes
NFPA standards are copyrighted and are never ingested. See data/PROFILE.md.

PRIVACY. The local incident export is NOT ingested. It carries street
addresses, building names, coordinates and personnel identifiers for real
incidents. PROFILE.md section 7 forbids those leaving the raw file, and this
module never reads it.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from firesight.config import REPO_ROOT, settings


@dataclass(frozen=True)
class ChunkConfig:
    name: str
    target_tokens: int
    overlap_pct: float

    @property
    def overlap_tokens(self) -> int:
        return int(self.target_tokens * self.overlap_pct)

    @property
    def collection(self) -> str:
        return f"firesight_docs_{self.name}"


CHUNK_CONFIGS: dict[str, ChunkConfig] = {
    # The spec's starting point: ~500 tokens, ~15% overlap.
    "default": ChunkConfig("default", target_tokens=500, overlap_pct=0.15),
    # Finer chunks: better precision on short definitional lookups, worse on
    # questions needing surrounding narrative. M4 measures which wins.
    "small": ChunkConfig("small", target_tokens=220, overlap_pct=0.20),
}


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source_document: str
    section: str
    page: int | None
    publisher: str
    year: str
    url: str

    def metadata(self) -> dict:
        return {
            "source_document": self.source_document,
            "section": self.section,
            "page": self.page if self.page is not None else -1,
            "publisher": self.publisher,
            "year": self.year,
            "url": self.url,
        }

    def citation(self) -> str:
        page = f", p. {self.page}" if self.page and self.page > 0 else ""
        return f"{self.source_document} — {self.section}{page}"


# ── sources ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Source:
    path: Path
    title: str
    publisher: str
    year: str
    url: str


def _usfa(name: str, title: str, year: str, url: str) -> Source:
    return Source(
        path=settings.docs_path / "usfa" / name,
        title=title,
        publisher="U.S. Fire Administration (FEMA)",
        year=year,
        url=url,
    )


PDF_SOURCES: list[Source] = [
    _usfa(
        "nfirs_complete_reference_guide_2015.pdf",
        "NFIRS 5.0 Complete Reference Guide",
        "2015",
        "https://www.usfa.fema.gov/downloads/pdf/nfirs/nfirs_complete_reference_guide_2015.pdf",
    ),
    _usfa(
        "nfirs_data_analysis_guidelines_issues.pdf",
        "NFIRS 5.0 Fire Data Analysis Guidelines and Issues",
        "2011",
        "https://www.usfa.fema.gov/downloads/pdf/nfirs/nfirs_data_analysis_guidelines_issues.pdf",
    ),
    _usfa(
        "nfirs_spec_2015.pdf",
        "NFIRS 5.0 Design Documentation",
        "2015",
        "https://www.usfa.fema.gov/downloads/pdf/nfirs/nfirs_spec_2015.pdf",
    ),
]

MARKDOWN_SOURCES: list[Source] = [
    Source(
        path=REPO_ROOT / "data" / "PROFILE.md",
        title="FireSight Data Profile",
        publisher="FireSight (own work)",
        year="2026",
        url="data/PROFILE.md",
    ),
    Source(
        path=REPO_ROOT / "data" / "RECONCILIATION.md",
        title="FireSight Reconciliation Notes",
        publisher="FireSight (own work)",
        year="2026",
        url="data/RECONCILIATION.md",
    ),
]


# ── tokenizer ──────────────────────────────────────────────────────────────
class Tokenizer:
    """
    Counts tokens with the embedding model's own tokenizer so chunks respect
    the model's 512-token window.

    Chunk text is always sliced from the ORIGINAL string using character
    offsets, never reconstructed by decoding token ids. bge-small-en-v1.5 is
    an uncased WordPiece model: decoding a round trip lowercases everything
    and inserts spaces around punctuation, so "See NFPA 1710, Sec. 5.2."
    comes back as "see nfpa 1710, sec. 5. 2.". Embedding that is survivable;
    storing it and showing it to a reader as a quotation is not.
    """

    def __init__(self, model_name: str) -> None:
        self._tok = None
        try:
            from transformers import AutoTokenizer

            self._tok = AutoTokenizer.from_pretrained(model_name)
        except Exception:
            self._tok = None

    def count(self, text: str) -> int:
        if self._tok is not None:
            return len(self._tok.encode(text, add_special_tokens=False))
        return len(text.split())

    # Kept for the length audit in tests and scripts.
    def encode(self, text: str) -> list:
        if self._tok is not None:
            return self._tok.encode(text, add_special_tokens=False)
        return text.split()

    def spans(self, text: str) -> list[tuple[int, int]]:
        """Character span of each token, so slices stay lossless."""
        if self._tok is not None and getattr(self._tok, "is_fast", False):
            enc = self._tok(
                text, add_special_tokens=False, return_offsets_mapping=True
            )
            return [(a, b) for a, b in enc["offset_mapping"] if b > a]
        # Word fallback: span each whitespace-delimited word.
        out, pos = [], 0
        for word in text.split():
            start = text.find(word, pos)
            if start < 0:
                continue
            out.append((start, start + len(word)))
            pos = start + len(word)
        return out

    @property
    def exact(self) -> bool:
        return self._tok is not None

    @property
    def has_offsets(self) -> bool:
        return self._tok is not None and getattr(self._tok, "is_fast", False)


# ── loading ────────────────────────────────────────────────────────────────
# A heading is a short line that is not prose: numbered, ALL CAPS, or Title
# Case without terminal punctuation. Tuned against the CRG's actual layout.
HEADING = re.compile(
    r"^(?:"
    r"(?:SECTION|CHAPTER|APPENDIX|MODULE)\s+[A-Z0-9IVX.\-]+.*"
    r"|\d+(?:\.\d+)*\s+[A-Z][^.!?]{2,70}"
    r"|[A-Z][A-Z0-9 ,/&'()\-]{5,70}"
    r")$"
)

PAGE_NOISE = re.compile(
    r"^(?:"
    r"page\s+\d+"
    r"|[\divxlcIVXLC\s.\-]+"                       # bare page/roman numerals
    r"|NFIRS\s+(?:VERSION\s+)?5\.0.*"              # running headers
    r"|U\.?S\.?\s+Fire\s+Administration.*"
    r"|(?:January|February|March|April|May|June|July|August|September"
    r"|October|November|December)\s+20\d\d"
    r"|Appendix\s+[A-Z]\s*[-–]\s*\d+"
    r"|Table\s+of\s+Contents"
    r")$",
    re.IGNORECASE,
)

# A block shorter than this is page furniture, not content worth embedding.
MIN_BLOCK_CHARS = 120

# Hard ceiling for a chunk. bge-small-en-v1.5 truncates silently above this,
# which would drop the tail of every long chunk without an error.
EMBED_WINDOW_TOKENS = 512

# Sections that are navigation, not content. A table of contents retrieves
# well on keyword overlap and answers nothing.
SKIP_SECTIONS = re.compile(r"^(?:table\s+of\s+contents|contents|index)$", re.IGNORECASE)


def _clean_lines(raw: str) -> list[str]:
    out = []
    for line in raw.splitlines():
        s = " ".join(line.split())
        if not s or PAGE_NOISE.match(s):
            continue
        out.append(s)
    return out


def _snap(text: str, end: int, lookahead: int = 60) -> int:
    """Move `end` forward to the next sentence break, else the next space."""
    n = len(text)
    if end >= n:
        return n
    for i in range(end, min(end + lookahead, n)):
        if text[i] in ".!?" and (i + 1 >= n or text[i + 1].isspace()):
            return i + 1
    for i in range(end, min(end + lookahead, n)):
        if text[i].isspace():
            return i
    return end


def _outline_sections(reader) -> dict[int, str]:
    """
    Map 1-based page number -> section title from the PDF's own bookmarks.

    These are the document's real headings, which beats guessing from line
    shape: the NFIRS PDFs are mostly tables and code lists, and a regex
    cheerfully mistakes a table row like "7 Death" for a chapter title.
    """
    marks: list[tuple[int, str]] = []

    def walk(items) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            try:
                title = " ".join(str(item.title).split())
                page_no = reader.get_destination_page_number(item) + 1
            except Exception:
                continue
            if title:
                marks.append((page_no, title))

    try:
        walk(reader.outline)
    except Exception:
        return {}

    if not marks:
        return {}
    marks.sort(key=lambda x: x[0])
    mapping: dict[int, str] = {}
    for idx, (page_no, title) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(reader.pages) + 1
        for p in range(page_no, end):
            mapping[p] = title
    return mapping


def load_pdf(src: Source) -> list[tuple[int, str, str]]:
    """Return (page_number, section, text) blocks."""
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("pypdf not installed. Run: uv sync --extra rag")

    reader = PdfReader(str(src.path))
    outline = _outline_sections(reader)
    blocks: list[tuple[int, str, str]] = []
    heuristic_section = "Front matter"

    for page_no, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            continue
        lines = _clean_lines(raw)
        if not lines:
            continue

        # Prefer the document's own bookmark for this page. Only fall back to
        # the line-shape heuristic where the outline is silent (the Design
        # Documentation ships just two bookmarks for 367 pages).
        if page_no in outline:
            section = outline[page_no]
            if SKIP_SECTIONS.match(section.strip()):
                continue
            body = " ".join(lines)
            if len(body) >= MIN_BLOCK_CHARS:
                blocks.append((page_no, section, body))
            continue

        buf: list[str] = []
        for line in lines:
            if HEADING.match(line) and len(line) < 75:
                if buf:
                    body = " ".join(buf)
                    if len(body) >= MIN_BLOCK_CHARS:
                        blocks.append((page_no, heuristic_section, body))
                    buf = []
                heuristic_section = line.title() if line.isupper() else line
            else:
                buf.append(line)
        if buf:
            body = " ".join(buf)
            if len(body) >= MIN_BLOCK_CHARS:
                blocks.append((page_no, heuristic_section, body))
    return blocks


MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def load_markdown(src: Source) -> list[tuple[int, str, str]]:
    blocks: list[tuple[int, str, str]] = []
    section = src.title
    buf: list[str] = []
    for line in src.path.read_text(encoding="utf-8").splitlines():
        m = MD_HEADING.match(line)
        if m:
            if buf:
                blocks.append((None, section, "\n".join(buf).strip()))
                buf = []
            section = " ".join(m.group(2).split())
        else:
            buf.append(line)
    if buf:
        blocks.append((None, section, "\n".join(buf).strip()))
    return [(p, s, t) for p, s, t in blocks if t]


def load_code_dictionary() -> list[tuple[int, str, str]]:
    """
    Turn the PDR's own codelookup table into prose documents, one section per
    coded field. This is the authoritative answer to definitional questions
    like "how does NFIRS classify a structure fire?".
    """
    path = settings.codelookup_file
    if not path.exists():
        return []
    fields: dict[str, list[tuple[str, str]]] = {}
    with open(path, encoding="latin-1", newline="") as f:
        rd = csv.reader(f, delimiter="^", quotechar='"')
        next(rd, None)
        for row in rd:
            if len(row) >= 3 and row[1].strip():
                fields.setdefault(row[0].strip(), []).append(
                    (row[1].strip(), row[2].strip())
                )
    blocks = []
    for field, codes in sorted(fields.items()):
        lines = [
            f"NFIRS field {field} has {len(codes)} permitted code values. "
            f"Each code and its official description follows."
        ]
        lines += [f"Code {c} means: {d}." for c, d in codes]
        blocks.append((None, f"Field {field}", "\n".join(lines)))
    return blocks


# ── chunking ───────────────────────────────────────────────────────────────
def chunk_blocks(
    blocks: list[tuple[int | None, str, str]],
    src: Source,
    cfg: ChunkConfig,
    tok: Tokenizer,
) -> list[Chunk]:
    """
    Split each section into token-bounded chunks with overlap.

    Section boundaries are respected: a chunk never spans two sections, so
    every chunk can carry an honest `section` citation.
    """
    chunks: list[Chunk] = []
    step = max(1, cfg.target_tokens - cfg.overlap_tokens)

    for page, section, text in blocks:
        if not text.strip():
            continue
        spans = tok.spans(text)
        if len(spans) <= cfg.target_tokens:
            pieces = [text]
        else:
            pieces = []
            for start in range(0, len(spans), step):
                window = spans[start : start + cfg.target_tokens]
                if not window:
                    break
                lo, hi = window[0][0], window[-1][1]
                # Snap the end forward to the next sentence or word boundary so
                # chunks do not end mid-word -- but never past the embedding
                # window, or the model silently truncates the tail.
                snapped = _snap(text, hi)
                if tok.count(text[lo:snapped]) <= EMBED_WINDOW_TOKENS:
                    hi = snapped
                pieces.append(text[lo:hi])
                if start + cfg.target_tokens >= len(spans):
                    break
        for i, piece in enumerate(pieces):
            body = piece.strip()
            if len(body) < 40:  # drop header fragments and stray page furniture
                continue
            key = f"{src.title}|{section}|{page}|{i}|{cfg.name}"
            chunks.append(
                Chunk(
                    chunk_id=hashlib.sha1(key.encode()).hexdigest()[:16],
                    text=body,
                    source_document=src.title,
                    section=section,
                    page=page,
                    publisher=src.publisher,
                    year=src.year,
                    url=src.url,
                )
            )
    return chunks


def build_chunks(cfg: ChunkConfig, tok: Tokenizer) -> list[Chunk]:
    chunks: list[Chunk] = []
    missing: list[str] = []

    for src in PDF_SOURCES:
        if not src.path.exists():
            missing.append(str(src.path))
            continue
        chunks += chunk_blocks(load_pdf(src), src, cfg, tok)

    for src in MARKDOWN_SOURCES:
        if src.path.exists():
            chunks += chunk_blocks(load_markdown(src), src, cfg, tok)

    code_src = Source(
        path=settings.codelookup_file,
        title="NFIRS Code Dictionary",
        publisher="U.S. Fire Administration (FEMA)",
        year="2024",
        url="NFIRS 2024 Public Data Release / codelookup.txt",
    )
    if settings.codelookup_file.exists():
        chunks += chunk_blocks(load_code_dictionary(), code_src, cfg, tok)
    else:
        missing.append(str(settings.codelookup_file))

    if missing:
        print("  ! missing sources (skipped):", flush=True)
        for m in missing:
            print(f"      {m}", flush=True)

    # Guard against duplicate ids colliding in Chroma.
    seen: dict[str, int] = {}
    for c in chunks:
        seen[c.chunk_id] = seen.get(c.chunk_id, 0) + 1
    dupes = [k for k, v in seen.items() if v > 1]
    if dupes:
        uniq, used = [], set()
        for c in chunks:
            cid = c.chunk_id
            n = 0
            while cid in used:
                n += 1
                cid = hashlib.sha1(f"{c.chunk_id}|{n}".encode()).hexdigest()[:16]
            used.add(cid)
            uniq.append(Chunk(**{**c.__dict__, "chunk_id": cid}))
        chunks = uniq
    return chunks


# ── embedding + persistence ────────────────────────────────────────────────
def ingest(cfg: ChunkConfig, rebuild: bool = False, batch: int = 256) -> int:
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.exit("chromadb / sentence-transformers not installed. Run: uv sync --extra rag")

    tok = Tokenizer(settings.embed_model)
    if not tok.exact:
        print("  ! model tokenizer unavailable; chunking by whitespace words", flush=True)

    print(f"[{cfg.name}] chunking (target {cfg.target_tokens} tok, "
          f"{cfg.overlap_pct:.0%} overlap) ...", flush=True)
    chunks = build_chunks(cfg, tok)
    if not chunks:
        sys.exit("No chunks produced. Check FIRESIGHT_DOCS_PATH and the NFIRS dir.")
    print(f"[{cfg.name}] {len(chunks):,} chunks from "
          f"{len({c.source_document for c in chunks})} documents", flush=True)

    settings.chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    if rebuild:
        with contextlib.suppress(Exception):
            client.delete_collection(cfg.collection)
    coll = client.get_or_create_collection(
        cfg.collection, metadata={"hnsw:space": "cosine"}
    )

    print(f"[{cfg.name}] embedding with {settings.embed_model} ...", flush=True)
    model = SentenceTransformer(settings.embed_model)
    for i in range(0, len(chunks), batch):
        part = chunks[i : i + batch]
        vecs = model.encode(
            [c.text for c in part],
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        coll.upsert(
            ids=[c.chunk_id for c in part],
            documents=[c.text for c in part],
            metadatas=[c.metadata() for c in part],
            embeddings=[v.tolist() for v in vecs],
        )
        print(f"    {min(i + batch, len(chunks)):,}/{len(chunks):,}", flush=True)

    total = coll.count()
    print(f"[{cfg.name}] collection '{cfg.collection}' now holds {total:,} chunks")
    return total


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest the document corpus into Chroma.")
    p.add_argument("--config", choices=[*CHUNK_CONFIGS, "all"], default="all")
    p.add_argument("--rebuild", action="store_true", help="drop the collection first")
    args = p.parse_args()

    names = list(CHUNK_CONFIGS) if args.config == "all" else [args.config]
    for name in names:
        ingest(CHUNK_CONFIGS[name], rebuild=args.rebuild)


if __name__ == "__main__":
    main()
