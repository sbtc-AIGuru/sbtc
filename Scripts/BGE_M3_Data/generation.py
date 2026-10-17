"""Generate and judge evidence-grounded query labels with durable JSONL journals."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from time import monotonic
from typing import Any

from .common import json_hash, normalize_text, parse_model_json, read_jsonl, unique_rows, write_json
from .corpus import CJK, VIETNAMESE
from .models import Generator, batches


def generation_prompt(task: dict[str, Any], passage: dict[str, Any], config: dict[str, Any]) -> str:
    language = "Vietnamese" if task["query_language"] == "vi" else "Chinese"
    return (
        f"Create up to {config['questions_per_passage']} distinct natural retrieval questions in {language}. "
        "Each question must have a complete explicit answer in the passage below. "
        "Cover different facts rather than paraphrasing one fact. Prefer realistic user wording. "
        "Preserve age, dates, units, uncertainty, negation and other conditions. Do not add medical facts. "
        "A patient question, heading, advertisement, navigation or doctor signature is not answer evidence. "
        "Do not copy a question already present in the passage. Reject a passage with no useful answers. "
        "For each item quote one contiguous answer-bearing evidence span EXACTLY as written, "
        "in the original passage language. A short answer is for verification only. "
        'Return only {"items":[{"query":"...","evidence":"exact source span",'
        '"answer":"short supported answer","intent":"fact|cause|symptom|procedure|comparison|condition"}]}. '
        'Return {"items":[]} when unanswerable.\nPASSAGE:\n' + passage["text"]
    )


def validate_generated_item(item: Any, task: dict[str, Any], passage: dict[str, Any],
                            group_passages: list[dict[str, Any]]) -> dict[str, Any]:
    """Require literal source evidence and stable multi-positive chunk IDs."""
    if not isinstance(item, dict):
        raise ValueError("Generated item must be an object")
    for name in ("query", "evidence", "answer", "intent"):
        if not isinstance(item.get(name), str) or not item[name].strip():
            raise ValueError(f"Missing generated {name}")
    query = item["query"].strip()
    evidence = item["evidence"].strip()
    if len(query) < 8 or len(query) > 600:
        raise ValueError("Question length outside the accepted range")
    matches_language = (len(CJK.findall(query)) >= 4 if task["query_language"] == "zh"
                        else bool(VIETNAMESE.search(query)) and not CJK.search(query))
    if not matches_language:
        raise ValueError("Question does not match the requested language heuristic")
    if len(evidence) < (12 if task["passage_language"] == "zh" else 24):
        raise ValueError("Evidence is too short to support a specific answer")
    if evidence not in passage["text"]:
        raise ValueError("Evidence is not an exact substring of the positive passage")
    if normalize_text(query).rstrip("?\uff1f") in normalize_text(passage["text"]):
        raise ValueError("Question is copied from the passage")
    positive_ids = []
    spans = []
    ordered_passages = sorted(group_passages, key=lambda child: (child["chunk_id"] != passage["chunk_id"], child["chunk_id"]))
    for child in ordered_passages:
        position = child["text"].find(evidence)
        if position < 0:
            continue
        positive_ids.append(child["chunk_id"])
        spans.append({"chunk_id": child["chunk_id"], "start_char": position,
                      "end_char": position + len(evidence),
                      "source_start_char": child["start_char"] + position,
                      "source_end_char": child["start_char"] + position + len(evidence)})
        if len(positive_ids) == 8:
            break
    if passage["chunk_id"] not in positive_ids:
        raise ValueError("Anchor passage is missing from positives")
    return {
        "query_id": json_hash([task["task_id"], normalize_text(query)])[:32],
        "task_id": task["task_id"], "query": query, "query_hash": json_hash(normalize_text(query)),
        "anchor_chunk_id": passage["chunk_id"], "doc_id": passage["doc_id"],
        "group_id": task["group_id"], "split": task["split"],
        "query_language": task["query_language"], "passage_language": task["passage_language"],
        "positive_chunk_ids": sorted(positive_ids), "evidence": evidence,
        "evidence_spans": spans, "answer_for_verification": item["answer"].strip(),
        "intent": item["intent"], "human_relevance_label": False,
    }


def positive_judge_prompt(rows: list[dict[str, Any]], passage: dict[str, Any]) -> str:
    items = [{"id": index, "query": row["query"], "answer": row["answer_for_verification"],
              "evidence": row["evidence"]} for index, row in enumerate(rows)]
    return (
        "Independently verify each proposed question and answer against the passage. "
        "Use ONLY passage facts. A question in the source is not its own answer. "
        "Reject unsupported diagnoses, omitted conditions, changed age/dose/date, reversed negation, "
        "advertisements, unclear questions, translation errors and answers needing outside context. "
        "supported=true only when the complete answer is explicit and the quoted evidence supports it. "
        'Return only {"items":[{"id":0,"supported":true,"reason":"brief reason"}]}, '
        "one decision for every supplied id.\nPROPOSED:\n" + json.dumps(items, ensure_ascii=False)
        + "\nPASSAGE:\n" + passage["text"]
    )


def judge_decisions(content: str, expected_count: int, field: str) -> dict[int, dict[str, Any]]:
    payload = parse_model_json(content)
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != expected_count:
        raise ValueError("Judge did not return exactly one decision per candidate")
    result = {}
    for item in items:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            raise ValueError("Invalid judge item id")
        index = item["id"]
        if index not in range(expected_count) or index in result:
            raise ValueError("Duplicate or unexpected judge item id")
        if field == "supported" and type(item.get(field)) is not bool:
            raise ValueError("Judge supported flag must be a boolean")
        if field == "label" and item.get(field) not in {"answerable", "unanswerable", "uncertain"}:
            raise ValueError("Invalid negative-judge label")
        result[index] = item
    return result


def append_rows(stream: Any, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    stream.flush()


def generate_worker(work: Path, config: dict[str, Any], worker: int, workers: int,
                    device: str, limit_tasks: int | None = None) -> dict[str, Any]:
    """Resume one disjoint task shard; rejected tasks are recorded explicitly."""
    corpus = {row["chunk_id"]: row for row in read_jsonl(work / "corpus.jsonl")}
    groups = defaultdict(list)
    for row in corpus.values():
        groups[row["group_id"]].append(row)
    ledger_path = work / f"generation-ledger-{worker}.jsonl"
    done = set(unique_rows(list(work.glob("generation-ledger-*.jsonl")), "task_id"))
    tasks = [row for index, row in enumerate(read_jsonl(work / "tasks.jsonl"))
             if index % workers == worker and row["task_id"] not in done
             and (limit_tasks is None or index < limit_tasks)]
    started = monotonic()
    counts = Counter()
    if not tasks:
        return {"new_tasks": 0}
    model = Generator(config, device)
    path = work / f"queries-{worker}.jsonl"
    existing_queries = set(unique_rows(list(work.glob("queries-*.jsonl")), "query_id"))
    with path.open("a", encoding="utf-8") as output, ledger_path.open("a", encoding="utf-8") as ledger:
        for batch in batches(tasks, config["generation_batch_size"]):
            prompts = [generation_prompt(task, corpus[task["chunk_id"]], config) for task in batch]
            responses = model.complete(prompts)
            proposals = []
            errors = []
            for task, response in zip(batch, responses):
                accepted = []
                local_errors = Counter()
                try:
                    items = parse_model_json(response).get("items")
                    if not isinstance(items, list) or len(items) > config["questions_per_passage"]:
                        raise ValueError("Invalid generated items list")
                    query_hashes = set()
                    for item in items:
                        try:
                            row = validate_generated_item(item, task, corpus[task["chunk_id"]], groups[task["group_id"]])
                            if row["query_hash"] in query_hashes:
                                raise ValueError("Duplicate question within a task")
                            query_hashes.add(row["query_hash"])
                            accepted.append(row)
                        except ValueError as error:
                            local_errors[str(error)] += 1
                except ValueError as error:
                    local_errors[str(error)] += 1
                proposals.append(accepted)
                errors.append(local_errors)
            judge_indexes = [index for index, rows in enumerate(proposals) if rows]
            judged = {}
            for indexes in batches(judge_indexes, config["judge_batch_size"]):
                answers = model.complete([positive_judge_prompt(proposals[index], corpus[batch[index]["chunk_id"]])
                                          for index in indexes], max_new_tokens=256)
                for index, answer in zip(indexes, answers):
                    try:
                        judged[index] = judge_decisions(answer, len(proposals[index]), "supported")
                    except ValueError as error:
                        errors[index][str(error)] += 1
            for index, task in enumerate(batch):
                accepted = []
                for item_index, row in enumerate(proposals[index]):
                    decision = judged.get(index, {}).get(item_index)
                    if decision and decision["supported"]:
                        row.update(generator_model=config["generator_model"], generator_revision=model.revision,
                                   positive_judge=decision, label_status="synthetic_silver_positive_verified")
                        accepted.append(row)
                    else:
                        errors[index]["positive_judge_rejected_or_invalid"] += 1
                new_rows = [row for row in accepted if row["query_id"] not in existing_queries]
                append_rows(output, new_rows)
                existing_queries.update(row["query_id"] for row in new_rows)
                append_rows(ledger, [{"task_id": task["task_id"], "accepted_queries": len(accepted),
                                     "rejection_counts": dict(errors[index]), "generator_revision": model.revision}])
                counts["tasks"] += 1
                counts["accepted_queries"] += len(accepted)
                counts.update(errors[index])
            print(f"generate worker={worker} tasks={counts['tasks']}/{len(tasks)} queries={counts['accepted_queries']} elapsed={monotonic()-started:.0f}s", flush=True)
    report = {"new_tasks": counts["tasks"], "accepted_queries": counts["accepted_queries"],
              "counts": dict(counts), "elapsed_seconds": round(monotonic()-started, 2),
              "generator_revision": model.revision}
    write_json(work / f"generation-report-{worker}.json", report)
    return report


def negative_judge_prompt(query: str, candidates: list[dict[str, Any]]) -> str:
    passages = [{"id": index, "passage": candidate["text"]} for index, candidate in enumerate(candidates)]
    return (
        "For EACH passage decide whether it explicitly answers the query, in any language. "
        "Use passage evidence only. Another valid answer, an overlapping answer, or an answer "
        "with different wording is answerable and must NEVER become a negative. "
        "A passage is unanswerable only when it clearly lacks the information required by the query. "
        "Use uncertain whenever ambiguous, including partial answers or unclear conditions. "
        'Return only {"items":[{"id":0,"label":"answerable|unanswerable|uncertain"}]}, '
        "one decision for every id.\nQUERY:\n" + query + "\nPASSAGES:\n" + json.dumps(passages, ensure_ascii=False)
    )


def judge_negative_worker(work: Path, config: dict[str, Any], worker: int, workers: int,
                          device: str) -> dict[str, Any]:
    corpus = {row["chunk_id"]: row for row in read_jsonl(work / "corpus.jsonl")}
    path = work / f"negative-judgments-{worker}.jsonl"
    done = set(unique_rows(list(work.glob("negative-judgments-*.jsonl")), "query_id"))
    mined = unique_rows(list(work.glob("mined-*.jsonl")), "query_id")
    tasks = [row for index, row in enumerate(sorted(mined.values(), key=lambda row: row["query_id"]))
             if index % workers == worker and row["query_id"] not in done]
    if not tasks:
        return {"new_queries": 0}
    model = Generator(config, device)
    started = monotonic()
    counts = Counter()
    with path.open("a", encoding="utf-8") as output:
        # Small groups cap context usage even for long multilingual passages.
        for row in tasks:
            candidates = row["negative_candidates"][:config["negative_judge_candidates"]]
            decisions = []
            prompts = []
            groups = list(batches(candidates, 3))
            for group in groups:
                prompts.append(negative_judge_prompt(row["query"], [corpus[value["chunk_id"]] for value in group]))
            answers = []
            for prompt_group in batches(prompts, config["judge_batch_size"]):
                answers.extend(model.complete(prompt_group, max_new_tokens=160))
            for group, answer in zip(groups, answers):
                try:
                    judged = judge_decisions(answer, len(group), "label")
                except ValueError:
                    judged = {}
                    counts["invalid_judge_response"] += 1
                for index, candidate in enumerate(group):
                    label = judged.get(index, {}).get("label", "uncertain")
                    decisions.append({**candidate, "label": label})
                    counts[label] += 1
            verified = [candidate for candidate in decisions if candidate["label"] == "unanswerable"]
            append_rows(output, [{"query_id": row["query_id"], "negative_decisions": decisions,
                                 "verified_negative_candidates": verified,
                                 "generator_revision": model.revision}])
            counts["queries"] += 1
            if counts["queries"] % 10 == 0:
                print(f"judge-negatives worker={worker} queries={counts['queries']}/{len(tasks)} elapsed={monotonic()-started:.0f}s", flush=True)
    report = {"new_queries": counts["queries"], "counts": dict(counts),
              "generator_revision": model.revision, "elapsed_seconds": round(monotonic()-started, 2)}
    write_json(work / f"negative-judge-report-{worker}.json", report)
    return report
