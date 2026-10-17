"""Export validated FlagEmbedding triplets, silver qrels and a human-review sample."""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any
import zipfile

from .common import load_manifest, read_jsonl, record_stage, unique_rows, write_json, write_jsonl
from .mining import candidate_allowed


def validate_triplet(row: dict[str, Any], corpus: dict[str, dict[str, Any]],
                     negative_count: int) -> None:
    """Check evidence, score alignment, duplicates and split isolation before export."""
    positives = row["positive_chunk_ids"]
    negatives = row["negative_chunk_ids"]
    if not positives or len(negatives) != negative_count:
        raise ValueError("Incorrect positive/negative counts")
    if len(set(positives)) != len(positives) or len(set(negatives)) != len(negatives):
        raise ValueError("Repeated chunk IDs in a training row")
    if set(positives) & set(negatives):
        raise ValueError("Positive and negative IDs overlap")
    if len(row["pos_scores"]) != len(positives) or len(row["neg_scores"]) != len(negatives):
        raise ValueError("Teacher scores are not aligned with text")
    if not all(math.isfinite(value) for value in row["pos_scores"] + row["neg_scores"]):
        raise ValueError("Nonfinite teacher scores")
    if row.get("positive_judge", {}).get("supported") is not True:
        raise ValueError("Positive has no affirmative evidence judgment")
    decisions = {value["chunk_id"]: value for value in row.get("negative_judgments", [])}
    teacher = {value["chunk_id"]: value["score"] for value in row.get("negative_candidates", [])}
    for identity, score in zip(negatives, row["neg_scores"]):
        if decisions.get(identity, {}).get("label") != "unanswerable":
            raise ValueError("Negative has no explicit unanswerable judgment")
        if teacher.get(identity) != score or decisions[identity].get("score") != score:
            raise ValueError("Negative judgment/teacher score mismatch")
    for identity in positives:
        passage = corpus[identity]
        if passage["split"] != row["split"] or passage["group_id"] != row["group_id"]:
            raise ValueError("Positive split/group mismatch")
        if row["evidence"] not in passage["text"]:
            raise ValueError("Positive does not contain the declared evidence")
    negative_hashes = set()
    for identity in negatives:
        passage = corpus[identity]
        if not candidate_allowed(passage, row):
            raise ValueError("Unsafe negative: duplicate group, evidence or held-out training passage")
        if passage["text_hash"] in negative_hashes:
            raise ValueError("Duplicate negative text")
        negative_hashes.add(passage["text_hash"])
    if row.get("human_relevance_label") is not False:
        raise ValueError("Synthetic records must not claim human relevance labels")


def retrieval_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    recall = reciprocal = ndcg = 0.0
    for row in rows:
        positives = set(row["positive_chunk_ids"])
        ranking = row.get("baseline_dense_top10", [])
        hits = [index for index, identity in enumerate(ranking) if identity in positives]
        recall += len(hits) / len(positives)
        if hits:
            reciprocal += 1 / (hits[0] + 1)
        dcg = sum(1 / math.log2(index + 2) for index in hits)
        ideal = sum(1 / math.log2(index + 2) for index in range(min(len(positives), 10)))
        ndcg += dcg / ideal if ideal else 0
    count = len(rows)
    return {"queries": count, "Recall@10": recall / count if count else None,
            "MRR@10": reciprocal / count if count else None,
            "nDCG@10": ndcg / count if count else None,
            "labels": "synthetic silver; incomplete relevance judgments, not human gold",
            "search": "exact normalized dense dot products computed in float16 on the pilot corpus"}


def export_dataset(work: Path, config: dict[str, Any], allow_small: bool = False) -> dict[str, Any]:
    corpus = {row["chunk_id"]: row for row in read_jsonl(work / "corpus.jsonl")}
    eligible = {row["chunk_id"] for row in read_jsonl(work / "cache" / "eligible.jsonl")}
    mined = unique_rows(list(work.glob("mined-*.jsonl")), "query_id")
    judgments = unique_rows(list(work.glob("negative-judgments-*.jsonl")), "query_id")
    counts = Counter()
    rows = []
    query_hashes = set()
    priority = {"test": 0, "validation": 1, "train": 2}
    for row in sorted(mined.values(), key=lambda value: (priority[value["split"]], value["query_id"])):
        if row["query_hash"] in query_hashes:
            counts["duplicate_question_removed"] += 1
            continue
        judgment = judgments.get(row["query_id"])
        if judgment is None:
            counts["missing_negative_judgment"] += 1
            continue
        candidates = judgment["verified_negative_candidates"][:config["negative_count"]]
        if len(candidates) != config["negative_count"]:
            counts["insufficient_verified_negatives"] += 1
            continue
        result = {**row, "negative_chunk_ids": [candidate["chunk_id"] for candidate in candidates],
                  "neg_scores": [candidate["score"] for candidate in candidates],
                  "negative_judgments": judgment["negative_decisions"],
                  "label_status": "synthetic_silver_positive_and_negative_verified"}
        validate_triplet(result, corpus, config["negative_count"])
        if not set(result["positive_chunk_ids"] + result["negative_chunk_ids"]) <= eligible:
            raise ValueError("Export contains a passage outside the validated BGE token budget")
        query_hashes.add(row["query_hash"])
        rows.append(result)
    task_ids = {row["task_id"] for row in read_jsonl(work / "tasks.jsonl")}
    completed = unique_rows(list(work.glob("generation-ledger-*.jsonl")), "task_id")
    generation_complete = task_ids <= set(completed)
    generated = unique_rows(list(work.glob("queries-*.jsonl")), "query_id")
    mining_complete = set(generated) <= set(unique_rows(list(work.glob("mining-ledger-*.jsonl")), "query_id"))
    judgment_complete = set(mined) <= set(judgments)
    split_counts = Counter(row["split"] for row in rows)
    quality_sufficient = (split_counts["train"] >= config["minimum_export_train_queries"]
                          and split_counts["validation"] >= config["minimum_export_eval_queries"]
                          and split_counts["test"] >= config["minimum_export_eval_queries"])
    destination = work / "dataset"
    destination.mkdir(exist_ok=True)
    for split in ("train", "validation", "test"):
        write_jsonl(destination / f"{split}.jsonl", (
            {"query": row["query"], "pos": [corpus[identity]["text"] for identity in row["positive_chunk_ids"]],
             "neg": [corpus[identity]["text"] for identity in row["negative_chunk_ids"]],
             "pos_scores": row["pos_scores"], "neg_scores": row["neg_scores"]}
            for row in rows if row["split"] == split))
    write_jsonl(destination / "provenance.jsonl", rows)
    evaluation = destination / "evaluation"
    evaluation.mkdir(exist_ok=True)
    write_jsonl(evaluation / "corpus.jsonl", (
        {"_id": row["chunk_id"], "title": "", "text": row["text"]}
        for row in corpus.values() if row["chunk_id"] in eligible))
    write_jsonl(evaluation / "queries.jsonl", (
        {"_id": row["query_id"], "text": row["query"], "split": row["split"],
         "query_language": row["query_language"], "label_status": "synthetic_silver", "human_relevance_label": False}
        for row in rows if row["split"] != "train"))
    with (evaluation / "qrels.tsv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["query-id", "corpus-id", "score"])
        for row in rows:
            if row["split"] != "train":
                writer.writerows((row["query_id"], identity, 1) for identity in row["positive_chunk_ids"])
    rng = random.Random(config["seed"])
    review_rows = rng.sample(rows, min(len(rows), config["review_sample_size"]))
    with (destination / "human_review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["query_id", "split", "query", "positive_text", "evidence",
                                                     "negative_texts", "positive_correct", "negatives_correct", "notes"])
        writer.writeheader()
        for row in review_rows:
            writer.writerow({"query_id": row["query_id"], "split": row["split"], "query": row["query"],
                             "positive_text": corpus[row["anchor_chunk_id"]]["text"], "evidence": row["evidence"],
                             "negative_texts": json.dumps([corpus[identity]["text"] for identity in row["negative_chunk_ids"]], ensure_ascii=False)})
    report = {
        "exported_queries": len(rows), "queries_by_split": dict(split_counts),
        "queries_by_language": dict(Counter(row["query_language"] for row in rows)),
        "queries_by_language_pair": dict(Counter(f"{row['query_language']}->{row['passage_language']}" for row in rows)),
        "dropped": dict(counts), "generation_complete": generation_complete,
        "mining_complete": mining_complete, "negative_judgment_complete": judgment_complete,
        "quality_thresholds_met": quality_sufficient,
        "dataset_complete": generation_complete and mining_complete and judgment_complete and quality_sufficient,
        "label_status": "synthetic silver, not human-validated gold",
        "evaluation_corpus_chunks": len(eligible),
        "baseline": {split: retrieval_metrics([row for row in rows if row["split"] == split])
                     for split in ("validation", "test")},
    }
    record_stage(work, "export", report)
    write_json(destination / "report.json", report)
    write_json(destination / "manifest.json", load_manifest(work))
    hashes = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file() and path.name != "checksums.json":
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            hashes[str(path.relative_to(destination))] = digest.hexdigest()
    write_json(destination / "checksums.json", hashes)
    temporary = work / "bge_m3_dataset.zip.tmp"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                archive.write(path, str(path.relative_to(destination)))
    temporary.replace(work / "bge_m3_dataset.zip")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report["dataset_complete"] and not allow_small:
        raise RuntimeError("Dataset saved, but completion/size gates failed; see dataset/report.json. No quality rules were relaxed.")
    return report
