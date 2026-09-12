"""
Evidence retrieval: patient -> queries -> BM25 over the local corpus.

Verbatim port of iaso-ptsd-agent/iaso/retrieval.py, minus the PubMed sufficiency
gate (this app never falls back to PubMed). The query builder is deliberately
rule-based (no LLM) and keys only off medications and comorbidities.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from .config import Settings, get_settings
from .corpus import EvidenceIndex, get_index

STOPWORDS = {
    "the", "and", "for", "with", "adults", "of", "in", "a", "an", "to", "on",
    "study", "studies",
}


SSRI_SNRI_DRUGS = ("sertraline", "paroxetine", "fluoxetine", "venlafaxine")


def build_fast_queries(patient: dict[str, Any], cfg: Settings | None = None) -> list[str]:
    cfg = cfg or get_settings()
    tx = patient.get("treatment", {}) or {}
    meds = " ".join(str(m.get("drug", "")) for m in (tx.get("medications") or [])).lower()
    comorb = " ".join(str(x) for x in (patient.get("comorbidities_at_onset") or [])).lower()
    on_ssri_snri = any(k in meds for k in SSRI_SNRI_DRUGS)
    ptsd_still_active = bool((patient.get("ptsd") or {}).get("still_active"))

    q: list[str] = []
    if "sertraline" in meds:
        q.append("PTSD sertraline efficacy randomized trial systematic review")
    elif any(k in meds for k in ("paroxetine", "fluoxetine", "venlafaxine")):
        q.append("PTSD SSRI SNRI pharmacotherapy efficacy systematic review")
    else:
        q.append("PTSD trauma focused psychotherapy pharmacotherapy systematic review")

    if any(k in comorb for k in ("misuses drugs", "alcohol", "substance")):
        q.append("PTSD substance use alcohol integrated treatment systematic review")
    elif any(k in comorb for k in ("chronic pain", "back pain", "neck pain")):
        q.append("PTSD chronic pain comorbid treatment outcomes")
    elif any(k in comorb for k in ("intimate partner", "violence")):
        q.append("PTSD intimate partner violence treatment evidence")
    elif "isolation" in comorb:
        q.append("PTSD social isolation support treatment outcomes")
    else:
        q.append("PTSD comorbid depression treatment outcomes adults")

    # ADDITIVE, not a replacement (regression fix - see HANDOVER / commit note):
    # an earlier version of this branch *replaced* the drug-efficacy query above
    # whenever still_active was true. In this synthetic dataset every sertraline
    # patient has still_active=true, so that swap fired for ~92% of the cohort
    # and threw away the query that reliably retrieves direct PTSD-treatment
    # evidence, in favor of one that mostly surfaces mechanistic/animal papers.
    # Keep both: the queries above stay the primary evidence source, and this
    # one adds next-line/treatment-resistant coverage on top for patients on an
    # SSRI/SNRI whose PTSD is still marked active.
    added_extra = False
    if on_ssri_snri and ptsd_still_active:
        q.append(
            "PTSD treatment-resistant inadequate response to SSRI next-line augmentation "
            "psychotherapy ketamine psilocybin"
        )
        added_extra = True

    limit = cfg.max_queries + 1 if added_extra else cfg.max_queries
    return q[:limit]


def search_local_corpus(
    query: str,
    *,
    top_k: int | None = None,
    per_doc: int = 1,
    index: EvidenceIndex | None = None,
    cfg: Settings | None = None,
) -> list[dict[str, Any]]:
    """BM25 with per-document capping so ``top_k`` snippets come from ``top_k`` papers."""
    cfg = cfg or get_settings()
    index = index or get_index(cfg)
    top_k = top_k or cfg.top_k_local
    chunks, bm25 = index.chunks, index.bm25
    if not chunks or bm25 is None:
        return []

    tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if t not in STOPWORDS]
    if not tokens:
        return []

    scores = np.asarray(bm25.get_scores(tokens), dtype=float)
    if scores.max() <= 0:
        return []

    order = np.argsort(-scores)
    picked: list[dict[str, Any]] = []
    seen_docs: dict[str, int] = {}
    for i in order[: top_k * 40]:
        raw = float(scores[int(i)])
        if raw < cfg.min_useful_bm25:
            break
        rec = chunks[int(i)]
        doc = rec["title"]
        if seen_docs.get(doc, 0) >= per_doc:
            continue
        seen_docs[doc] = seen_docs.get(doc, 0) + 1
        out = dict(rec)
        out["raw_bm25"] = round(raw, 3)
        out["score"] = round(raw / float(scores.max()), 4)
        out["text"] = out["text"][: cfg.evidence_chars]
        picked.append(out)
        if len(picked) >= top_k:
            break
    return picked
