"""Dense/BM25 retrieval and cross-encoder filtering without optional FAISS packages."""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import random
import sqlite3
from time import monotonic
from typing import Any

from .common import json_hash, read_jsonl, unique_rows, write_json, write_jsonl
from .generation import append_rows
from .models import Embedder, Reranker, batches


def lexical_terms(token_ids: list[int], special_ids: set[int]) -> str:
    """Let SQLite FTS5 BM25 use BGE subwords for both Vietnamese and Chinese."""
    return " ".join(f"t{value}" for value in token_ids if value not in special_ids)


def encode_corpus(work: Path, config: dict[str, Any], device: str) -> dict[str, Any]:
    """Encode bounded passages and keep token lengths and row-ID mapping together."""
    import numpy as np
    corpus = list(read_jsonl(work / "corpus.jsonl"))
    cache = work / "cache"
    cache.mkdir(exist_ok=True)
    report_path = cache / "encoding-report.json"
    signature = json_hash({"chunks": [(row["chunk_id"], row["text_hash"]) for row in corpus],
                           "model": config["embedder_model"], "revision": config["embedder_revision"],
                           "max_tokens": config["max_passage_tokens"]})
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["signature"] != signature:
            raise ValueError("Embedding cache belongs to a different corpus/configuration")
        for filename in ("vectors.npy", "eligible.jsonl", "bm25.sqlite3"):
            if not (cache / filename).is_file():
                raise FileNotFoundError(f"Incomplete embedding cache: {filename}")
        return report
    model = Embedder(config, device)
    special_ids = set(model.tokenizer.all_special_ids)
    eligible = []
    token_rows = []
    lengths = []
    counts = Counter()
    started = monotonic()
    for batch in batches(corpus, 256):
        ids = model.token_ids([row["text"] for row in batch])
        for row, values in zip(batch, ids):
            accepted = len(values) <= config["max_passage_tokens"]
            token_rows.append({"chunk_id": row["chunk_id"], "bge_tokens": len(values), "eligible": accepted})
            counts["eligible" if accepted else "overlong_passage"] += 1
            if accepted:
                eligible.append(row)
                lengths.append(len(values))
    if not eligible:
        raise ValueError("No passages fit the BGE token budget")
    # Sort by length to avoid padding every short passage to the longest one.
    ordered = sorted(zip(lengths, eligible), key=lambda value: (value[0], value[1]["chunk_id"]))
    eligible = [row for _, row in ordered]
    temporary = cache / "vectors.partial.npy"
    vectors = np.lib.format.open_memmap(temporary, mode="w+", dtype=np.float32, shape=(len(eligible), 1024))
    database_path = cache / "bm25.sqlite3"
    if database_path.exists():
        raise FileExistsError("Partial BM25 database exists; preserve it and use a new run directory")
    with sqlite3.connect(database_path) as database:
        database.execute("CREATE VIRTUAL TABLE passages USING fts5(terms)")
        database.execute("CREATE TABLE metadata (row_id INTEGER PRIMARY KEY, split TEXT NOT NULL)")
        for offset in range(0, len(eligible), config["encoding_batch_size"]):
            batch = eligible[offset:offset + config["encoding_batch_size"]]
            values = model.encode([row["text"] for row in batch], config["max_passage_tokens"])
            if values.shape != (len(batch), 1024):
                raise ValueError(f"Expected BGE-M3 shape {(len(batch), 1024)}, got {values.shape}")
            vectors[offset:offset + len(batch)] = values
            ids = model.token_ids([row["text"] for row in batch])
            database.executemany("INSERT INTO passages(rowid,terms) VALUES (?,?)",
                                 [(offset + index + 1, lexical_terms(value, special_ids)) for index, value in enumerate(ids)])
            database.executemany("INSERT INTO metadata(row_id,split) VALUES (?,?)",
                                 [(offset + index + 1, row["split"]) for index, row in enumerate(batch)])
            if offset % (config["encoding_batch_size"] * 100) == 0:
                database.commit()
                vectors.flush()
                print(f"encode passages={offset+len(batch)}/{len(eligible)} elapsed={monotonic()-started:.0f}s", flush=True)
        database.commit()
    vectors.flush()
    del vectors
    temporary.replace(cache / "vectors.npy")
    write_jsonl(cache / "eligible.jsonl", ({"chunk_id": row["chunk_id"], "row_id": index}
                                        for index, row in enumerate(eligible)))
    write_jsonl(work / "token_lengths.jsonl", token_rows)
    report = {"signature": signature, "counts": dict(counts), "dimension": 1024,
              "dtype": "float32", "normalized": True, "embedder_revision": model.revision,
              "elapsed_seconds": round(monotonic()-started, 2), "complete": True}
    write_json(report_path, report)
    return report


def candidate_allowed(candidate: dict[str, Any], query: dict[str, Any]) -> bool:
    return (candidate["group_id"] != query["group_id"]
            and candidate["chunk_id"] not in query["positive_chunk_ids"]
            and query["evidence"] not in candidate["text"]
            and not candidate.get("question_only_risk")
            and (query["split"] != "train" or candidate["split"] == "train"))


def select_candidates(query: dict[str, Any], corpus: list[dict[str, Any]],
                      dense_ids: list[int], lexical_ids: list[int],
                      config: dict[str, Any]) -> list[int]:
    """Fuse established retrieval rankings and add reproducible random candidates."""
    fused = Counter()
    for ranking in (dense_ids, lexical_ids):
        for rank, index in enumerate(ranking):
            if candidate_allowed(corpus[index], query):
                fused[index] += 1 / (60 + rank + 1)
    selected = [index for index, _ in fused.most_common(config["rerank_candidates"])]
    rng = random.Random(int(query["query_id"][:16], 16) ^ config["seed"])
    added = 0
    for _ in range(config["random_negative_candidates"] * 100):
        index = rng.randrange(len(corpus))
        if index not in selected and candidate_allowed(corpus[index], query):
            selected.append(index)
            added += 1
            if added >= config["random_negative_candidates"]:
                break
    return selected


def filter_teacher_candidates(query: dict[str, Any], positives: list[str], pos_scores: list[float],
                              candidates: list[dict[str, Any]], neg_scores: list[float],
                              config: dict[str, Any]) -> dict[str, Any] | None:
    if not positives or len(positives) != len(pos_scores) or len(candidates) != len(neg_scores):
        raise ValueError("Teacher score alignment failed")
    minimum_positive_logit = math.log(config["minimum_positive_probability"] / (1-config["minimum_positive_probability"]))
    maximum_negative_logit = math.log(config["maximum_negative_probability"] / (1-config["maximum_negative_probability"]))
    if max(pos_scores) < minimum_positive_logit:
        return None
    accepted_positives = [(identity, score) for identity, score in zip(positives, pos_scores)
                          if score >= minimum_positive_logit]
    anchor = query["anchor_chunk_id"]
    if anchor not in {identity for identity, _ in accepted_positives}:
        return None
    cutoff = min(maximum_negative_logit, min(score for _, score in accepted_positives) - config["minimum_reranker_margin"])
    accepted_negatives = [{"chunk_id": candidate["chunk_id"], "score": float(score)}
                          for candidate, score in zip(candidates, neg_scores)
                          if candidate_allowed(candidate, query) and score <= cutoff]
    accepted_negatives.sort(key=lambda value: (-value["score"], value["chunk_id"]))
    if len(accepted_negatives) < config["negative_count"]:
        return None
    return {**query, "positive_chunk_ids": [identity for identity, _ in accepted_positives],
            "pos_scores": [float(score) for _, score in accepted_positives],
            "negative_candidates": accepted_negatives[:config["negative_judge_candidates"]]}


def mine_worker(work: Path, config: dict[str, Any], worker: int, workers: int, device: str) -> dict[str, Any]:
    import numpy as np
    import torch
    all_corpus = {row["chunk_id"]: row for row in read_jsonl(work / "corpus.jsonl")}
    mapping = list(read_jsonl(work / "cache" / "eligible.jsonl"))
    corpus = [all_corpus[row["chunk_id"]] for row in mapping]
    positions = {row["chunk_id"]: index for index, row in enumerate(corpus)}
    values = np.load(work / "cache" / "vectors.npy", mmap_mode="r")
    if values.shape != (len(corpus), 1024) or values.dtype != np.float32:
        raise ValueError("Vector cache and metadata are not aligned")
    if any(row["row_id"] != index for index, row in enumerate(mapping)):
        raise ValueError("Non-contiguous vector row IDs")
    queries = unique_rows(list(work.glob("queries-*.jsonl")), "query_id")
    ledger_path = work / f"mining-ledger-{worker}.jsonl"
    done = set(unique_rows(list(work.glob("mining-ledger-*.jsonl")), "query_id"))
    selected = [row for index, row in enumerate(sorted(queries.values(), key=lambda value: value["query_id"]))
                if index % workers == worker and row["query_id"] not in done]
    if not selected:
        return {"new_queries": 0}
    embedder = Embedder(config, device)
    reranker = Reranker(config, device)
    vectors = torch.from_numpy(np.array(values, copy=True)).to(device=device, dtype=torch.float16)
    train_mask = torch.tensor([row["split"] == "train" for row in corpus], device=device, dtype=torch.bool)
    special_ids = set(embedder.tokenizer.all_special_ids)
    counts = Counter()
    started = monotonic()
    output_path = work / f"mined-{worker}.jsonl"
    existing = set(unique_rows(list(work.glob("mined-*.jsonl")), "query_id"))
    database_uri = (work / "cache" / "bm25.sqlite3").resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as database, output_path.open("a", encoding="utf-8") as output, ledger_path.open("a", encoding="utf-8") as ledger:
        for row in selected:
            positive_ids = [identity for identity in row["positive_chunk_ids"] if identity in positions]
            query_ids = embedder.token_ids([row["query"]])[0]
            reason = None
            if row["anchor_chunk_id"] not in positive_ids:
                reason = "positive_over_token_budget"
            elif len(query_ids) > config["max_query_tokens"]:
                reason = "query_over_token_budget"
            result = None
            if reason is None:
                query_vector = torch.from_numpy(embedder.encode([row["query"]], config["max_query_tokens"])).to(device=device, dtype=torch.float16)
                with torch.inference_mode():
                    similarities = (query_vector @ vectors.T).flatten()
                    if row["split"] == "train":
                        similarities = similarities.masked_fill(~train_mask, float("-inf"))
                    dense_ids = torch.topk(similarities, min(config["retrieval_candidates"], len(corpus))).indices.cpu().tolist()
                terms = sorted(set(lexical_terms(query_ids, special_ids).split()))
                lexical_ids = []
                if terms:
                    match = " OR ".join(f'"{term}"' for term in terms)
                    restriction = " AND metadata.split='train'" if row["split"] == "train" else ""
                    lexical_ids = [value[0] - 1 for value in database.execute(
                        "SELECT passages.rowid FROM passages JOIN metadata ON passages.rowid=metadata.row_id "
                        "WHERE passages MATCH ?" + restriction + " ORDER BY bm25(passages) LIMIT ?",
                        (match, config["retrieval_candidates"]))]
                candidate_ids = select_candidates(row, corpus, dense_ids, lexical_ids, config)
                candidates = [corpus[index] for index in candidate_ids]
                pairs = [(row["query"], corpus[positions[identity]]["text"]) for identity in positive_ids]
                pairs.extend((row["query"], candidate["text"]) for candidate in candidates)
                scores = reranker.score(pairs)
                result = filter_teacher_candidates(row, positive_ids, scores[:len(positive_ids)],
                                                   candidates, scores[len(positive_ids):], config)
                if result is None:
                    reason = "teacher_rejected_positive_or_insufficient_negatives"
                else:
                    result["baseline_dense_top10"] = [corpus[index]["chunk_id"] for index in dense_ids[:10]]
            if result is not None:
                result.update(embedder_revision=embedder.revision, reranker_revision=reranker.revision)
                if result["query_id"] not in existing:
                    append_rows(output, [result])
                    existing.add(result["query_id"])
                counts["accepted_queries"] += 1
            else:
                counts[str(reason)] += 1
            append_rows(ledger, [{"query_id": row["query_id"], "accepted": result is not None, "reason": reason}])
            counts["queries"] += 1
            if counts["queries"] % 20 == 0:
                print(f"mine worker={worker} queries={counts['queries']}/{len(selected)} accepted={counts['accepted_queries']} elapsed={monotonic()-started:.0f}s", flush=True)
    report = {"new_queries": counts["queries"], "counts": dict(counts),
              "embedder_revision": embedder.revision, "reranker_revision": reranker.revision,
              "elapsed_seconds": round(monotonic()-started, 2)}
    write_json(work / f"mining-report-{worker}.json", report)
    return report
