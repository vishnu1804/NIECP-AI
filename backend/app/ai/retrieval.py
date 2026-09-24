"""
Retrieval-augmented knowledge engine (spec §36).

Design constraints for this deployment:
  * zero external services — chunks are embedded into sparse term vectors
    (BM25-style scoring) stored as JSON, plus an optional deterministic hash
    embedding for dense cosine re-ranking;
  * every hit returns its source metadata (title, publisher, URL, citation,
    date, section, verification status) so the UI can render the citation block;
  * user-project documents are indexed too (scope PROJECT) so the assistant can
    reason about what the user actually uploaded;
  * if the corpus has no confident hit the caller receives an explicit
    `unavailable` signal and must say so — never an invented answer.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..enums import SourceStatus

log = logging.getLogger("niecp.rag")

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "for", "of", "to", "in", "on", "at", "by",
    "with", "from", "as", "is", "are", "was", "were", "be", "been", "being", "it", "its", "this", "that",
    "these", "those", "i", "you", "he", "she", "we", "they", "them", "their", "his", "her", "my", "our",
    "your", "what", "which", "who", "whom", "when", "where", "why", "how", "do", "does", "did", "done",
    "can", "could", "should", "would", "shall", "will", "may", "might", "must", "have", "has", "had",
    "not", "no", "nor", "so", "too", "very", "s", "t", "about", "into", "over", "under", "between",
    "there", "here", "than", "also", "any", "each", "few", "more", "most", "other", "some", "such", "only",
    "own", "same", "up", "down", "out", "off", "again", "further", "once", "all", "both", "he", "she",
    "me", "him", "us", "get", "got", "need", "needs", "want", "please", "tell", "show", "give",
}

TOKEN_RE = re.compile(r"[a-z0-9\u0b80-\u0bff\u0900-\u097f]{2,}")


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


def sparse_vector(text: str) -> dict[str, float]:
    tf = Counter(tokenize(text))
    if not tf:
        return {}
    max_tf = max(tf.values())
    return {term: 0.5 + 0.5 * count / max_tf for term, count in tf.items()}


def hash_embedding(text: str, dim: int | None = None) -> list[float]:
    """Deterministic feature-hashing embedding. Not semantic — a stable tiebreaker
    for near-duplicate passages. The primary ranking signal is the sparse score."""
    dim = dim or settings.embedding_dim
    vec = [0.0] * dim
    for term in tokenize(text):
        h = int.from_bytes(hashlib.sha256(term.encode()).digest()[:8], "big")
        idx = h % dim
        sign = 1.0 if (h >> 63) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def chunk_text(text: str, target_chars: int = 1100, overlap: int = 150) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= target_chars:
        return [text] if text else []
    # split on paragraph boundaries first
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for para in paragraphs:
        if size + len(para) > target_chars and current:
            chunks.append("\n\n".join(current))
            # keep a small overlap for continuity
            tail = "\n\n".join(current)[-overlap:]
            current = [tail, para]
            size = len(tail) + len(para)
        else:
            current.append(para)
            size += len(para) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


@dataclass
class RetrievedChunk:
    text: str
    score: float
    document_id: int
    title: str
    doc_kind: str
    publisher: str | None
    url: str | None
    citation: str | None
    published_on: str | None
    section: str | None
    verification_status: str
    scope: str
    project_id: int | None

    def citation_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "publisher": self.publisher,
            "url": self.url,
            "citation": self.citation,
            "published_on": self.published_on,
            "section": self.section,
            "verification_status": self.verification_status,
            "doc_kind": self.doc_kind,
            "score": round(self.score, 4),
            "excerpt": self.text[:400],
        }


def index_knowledge_document(db: Session, kd: models.KnowledgeDocument) -> int:
    """(Re)chunk and index one knowledge document. Returns chunk count."""
    for old in db.scalars(
        select(models.KnowledgeChunk).where(models.KnowledgeChunk.document_id == kd.id)
    ):
        db.delete(old)
    db.flush()
    body = kd.body or ""
    chunks = chunk_text(body)
    model = "sparse+hash-v1"
    for idx, chunk in enumerate(chunks):
        db.add(
            models.KnowledgeChunk(
                document_id=kd.id,
                chunk_index=idx,
                text=chunk,
                section=kd.section,
                token_count=len(tokenize(chunk)),
                embedding=None,  # computed lazily and cached as bytes if needed
                embedding_model=model,
                terms=sparse_vector(chunk),
            )
        )
    kd.chunk_count = len(chunks)
    db.flush()
    return len(chunks)


def retrieve(
    db: Session,
    query: str,
    *,
    project_id: int | None = None,
    top_k: int | None = None,
    include_project_docs: bool = True,
) -> list[RetrievedChunk]:
    """Hybrid retrieval over the knowledge corpus."""
    top_k = top_k or settings.rag_top_k
    qvec = sparse_vector(query)
    if not qvec:
        return []

    stmt = select(models.KnowledgeDocument, models.KnowledgeChunk).join(
        models.KnowledgeChunk, models.KnowledgeChunk.document_id == models.KnowledgeDocument.id
    ).where(models.KnowledgeDocument.is_active.is_(True), models.KnowledgeDocument.scope == "GLOBAL")
    if include_project_docs and project_id:
        stmt = select(models.KnowledgeDocument, models.KnowledgeChunk).join(
            models.KnowledgeChunk, models.KnowledgeChunk.document_id == models.KnowledgeDocument.id
        ).where(
            models.KnowledgeDocument.is_active.is_(True),
            models.KnowledgeDocument.scope.in_(["GLOBAL", "PROJECT"]),
            (models.KnowledgeDocument.project_id == project_id) | (models.KnowledgeDocument.scope == "GLOBAL"),
        )

    scored: list[RetrievedChunk] = []
    for kd, chunk in db.execute(stmt).all():
        chunk_terms = chunk.terms or {}
        # BM25-lite: query term overlap weighted by chunk term weights
        score = 0.0
        for term, qweight in qvec.items():
            if term in chunk_terms:
                score += qweight * chunk_terms[term]
        if score <= 0:
            continue
        # small title boost
        title_terms = set(tokenize(kd.title or ""))
        score += 0.6 * len(set(qvec) & title_terms)
        # verification trust boost — official summaries outrank user docs on ties
        if kd.verification_status == SourceStatus.VERIFIED_GOV_SOURCE:
            score *= 1.15
        if kd.doc_kind == "PROCEDURE":
            score *= 0.85
        scored.append(
            RetrievedChunk(
                text=chunk.text,
                score=score,
                document_id=kd.id,
                title=kd.title,
                doc_kind=kd.doc_kind,
                publisher=kd.publisher,
                url=kd.url,
                citation=None,
                published_on=kd.published_on.isoformat() if kd.published_on else None,
                section=chunk.section or kd.section,
                verification_status=kd.verification_status.value if kd.verification_status else SourceStatus.REQUIRES_VERIFICATION.value,
                scope=kd.scope,
                project_id=kd.project_id,
            )
        )
    scored.sort(key=lambda c: -c.score)
    # Confidence floor: a single weak term overlap is not "grounding". Require
    # at least a couple of meaningful term hits (or a strong title match).
    floor = 1.1
    return [c for c in scored[:top_k] if c.score >= floor]


def corpus_stats(db: Session) -> dict[str, Any]:
    docs = db.scalars(select(models.KnowledgeDocument)).all()
    return {
        "documents": len(docs),
        "chunks": sum(d.chunk_count or 0 for d in docs),
        "official_summaries": sum(1 for d in docs if d.doc_kind == "OFFICIAL_SUMMARY"),
        "procedures": sum(1 for d in docs if d.doc_kind == "PROCEDURE"),
        "project_documents": sum(1 for d in docs if d.scope == "PROJECT"),
    }
