from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from threading import RLock
from pathlib import Path

from .models import ANALYZER_PROFILE, INDEX_SCHEMA_VERSION, FIELDS, LANGUAGES, Hit
from .runtime import configure_java
from .utils import atomic_json, job_lock

# PyJNIus method descriptors bind their Java receiver in shared descriptor state.
# A single process must not interleave calls on separate SimpleSearcher instances.
JAVA_SEARCH_LOCK = RLock()


class SparseSearcher:
    """Use Anserini's sparse API without importing optional neural search modules."""

    def __init__(self, path):
        configure_java()
        from pyserini.pyclass import autoclass
        self.object = autoclass("io.anserini.search.SimpleSearcher")(str(path))
        self.num_docs = self.object.get_total_num_docs()

    def close(self):
        self.object.close()


def build_indexes(root: Path, *, threads=2) -> dict:
    configure_java()

    if threads < 1:
        raise ValueError("threads must be positive")
    root = root.resolve()
    with job_lock(root):
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest.get("analyzer_profile") != ANALYZER_PROFILE or manifest.get("index_schema_version") != INDEX_SCHEMA_VERSION:
            raise RuntimeError("Bulk builder cannot open an incompatible analyzer/schema profile")
        if manifest.get("build_mode") != "bulk":
            raise RuntimeError("Bulk builder cannot build a rolling-staging run")
        if not manifest.get("prepared"):
            raise RuntimeError("Corpus preparation incomplete")
        for granularity in ("documents", "chunks"):
            for lang in LANGUAGES:
                key = granularity + "/" + lang
                expected = manifest["counts"].get(f"views_{granularity}_{lang}", 0)
                path = root / "indexes" / granularity / lang
                if key in manifest["indexes"]:
                    searcher = SparseSearcher(path)
                    try:
                        if searcher.num_docs != expected:
                            raise RuntimeError("Completed index count mismatch")
                    finally:
                        searcher.close()
                    continue
                temporary = path.with_name(lang + ".building")
                # Only this run's uncommitted derived partition may be rebuilt.
                if temporary.exists():
                    shutil.rmtree(temporary)
                if path.exists():
                    marker = path / "snapshot.json"
                    if not marker.exists() or json.loads(marker.read_text()) != {"spec_hash": manifest["spec_hash"], "records": expected}:
                        raise RuntimeError(f"Uncommitted index lacks matching snapshot marker: {path}")
                    recovered = SparseSearcher(path)
                    try:
                        if recovered.num_docs != expected:
                            raise RuntimeError("Recovered index count mismatch")
                    finally:
                        recovered.close()
                    manifest["indexes"][key] = {"documents": expected}
                    atomic_json(root/"manifest.json", manifest)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                log_path = root / f"build-{granularity}-{lang}.log"
                import pyserini
                jars = sorted((Path(pyserini.__file__).parent/"resources/jars").glob("anserini-*-fatjar.jar"))
                if len(jars) != 1:
                    raise RuntimeError("Expected one pinned Anserini fatjar in Pyserini wheel")
                argv = [str(Path(os.environ["JAVA_HOME"])/"bin/java"), "--add-modules=jdk.incubator.vector", "-cp", str(jars[0]), "io.anserini.index.IndexCollection", "-collection", "JsonCollection", "-input", str(root/"prepared"/granularity/lang), "-index", str(temporary), "-generator", "DefaultLuceneDocumentGenerator", "-threads", str(threads), "-pretokenized", "-fields", *[x for x in FIELDS if x != "contents"]]
                with log_path.open("w") as log:
                    subprocess.run(argv, check=True, stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy())
                searcher = SparseSearcher(temporary)
                try:
                    if searcher.num_docs != expected:
                        raise RuntimeError(f"Index count mismatch {key}: {searcher.num_docs} != {expected}; see {log_path}")
                finally:
                    searcher.close()
                atomic_json(temporary/"snapshot.json", {"spec_hash": manifest["spec_hash"], "records": expected})
                os.replace(temporary, path)
                manifest["indexes"][key] = {"documents": expected}
                atomic_json(root/"manifest.json", manifest)
                print(json.dumps({"index_done": key, "records": expected}), flush=True)
        return manifest


class LuceneBackend:
    def __init__(self, root: Path, *, k1=0.8, b=0.4):
        if not k1 > 0 or not 0 <= b <= 1:
            raise ValueError("Invalid BM25 parameters")
        configure_java()
        from pyserini.analysis import JWhiteSpaceAnalyzer
        from pyserini.pyclass import autoclass

        self.parameters = k1, b
        self.searchers = {}
        manifest = json.loads((root/"manifest.json").read_text())
        if manifest.get("analyzer_profile") != ANALYZER_PROFILE or manifest.get("index_schema_version") != INDEX_SCHEMA_VERSION:
            raise RuntimeError("Index analyzer/schema profile is incompatible with this code")
        if not manifest.get("prepared") or len(manifest.get("indexes", {})) != 6:
            raise RuntimeError("Index snapshot not complete")
        for granularity in ("documents", "chunks"):
            for lang in LANGUAGES:
                searcher = SparseSearcher(root/"indexes"/granularity/lang)
                searcher.object.set_analyzer(JWhiteSpaceAnalyzer())
                searcher.object.set_bm25(float(k1), float(b))
                self.searchers[(granularity, lang)] = searcher
        self.Builder = autoclass("org.apache.lucene.search.BooleanQuery$Builder")
        self.Occur = autoclass("org.apache.lucene.search.BooleanClause$Occur")
        self.Term = autoclass("org.apache.lucene.index.Term")
        self.TermQuery = autoclass("org.apache.lucene.search.TermQuery")
        self.BoostQuery = autoclass("org.apache.lucene.search.BoostQuery")

    def search(self, granularity, language, fields, *, k, k1=0.8, b=0.4):
        with JAVA_SEARCH_LOCK:
            return self._search(granularity, language, fields, k=k, k1=k1, b=b)

    def _search(self, granularity, language, fields, *, k, k1, b):
        if k < 1 or (k1, b) != self.parameters:
            raise ValueError("Search k invalid or parameters differ from immutable searcher configuration")
        query = self.Builder()
        count = 0
        weights = {"contents": 2.5, "broad": 1.0, "exact": 2.0, "anchors": 2.0, "title": 0.2 if granularity == "chunks" else 1.0}
        import math
        allowance = max(1, math.floor(128/max(1, sum(bool(v) for v in fields.values()))))
        for field, tokens in fields.items():
            if field not in weights:
                raise ValueError(f"Unknown indexed field: {field}")
            for term in list(dict.fromkeys(tokens))[:allowance]:
                if count >= 128:
                    break
                if not term or any(c.isspace() for c in term):
                    raise ValueError("Expected nonempty pretokenized term")
                clause = self.TermQuery(self.Term(field, term))
                query.add(self.BoostQuery(clause, weights[field]), self.Occur.SHOULD)
                count += 1
        if not count:
            return []
        query.setMinimumNumberShouldMatch(1)
        values = self.searchers[(granularity, language)].object.search(query.build(), k)
        return [Hit(h.docid, float(h.score), i+1) for i, h in enumerate(values)]

    def close(self):
        for searcher in self.searchers.values():
            searcher.close()
