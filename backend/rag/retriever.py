"""
RAG Retriever — TF-IDF cosine similarity over the SOP protocol documents.
Lightweight, offline, no vector DB needed. Implemented directly (smoothed
idf, sublinear-free tf, L2-normalised vectors) instead of scikit-learn, which
cost ~125 MB of RAM just to index a dozen documents.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

DOCS_DIR = os.path.join(os.path.dirname(__file__), "documents")

# Common English stop words (subset of the scikit-learn list)
STOP_WORDS = frozenset("""
a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having
he her here hers herself him himself his how i if in into is it its itself just me more most my myself no
nor not now of off on once only or other our ours ourselves out over own same she should so some such than
that the their theirs them themselves then there these they this those through to too under until up very
was we were what when where which while who whom why will with would you your yours yourself yourselves
""".split())

_TOKEN = re.compile(r"(?u)\b\w\w+\b")

_doc_names: list[str] = []
_doc_contents: list[str] = []
_doc_vectors: list[dict[str, float]] = []
_idf: dict[str, float] = {}


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOP_WORDS]


def _vector(tokens: list[str]) -> dict[str, float]:
    """L2-normalised tf-idf vector for a token list (unknown terms dropped)."""
    counts = Counter(t for t in tokens if t in _idf)
    vec = {t: c * _idf[t] for t, c in counts.items()}
    norm = math.sqrt(sum(w * w for w in vec.values()))
    return {t: w / norm for t, w in vec.items()} if norm else {}


def _load_documents():
    """Load all .txt documents from the documents directory and index them."""
    global _doc_names, _doc_contents, _doc_vectors, _idf

    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR, exist_ok=True)
        return

    names, contents = [], []
    for fname in sorted(os.listdir(DOCS_DIR)):
        if fname.endswith(".txt"):
            with open(os.path.join(DOCS_DIR, fname), encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                names.append(fname.replace(".txt", "").replace("_", " ").title())
                contents.append(content)

    if not contents:
        print("RAG: No documents found in", DOCS_DIR)
        return

    doc_tokens = [_tokens(c) for c in contents]
    n = len(contents)
    df = Counter(t for toks in doc_tokens for t in set(toks))
    # Smoothed idf, as in scikit-learn's TfidfVectorizer default
    _idf = {t: math.log((1 + n) / (1 + d)) + 1 for t, d in df.items()}
    _doc_names, _doc_contents = names, contents
    _doc_vectors = [_vector(toks) for toks in doc_tokens]
    print(f"RAG: Indexed {n} SOP documents")


def retrieve_sops(query: str, top_k: int = 2) -> list[str]:
    """Retrieve top-k most relevant SOP documents for a query."""
    if not _doc_vectors:
        _load_documents()
    if not _doc_vectors:
        return []

    q = _vector(_tokens(query))
    scores = [sum(w * doc.get(t, 0.0) for t, w in q.items()) for doc in _doc_vectors]
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [
        f"[{_doc_names[i]}]\n{_doc_contents[i]}"
        for i in ranked
        if scores[i] > 0.05  # Minimum relevance threshold
    ]


def get_all_documents() -> list[dict]:
    """Return all documents with their names (for frontend display)."""
    if not _doc_contents:
        _load_documents()

    return [{"name": n, "content": c[:200] + "..."} for n, c in zip(_doc_names, _doc_contents)]
