"""
Vector retrieval over the document corpus, with an optional cross-encoder
rerank stage.

The reranker is a *measured* decision, not a default. `search()` takes
`rerank=` so the eval harness can run both arms over the same questions and
report the difference. If it does not improve Recall@5 and MRR it comes out,
and the negative result gets written down.

Models are loaded once per process and cached -- a cross-encoder reload per
query would dominate the latency numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from firesight.config import settings
from firesight.ingest.documents import CHUNK_CONFIGS, ChunkConfig


@dataclass
class Hit:
    chunk_id: str
    text: str
    score: float
    source_document: str
    section: str
    page: int | None
    publisher: str
    year: str
    url: str
    rank: int
    retrieval_score: float | None = None  # pre-rerank score, when reranked

    def citation(self) -> str:
        page = f", p. {self.page}" if self.page and self.page > 0 else ""
        return f"{self.source_document} — {self.section}{page}"


class CorpusUnavailableError(RuntimeError):
    """The Chroma collection is missing or empty."""


@lru_cache(maxsize=4)
def _embedder(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


@lru_cache(maxsize=2)
def _reranker(model_name: str, max_length: int):
    from sentence_transformers import CrossEncoder

    ce = CrossEncoder(model_name)
    # Truncation dominates cross-encoder cost; see the latency table in
    # eval/results/. Set explicitly rather than relying on the model default.
    # `max_length` was renamed to `max_seq_length`; support both.
    if hasattr(ce, "max_seq_length"):
        ce.max_seq_length = max_length
    else:  # pragma: no cover - older sentence-transformers
        ce.max_length = max_length
    return ce


@lru_cache(maxsize=4)
def _collection(name: str):
    import chromadb

    if not settings.chroma_path.exists():
        raise CorpusUnavailableError(
            f"no Chroma store at {settings.chroma_path}; "
            "run `python -m firesight.ingest.documents`"
        )
    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    try:
        coll = client.get_collection(name)
    except Exception as e:
        raise CorpusUnavailableError(f"collection {name!r} not found: {e}") from e
    if coll.count() == 0:
        raise CorpusUnavailableError(f"collection {name!r} is empty")
    return coll


def search(
    query: str,
    *,
    k: int | None = None,
    rerank: bool = False,
    config: str | ChunkConfig = "default",
    fetch_multiplier: int | None = None,
) -> list[Hit]:
    """
    Retrieve the top-k chunks for `query`.

    With `rerank=True`, `k * fetch_multiplier` candidates are pulled by
    embedding similarity and re-scored by the cross-encoder, which is the
    only arrangement in which reranking can change anything.
    """
    k = k or settings.top_k
    fetch_multiplier = fetch_multiplier or settings.rerank_candidate_multiplier
    cfg = CHUNK_CONFIGS[config] if isinstance(config, str) else config
    coll = _collection(cfg.collection)

    n_fetch = min(k * fetch_multiplier if rerank else k, coll.count())
    qvec = _embedder(settings.embed_model).encode(
        [query], normalize_embeddings=True
    )[0]
    res = coll.query(
        query_embeddings=[qvec.tolist()],
        n_results=n_fetch,
        include=["documents", "metadatas", "distances"],
    )

    ids = res["ids"][0]
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    hits = [
        Hit(
            chunk_id=i,
            text=d,
            # cosine distance -> similarity, so bigger is always better
            score=1.0 - float(dist),
            source_document=m.get("source_document", "?"),
            section=m.get("section", "?"),
            page=(None if m.get("page", -1) in (-1, None) else int(m["page"])),
            publisher=m.get("publisher", "?"),
            year=str(m.get("year", "?")),
            url=m.get("url", ""),
            rank=0,
        )
        for i, d, m, dist in zip(ids, docs, metas, dists, strict=True)
    ]

    if rerank and hits:
        ce = _reranker(settings.rerank_model, settings.rerank_max_length)
        scores = ce.predict([(query, h.text) for h in hits])
        for h, s in zip(hits, scores, strict=True):
            h.retrieval_score = h.score
            h.score = float(s)
        hits.sort(key=lambda h: h.score, reverse=True)

    hits = hits[:k]
    for n, h in enumerate(hits, start=1):
        h.rank = n
    return hits


def corpus_stats(config: str = "default") -> dict:
    cfg = CHUNK_CONFIGS[config]
    coll = _collection(cfg.collection)
    sample = coll.get(include=["metadatas"], limit=100_000)
    docs: dict[str, int] = {}
    for m in sample["metadatas"]:
        docs[m.get("source_document", "?")] = docs.get(m.get("source_document", "?"), 0) + 1
    return {
        "collection": cfg.collection,
        "chunks": coll.count(),
        "documents": len(docs),
        "by_document": dict(sorted(docs.items(), key=lambda x: -x[1])),
    }


SCOPE_DOCUMENT = "FireSight Corpus Scope"


def scope_context(
    question: str, *, k: int = 2, config: str | ChunkConfig = "default"
) -> list[Hit]:
    """
    Retrieve the scope-boundary document's most relevant sections.

    Fetched deliberately rather than by hoping it ranks. Measured: when the
    scope document shared the main index it did NOT reach the top 5 for "What
    sprinkler pressure does NFPA 13 require?" or for state-fire-code questions
    -- the same similarity blindness that lets those questions past the support
    floor also keeps the document that explains the refusal out of the results.

    It therefore lives in its OWN collection, out of the main index, and the
    out_of_scope path asks for it by name. Sharing the index cost MRR (0.711 ->
    0.644 on the best arm) for presence nothing used.
    """
    cfg = CHUNK_CONFIGS[config] if isinstance(config, str) else config
    try:
        coll = _collection(cfg.scope_collection)
    except CorpusUnavailableError:
        return []

    qvec = _embedder(settings.embed_model).encode([question], normalize_embeddings=True)[0]
    res = coll.query(
        query_embeddings=[qvec.tolist()],
        n_results=min(k, coll.count()),
        include=["documents", "metadatas", "distances"],
    )
    if not res["ids"] or not res["ids"][0]:
        return []

    hits = [
        Hit(
            chunk_id=i,
            text=d,
            score=1.0 - float(dist),
            source_document=m.get("source_document", SCOPE_DOCUMENT),
            section=m.get("section", "?"),
            page=None,
            publisher=m.get("publisher", "FireSight (scope boundary)"),
            year=str(m.get("year", "")),
            url=m.get("url", ""),
            rank=n,
        )
        for n, (i, d, m, dist) in enumerate(
            zip(
                res["ids"][0],
                res["documents"][0],
                res["metadatas"][0],
                res["distances"][0],
                strict=True,
            ),
            start=1,
        )
    ]
    return hits
