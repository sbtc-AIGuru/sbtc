"""Dense Qdrant + language-specific Elasticsearch BM25, with existing RRF semantics."""

from copy import deepcopy

import numpy as np

from ..Database.elastic_search import search_bm25
from ..Database.qdrant_db import parse_dense_weight

QUERY_KEYS = ("original_query", "eng_query", "chinese_query")


def elastic_filter(condition):
    """Translate shared keyword filters; reject unsupported Qdrant-only conditions."""
    if "key" in condition:
        key = condition["key"]
        if set(condition) != {"key", "match"} or key not in {"doc_id", "chunk_id", "lang"}:
            raise ValueError("Elasticsearch supports match filters on doc_id, chunk_id and lang only")
        match = condition["match"]
        if set(match) == {"value"}:
            return {"term": {key: str(match["value"])}}
        if set(match) in ({"any"}, {"except"}):
            operator = next(iter(match))
            terms = {"terms": {key: [str(value) for value in match[operator]]}}
            return terms if operator == "any" else {"bool": {"must_not": [terms]}}
        raise ValueError("Unsupported match filter for Elasticsearch")
    if set(condition) - {"must", "should", "must_not", "min_should"}:
        raise ValueError("Unsupported Qdrant filter for Elasticsearch")
    result = {}
    for operator in ("must", "should", "must_not"):
        if operator in condition:
            values = condition[operator]
            values = values if isinstance(values, list) else [values]
            result[operator] = [elastic_filter(value) for value in values]
    if result.get("should"):
        result["minimum_should_match"] = 1
    if "min_should" in condition:
        group = condition["min_should"]
        result.setdefault("must", []).append({"bool": {
            "should": [elastic_filter(value) for value in group["conditions"]],
            "minimum_should_match": group["min_count"],
        }})
    return {"bool": result}


def normalize_hit(hit, *, elastic=False):
    payload = dict(hit["_source"] if elastic else hit["payload"])
    if "chunk_text" not in payload and "content" in payload:
        payload["chunk_text"] = payload["content"]
    chunk_id = payload.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id.strip():
        raise ValueError("Search result must contain the original chunk_id")
    return {"id": hit.get("_id") if elastic else hit.get("id"), "payload": payload}


def weighted_rrf(branches, weights, top_k):
    """Match Qdrant's f32 rank weighting: 1 / ((position + 1) / weight + k - 1).

    k=2, zero-based positions. See Qdrant reciprocal_rank_fusion.rs (v1.19.2).
    Chunk IDs join the stores; their UUID and SHA-256 point IDs differ.
    """
    points = {}
    for hits, weight in zip(branches, weights, strict=True):
        if weight <= 0:
            continue
        seen = set()
        for position, hit in enumerate(hits):
            payload = hit["payload"]
            key = payload["chunk_id"]
            duplicate = key in seen
            seen.add(key)
            if key not in points:
                points[key] = {**hit, "payload": deepcopy(payload), "score": np.float32(0)}
            point = points[key]
            for field in ("doc_id", "chunk_text"):
                old, new = point["payload"].get(field), payload.get(field)
                if old is not None and new is not None:
                    if (str(old) if field == "doc_id" else old) != (str(new) if field == "doc_id" else new):
                        raise ValueError(f"Conflicting {field} across stores for chunk {key}")
                elif new is not None:
                    point["payload"][field] = new
            if duplicate:
                continue
            contribution = np.float32(1) / (np.float32(position + 1) / np.float32(weight) + np.float32(1))
            point["score"] = np.float32(point["score"] + contribution)
    # Equal scores keep branch/first-appearance order; Qdrant leaves ties unspecified.
    result = sorted(points.values(), key=lambda point: point["score"], reverse=True)[:top_k]
    for point in result:
        point["score"] = float(point["score"])
    return result


class HybridRetriever:
    def __init__(self, qdrant, elastic_client, index):
        self.qdrant, self.elastic_client, self.index = qdrant, elastic_client, index

    def query(self, query, *, multilingual_dense, top_k, branch_limit, dense_weight,
              query_filter=None, include_bm25=True, hnsw_ef=None):
        weight = parse_dense_weight(dense_weight) if include_bm25 else 1.0
        filters = [elastic_filter(query_filter)] if query_filter is not None and weight < 1 else None
        branches, weights = [], []
        if weight > 0:
            texts = [query[key] for key in QUERY_KEYS[:3 if multilingual_dense else 1]]
            vectors = self.qdrant.dense_encoder(texts)
            if len(vectors) != len(texts):
                raise ValueError("Encoder must return one dense vector per query text")
            for vector in vectors:
                hits = self.qdrant.search_dense(vector, top_k=branch_limit,
                                                 query_filter=query_filter, with_payload=True,
                                                 hnsw_ef=hnsw_ef)
                branches.append([normalize_hit(hit) for hit in hits])
                weights.append(weight / len(texts))
        if weight < 1:
            for key, lang in zip(QUERY_KEYS, ("vi", "en", "zh"), strict=True):
                hits = search_bm25(query[key], lang, branch_limit, client=self.elastic_client,
                                   index=self.index, filters=filters)
                branches.append([normalize_hit(hit, elastic=True) for hit in hits])
                weights.append((1 - weight) / 3)
        return weighted_rrf(branches, weights, top_k)
