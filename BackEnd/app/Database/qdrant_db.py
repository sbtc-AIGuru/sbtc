"""Read-only dense and multilingual hybrid queries for a restored collection."""

from __future__ import annotations

import math
import os
import json
from copy import deepcopy
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import quote

import requests


class QdrantManager:
    """Read-only Qdrant queries; never create collections, indexes or models."""

    def __init__(
        self, url: str | None = None, collection: str | None = None, *,
        dense_vector_name: str | None = None, sparse_vector_name: str | None = None,
        api_key: str | None = None, timeout: float = 30,
        bm25_options: dict | None = None,
        dense_encoder: Callable[[list[str]], Sequence[Sequence[float]]] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.url = (url or os.getenv("QDRANT_URL", "http://127.0.0.1:6333")).rstrip("/")
        self.collection = collection or os.getenv("QDRANT_COLLECTION", "sbtc_gte_multilingual")
        self.dense_vector_name = dense_vector_name or os.getenv("QDRANT_DENSE_VECTOR_NAME")
        self.sparse_vector_name = sparse_vector_name or os.getenv("QDRANT_SPARSE_VECTOR_NAME", "bm25")
        self.api_key = api_key or os.getenv("QDRANT_API_KEY")
        self.timeout = timeout
        self.dense_encoder = dense_encoder
        self.bm25_options = deepcopy(bm25_options) if bm25_options is not None else {
            "tokenizer": "multilingual", "stemmer": {"type": "none"},
            "stopwords": {}, "ascii_folding": False,
        }
        self.session = session if session is not None else requests.Session()
        self._owns_session = session is None
        self._config = None
        self._path = f"/collections/{quote(self.collection, safe='')}"

    @classmethod
    def from_manifest(cls, path: str | Path, *, url: str | None = None, **kwargs):
        """Use the exact vector names and BM25 tokenizer exported by the notebook."""
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        if not manifest["complete"]:
            raise ValueError("Recovery snapshot is incomplete; resume the notebook before production queries")
        schema = manifest["vector_schema"]
        return cls(url, manifest["collection"], dense_vector_name=schema["dense"],
                   sparse_vector_name=schema["sparse"], bm25_options=schema["bm25_options"], **kwargs)

    def _request(self, method: str, path: str, body: dict | None = None):
        response = self.session.request(
            method, self.url + path, json=body, timeout=self.timeout,
            headers={"api-key": self.api_key} if self.api_key else {},
        )
        response.raise_for_status()
        return response.json()["result"]

    def refresh_collection(self) -> dict:
        """Reload schema after an administrator adds or changes vector indexes."""
        info = self._request("GET", self._path)
        self._config = info["config"]["params"]
        return info

    def _collection_config(self) -> dict:
        if self._config is None:
            self.refresh_collection()
        return self._config

    def _dense_query(self, vector: Sequence[float]) -> dict:
        vectors = self._collection_config()["vectors"]
        if self.dense_vector_name:
            if self.dense_vector_name not in vectors:
                raise ValueError(f"Dense vector {self.dense_vector_name!r} is not configured")
            specification = vectors[self.dense_vector_name]
        else:
            if "size" in vectors:
                specification = vectors
            elif "dense" in vectors:
                self.dense_vector_name = "dense"
                specification = vectors["dense"]
            else:
                raise ValueError("Collection uses named vectors; set dense_vector_name")
        values = [float(value) for value in vector]
        if len(values) != specification["size"]:
            raise ValueError(f"Expected {specification['size']} dense dimensions, got {len(values)}")
        if not all(math.isfinite(value) for value in values) or not any(values):
            raise ValueError("Dense vector must contain finite values and be nonzero")
        query = {"query": values}
        if self.dense_vector_name:
            query["using"] = self.dense_vector_name
        return query

    def _sparse_query(self, vector: dict | None) -> dict:
        sparse = self._collection_config().get("sparse_vectors") or {}
        if self.sparse_vector_name not in sparse:
            raise RuntimeError(
                f"Collection {self.collection!r} has no sparse vector {self.sparse_vector_name!r}. "
                "The restored Kaggle snapshot is dense-only. Build and populate a matching "
                "sparse index first, then call refresh_collection(); search_dense() is available now."
            )
        if vector is None:
            raise ValueError("Hybrid search requires sparse_vector with indices and values")
        if "text" in vector:
            if vector.get("model") != "qdrant/bm25" or not isinstance(vector["text"], str) or not vector["text"].strip():
                raise ValueError("BM25 text query must contain nonempty text and model qdrant/bm25")
            return {"query": deepcopy(vector), "using": self.sparse_vector_name}
        indices = list(vector["indices"])
        values = [float(value) for value in vector["values"]]
        if not indices or len(indices) != len(values):
            raise ValueError("Sparse indices and values must be nonempty and have equal length")
        if any(type(index) is not int or not 0 <= index < 2**32 for index in indices):
            raise ValueError("Sparse indices must be unsigned 32-bit integers")
        if len(set(indices)) != len(indices):
            raise ValueError("Sparse indices must be unique")
        if not all(math.isfinite(value) for value in values) or not any(values):
            raise ValueError("Sparse values must be finite and nonzero as a vector")
        return {"query": {"indices": indices, "values": values}, "using": self.sparse_vector_name}

    def query_original_dense(
        self, query: dict[str, str], *, query_filter: dict | None = None,
        with_payload: bool | list[str] = True,
    ) -> list[dict]:
        """Fuse dense(original_query) and BM25(VI/EN/ZH): 50 per branch, top 100."""
        return self._query_hybrid(query, multilingual_dense=False,
                                  query_filter=query_filter, with_payload=with_payload)

    def query_multilingual_dense(
        self, query: dict[str, str], *, query_filter: dict | None = None,
        with_payload: bool | list[str] = True,
    ) -> list[dict]:
        """Fuse dense(VI/EN/ZH) and BM25(VI/EN/ZH): 50 per branch, top 100."""
        return self._query_hybrid(query, multilingual_dense=True,
                                  query_filter=query_filter, with_payload=with_payload)

    def _query_hybrid(
        self, query: dict[str, str], *, multilingual_dense: bool,
        query_filter: dict | None, with_payload: bool | list[str],
    ) -> list[dict]:
        keys = ("original_query", "eng_query", "chinese_query")
        if not isinstance(query, dict) or any(
            not isinstance(query.get(key), str) or not query[key].strip() for key in keys
        ):
            raise ValueError("Query requires nonempty original_query, eng_query and chinese_query")
        if self.dense_encoder is None:
            raise ValueError("Configure dense_encoder with the same GTE encoder used to build the index")
        texts = [query[key] for key in keys]
        sparse = [self._sparse_query({
            "text": text, "model": "qdrant/bm25", "options": self.bm25_options,
        }) for text in texts]
        dense_texts = texts if multilingual_dense else texts[:1]
        vectors = self.dense_encoder(dense_texts)
        if len(vectors) != len(dense_texts):
            raise ValueError("dense_encoder must return one vector per query text")
        branches = [self._dense_query(vector) for vector in vectors] + sparse
        for branch in branches:
            branch["limit"] = 50
            if query_filter is not None:
                branch["filter"] = query_filter
        # Fusion ranks the union of all branches; each branch keeps its top-50 budget.
        body = {
            "prefetch": branches, "query": {"fusion": "rrf"}, "limit": 100,
            "with_payload": with_payload, "with_vector": False,
        }
        if query_filter is not None:
            body["filter"] = query_filter
        return self._request("POST", self._path + "/points/query", body)["points"]

    def search(
        self, dense_vector: Sequence[float], sparse_vector: dict | None = None,
        top_k: int = 10, *, prefetch_limit: int | None = None, fusion: str = "rrf",
        query_filter: dict | None = None, with_payload: bool | list[str] = True,
    ) -> list[dict]:
        """Fuse dense and indexed sparse candidates inside Qdrant using RRF/DBSF.

        Dense embeddings must match the snapshot's GTE model/revision and CLS
        pooling. Sparse token IDs/weights must match the encoder used to index
        the same points. This method does not tokenize text or build BM25.
        Returned scores are fusion scores, not cosine similarities.
        """
        if top_k < 1:
            raise ValueError("top_k must be positive")
        if prefetch_limit is None:
            prefetch_limit = max(100, top_k)
        if prefetch_limit < top_k:
            raise ValueError("prefetch_limit must be at least top_k")
        if fusion not in {"rrf", "dbsf"}:
            raise ValueError("fusion must be 'rrf' or 'dbsf'")
        sparse = self._sparse_query(sparse_vector)
        dense = self._dense_query(dense_vector)
        for branch in (dense, sparse):
            branch["limit"] = prefetch_limit
            if query_filter is not None:
                branch["filter"] = query_filter
        body = {
            "prefetch": [dense, sparse], "query": {"fusion": fusion},
            "limit": top_k, "with_payload": with_payload, "with_vector": False,
        }
        if query_filter is not None:
            body["filter"] = query_filter
        return self._request("POST", self._path + "/points/query", body)["points"]

    def search_text(self, dense_vector: Sequence[float], text: str, top_k: int = 10, **kwargs) -> list[dict]:
        """Use native BM25 inference for text; only the dense query needs encoding."""
        document = {"text": text, "model": "qdrant/bm25", "options": self.bm25_options}
        return self.search(dense_vector, document, top_k, **kwargs)

    def search_dense(
        self, dense_vector: Sequence[float], top_k: int = 10, *,
        query_filter: dict | None = None, with_payload: bool | list[str] = True,
    ) -> list[dict]:
        """Search the existing unnamed dense vector without requiring BM25."""
        if top_k < 1:
            raise ValueError("top_k must be positive")
        body = {
            **self._dense_query(dense_vector), "limit": top_k,
            "with_payload": with_payload, "with_vector": False,
        }
        if query_filter is not None:
            body["filter"] = query_filter
        return self._request("POST", self._path + "/points/query", body)["points"]

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
