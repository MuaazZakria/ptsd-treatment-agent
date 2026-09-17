"""
Evidence index: PDF -> page text -> overlapping word chunks -> BM25.

Ported from the original pipeline's corpus module. The index is a lazily-built
singleton with a disk cache keyed by a fingerprint of the PDF set. Delete
``.cache/`` to force a rebuild.
"""

from __future__ import annotations

import hashlib
import pickle
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings, get_settings

_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _chunk(text: str, chunk_words: int, overlap_words: int, min_chunk_words: int) -> list[str]:
    words = text.split()
    if len(words) < min_chunk_words:
        return []
    step = max(1, chunk_words - overlap_words)
    out: list[str] = []
    for i in range(0, len(words), step):
        piece = words[i : i + chunk_words]
        if len(piece) >= min_chunk_words:
            out.append(" ".join(piece))
    return out


def _fingerprint(paths: list[Path], cfg: Settings) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}".encode())
    h.update(f"{cfg.chunk_words}:{cfg.overlap_words}:{cfg.min_chunk_words}".encode())
    return h.hexdigest()[:16]


def _extract_one(args: tuple[Path, Settings]) -> list[dict[str, Any]]:
    path, cfg = args
    rows: list[dict[str, Any]] = []
    try:
        if path.suffix.lower() == ".txt":
            pages = [_clean(path.read_text(encoding="utf-8", errors="ignore"))]
        else:
            import pymupdf  # heavy import, kept local

            with pymupdf.open(path) as doc:
                pages = [_clean(page.get_text("text")) for page in doc]
        for page_no, text in enumerate(pages, start=1):
            for chunk in _chunk(text, cfg.chunk_words, cfg.overlap_words, cfg.min_chunk_words):
                rows.append(
                    {
                        "source": "local_pdf",
                        "title": path.stem,
                        "file": path.name,
                        "page": page_no,
                        "text": chunk,
                    }
                )
    except Exception as exc:  # a corrupt file should not sink the whole index
        print(f"[corpus] skipped {path.name}: {exc}")
    return rows


@dataclass
class EvidenceIndex:
    chunks: list[dict[str, Any]]
    bm25: Any
    n_documents: int
    built_seconds: float
    from_cache: bool
    source_dir: Path

    @property
    def n_chunks(self) -> int:
        return len(self.chunks)


def build_index(cfg: Settings | None = None, *, force: bool = False) -> EvidenceIndex:
    cfg = cfg or get_settings()
    from rank_bm25 import BM25Okapi

    pdf_paths = (
        sorted([*cfg.evidence_dir.rglob("*.pdf"), *cfg.evidence_dir.rglob("*.txt")])
        if cfg.evidence_dir.exists()
        else []
    )
    if not pdf_paths:
        raise FileNotFoundError(
            f"No .pdf/.txt files under {cfg.evidence_dir}. Set PTA_EVIDENCE_DIR to the corpus folder."
        )

    fp = _fingerprint(pdf_paths, cfg)
    cache_file = cfg.cache_dir / f"chunks_{fp}.pkl"
    t0 = time.perf_counter()

    if cache_file.exists() and not force:
        chunks = pickle.loads(cache_file.read_bytes())
        from_cache = True
    else:
        chunks = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            for rows in ex.map(_extract_one, [(p, cfg) for p in pdf_paths]):
                chunks.extend(rows)
        for i, c in enumerate(chunks, start=1):
            c["evidence_id"] = f"LOCAL-{i:05d}"
        cache_file.write_bytes(pickle.dumps(chunks))
        from_cache = False

    bm25 = BM25Okapi([c["text"].lower().split() for c in chunks]) if chunks else None
    return EvidenceIndex(
        chunks=chunks,
        bm25=bm25,
        n_documents=len(pdf_paths),
        built_seconds=round(time.perf_counter() - t0, 3),
        from_cache=from_cache,
        source_dir=cfg.evidence_dir,
    )


_INDEX: EvidenceIndex | None = None


def get_index(cfg: Settings | None = None) -> EvidenceIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = build_index(cfg)
    return _INDEX
