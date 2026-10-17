from __future__ import annotations

import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from .models import SearchBackend
from .query import QueryProjector
from .store import TextStore


def fuse(runs, *, maximum: int, rrf_k=60):
    counts = Counter(lang for lang, _, _ in runs)
    scores = defaultdict(float)
    evidence = defaultdict(list)
    for language, channel, hits in runs:
        seen = set()
        for hit in hits:
            if hit.identifier in seen:
                continue
            seen.add(hit.identifier)
            scores[hit.identifier] += 1/(max(1, counts[language]) * (rrf_k+hit.rank))
            evidence[hit.identifier].append({"language": language, "channel": channel, "rank": hit.rank, "bm25": hit.score})
    keys = sorted(scores, key=lambda k: (-scores[k], k))[:maximum]
    return [{"identifier": key, "rank": i+1, "fusion_score": scores[key], "evidence": evidence[key]} for i, key in enumerate(keys)]


class CandidateEngine:
    """Candidate search only. No qrels, relevance cutoff, or final submission policy."""

    def __init__(self, backend: SearchBackend, projector: QueryProjector, store: TextStore, *, per_language_docs=300, per_language_chunks=1000, max_docs=1000, max_chunks=3000, threads=2, k1=0.8, b=0.4):
        if min(per_language_docs, per_language_chunks, max_docs, max_chunks, threads) < 1:
            raise ValueError("Candidate budgets and threads must be positive")
        self.backend, self.projector, self.store = backend, projector, store
        self.doc_k, self.chunk_k = per_language_docs, per_language_chunks
        self.max_docs, self.max_chunks = max_docs, max_chunks
        self.k1, self.b = k1, b
        self.pool = ThreadPoolExecutor(max_workers=threads)

    def search(self, query: dict) -> dict:
        started = time.perf_counter()
        channels, warnings = self.projector.project(query["query"])
        jobs = [(g, lang, channel, fields) for g in ("documents", "chunks") for lang, channel, fields in channels]
        def execute(job):
            g, lang, channel, fields = job
            hits = self.backend.search(g, lang, fields, k=self.doc_k if g == "documents" else self.chunk_k, k1=self.k1, b=self.b)
            return g, lang, channel, hits
        results = list(self.pool.map(execute, jobs))
        documents = fuse([(l, c, h) for g, l, c, h in results if g == "documents"], maximum=self.max_docs)
        chunks = fuse([(l, c, h) for g, l, c, h in results if g == "chunks"], maximum=self.max_chunks)
        doc_lookup = {d["identifier"]: d for d in documents}
        for c in chunks:
            meta = self.store.metadata(c.pop("identifier"))
            c.update(chunk_id=meta["chunk_id"], doc_id=meta["doc_id"], chunk_order=meta["chunk_order"])
            identifier = str(meta["doc_id"])
            # Best evidence only: repeated chunks never accumulate document score.
            if identifier not in doc_lookup:
                doc_lookup[identifier] = {"identifier": identifier, "fusion_score": c["fusion_score"], "evidence": [{"channel": "best-chunk", "rank": c["rank"]}]}
            else:
                doc_lookup[identifier]["fusion_score"] = max(doc_lookup[identifier]["fusion_score"], c["fusion_score"])
        docs = sorted(doc_lookup.values(), key=lambda d: (-d["fusion_score"], d["identifier"]))[:self.max_docs]
        for i, doc in enumerate(docs):
            doc["doc_id"] = int(doc.pop("identifier"))
            if not self.store.document_exists(doc["doc_id"]):
                raise RuntimeError("Search result document missing source identity")
            doc["rank"] = i+1
        return {"id": query["id"], "query": query["query"], "documents": docs, "chunks": chunks, "warnings": warnings, "seconds": time.perf_counter()-started}

    def search_batch(self, queries):
        for query in queries:
            yield self.search(query)

    def close(self):
        self.pool.shutdown(wait=True)
        self.backend.close()
        self.store.close()
