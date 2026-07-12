"""
RAG Retriever — TF-IDF cosine similarity over ~20 SOP protocol documents.
Lightweight, offline, no vector DB needed.
"""
from __future__ import annotations

import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DOCS_DIR = os.path.join(os.path.dirname(__file__), "documents")

_vectorizer: TfidfVectorizer | None = None
_tfidf_matrix = None
_doc_names: list[str] = []
_doc_contents: list[str] = []


def _load_documents():
    """Load all .txt documents from the documents directory."""
    global _vectorizer, _tfidf_matrix, _doc_names, _doc_contents

    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR, exist_ok=True)
        return

    _doc_names = []
    _doc_contents = []

    for fname in sorted(os.listdir(DOCS_DIR)):
        if fname.endswith(".txt"):
            fpath = os.path.join(DOCS_DIR, fname)
            with open(fpath, encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                _doc_names.append(fname.replace(".txt", "").replace("_", " ").title())
                _doc_contents.append(content)

    if _doc_contents:
        _vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        _tfidf_matrix = _vectorizer.fit_transform(_doc_contents)
        print(f"RAG: Indexed {len(_doc_contents)} SOP documents")
    else:
        print("RAG: No documents found in", DOCS_DIR)


def retrieve_sops(query: str, top_k: int = 2) -> list[str]:
    """Retrieve top-k most relevant SOP documents for a query."""
    global _vectorizer, _tfidf_matrix

    if _vectorizer is None or _tfidf_matrix is None:
        _load_documents()

    if _vectorizer is None or _tfidf_matrix is None or not _doc_contents:
        return []

    query_vec = _vectorizer.transform([query])
    similarities = cosine_similarity(query_vec, _tfidf_matrix).flatten()

    top_indices = similarities.argsort()[-top_k:][::-1]
    results = []
    for idx in top_indices:
        if similarities[idx] > 0.05:  # Minimum relevance threshold
            results.append(f"[{_doc_names[idx]}]\n{_doc_contents[idx]}")

    return results


def get_all_documents() -> list[dict]:
    """Return all documents with their names (for frontend display)."""
    if not _doc_contents:
        _load_documents()

    return [{"name": n, "content": c[:200] + "..."} for n, c in zip(_doc_names, _doc_contents)]
