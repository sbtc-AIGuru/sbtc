"""Stream, filter, group and sample the existing paragraph-v3 corpus."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterator
import hashlib
import json
from pathlib import Path
import random
import re
from time import monotonic
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .common import PIPELINE_VERSION, json_hash, normalize_text, text_hash, write_json, write_jsonl


CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
VIETNAMESE = re.compile(r"[\u0102\u0103\u00c2\u00e2\u0110\u0111\u00ca\u00ea\u00d4\u00f4\u01a0\u01a1\u01af\u01b0\u1ea0-\u1ef9]")
AD_MARKERS = re.compile(r"\u9884\u7ea6\u6302\u53f7|\u5728\u7ebf\u9884\u7ea6|\u533b\u9662\u6392\u540d|\u533b\u9662\u6392\u884c|\u70ed\u95e8\u533b\u9662|\u540d\u533b\u5728\u7ebf")
PREVIEW_MARKER = "\u663e\u793a\u5168\u90e8"
QA_ANSWER_MARKERS = re.compile(r"\u75c5\u60c5\u5206\u6790|\u6307\u5bfc\u610f\u89c1|\u533b\u751f\u56de\u590d|\u56de\u7b54|tr\u1ea3 l\u1eddi|gi\u1ea3i \u0111\u00e1p", re.IGNORECASE)
QA_QUESTION_MARKERS = re.compile(r"\u5065\u5eb7\u54a8\u8be2\u63cf\u8ff0|\u60f3\u5f97\u5230\u600e\u6837\u7684\u5e2e\u52a9|\u60a3\u8005\u54a8\u8be2")
TRACKING_PARAMETERS = {"fbclid", "gclid", "dclid", "ref", "source"}


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMETERS]
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path,
                       urlencode(sorted(query)), ""))


def infer_language(text: str) -> str:
    """Use an explicit script heuristic; this is not a language-ID model."""
    cjk = len(CJK.findall(text))
    letters = sum(character.isalpha() for character in text)
    if cjk >= 8 and cjk / max(letters, 1) >= 0.25:
        return "zh"
    if len(VIETNAMESE.findall(text)) >= 3:
        return "vi"
    return "unknown"


def iter_documents(path: Path, digest: Any) -> Iterator[dict[str, Any]]:
    """Validate the exported array while computing its full original checksum."""
    with path.open("rb") as stream:
        first = stream.readline()
        digest.update(first)
        if first.strip() != b"[":
            raise ValueError("Expected '[' on the first line of merged.json")
        previous_comma = True
        seen_document = False
        for number, line in enumerate(stream, 2):
            digest.update(line)
            raw = line.strip()
            if not raw:
                continue
            if raw == b"]":
                if seen_document and previous_comma:
                    raise ValueError("Trailing comma in merged.json")
                for tail in stream:
                    digest.update(tail)
                    if tail.strip():
                        raise ValueError("Unexpected content after merged.json")
                return
            if not previous_comma:
                raise ValueError(f"Missing separator at line {number}")
            previous_comma = raw.endswith(b",")
            if previous_comma:
                raw = raw[:-1]
            try:
                document = json.loads(raw)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid document JSON at line {number}") from error
            if not isinstance(document, dict):
                raise ValueError(f"Expected document object at line {number}")
            seen_document = True
            yield document
        raise ValueError("Missing closing ']' in merged.json")


def passage_rejection(child: dict[str, Any], language: str, config: dict[str, Any]) -> str | None:
    text = child.get("chunk_text")
    if child.get("retrieval_eligible") is not True or not isinstance(text, str) or not text.strip():
        return "ineligible_or_empty"
    if len(text.strip()) < config["min_passage_chars"][language]:
        return "short_or_heading"
    if len(AD_MARKERS.findall(text)) >= 2:
        return "hospital_advertising"
    lowered = normalize_text(text)
    if "hotline" in lowered and ("\u0111\u1eb7t l\u1ecbch" in lowered or "\u0111\u0103ng k\u00fd" in lowered):
        return "booking_advertising"
    if PREVIEW_MARKER in text and ("..." in text or "\u2026" in text):
        return "incomplete_preview"
    start, end = child.get("start_char"), child.get("end_char")
    if not isinstance(start, int) or not isinstance(end, int) or end - start != len(text):
        return "invalid_character_span"
    return None


def filtered_document(document: dict[str, Any], language: str,
                      config: dict[str, Any], rejected: Counter) -> dict[str, Any] | None:
    children = []
    identities = set()
    for child in document.get("children", []):
        reason = passage_rejection(child, language, config)
        if reason:
            rejected[reason] += 1
            continue
        identity = text_hash(child["chunk_text"])
        if identity in identities:
            rejected["within_document_duplicate"] += 1
            continue
        identities.add(identity)
        children.append({
            "chunk_id": child["chunk_id"], "doc_id": document["doc_id"],
            "parent_id": child["parent_id"], "start_char": child["start_char"],
            "end_char": child["end_char"], "text": child["chunk_text"], "text_hash": identity,
            "chunk_order": child["chunk_order"], "language": language,
        })
    if not children:
        return None
    first_text = document["children"][0].get("chunk_text", "")
    title = normalize_text(first_text.split("\n", 1)[0])[:180]
    return {
        "doc_id": document["doc_id"], "url": document["url"],
        "canonical_url": canonical_url(document["url"]),
        "source_sha256": document.get("source_sha256") or document.get("raw_sha256")
        or json_hash(sorted(identities)), "domain": urlsplit(document["url"]).netloc.casefold(),
        "language": language, "doc_type": document.get("doc_type"), "title": title,
        "children": children,
    }


def group_documents(documents: list[dict[str, Any]], reserved: list[dict[str, Any]],
                    config: dict[str, Any]) -> dict[str, Any]:
    """Conservatively group exact duplicates, shared paragraphs and equal titles."""
    parents = list(range(len(documents)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left != right:
            parents[max(left, right)] = min(left, right)

    keys = {}
    reserved_keys = set()
    for document in reserved:
        reserved_keys.update((f"hash:{document['source_sha256']}", f"url:{document['canonical_url']}"))
        reserved_keys.update(f"chunk:{child['text_hash']}" for child in document["children"])
        if len(document["title"]) >= 12:
            reserved_keys.add(f"title:{document['language']}:{document['title']}")
    blocked = set()
    for index, document in enumerate(documents):
        document_keys = [f"hash:{document['source_sha256']}", f"url:{document['canonical_url']}"]
        document_keys.extend(f"chunk:{child['text_hash']}" for child in document["children"])
        if len(document["title"]) >= 12:
            document_keys.append(f"title:{document['language']}:{document['title']}")
        for key in document_keys:
            if key in keys:
                union(index, keys[key])
            else:
                keys[key] = index
            if key in reserved_keys:
                blocked.add(index)
    members = defaultdict(list)
    for index in range(len(documents)):
        members[find(index)].append(index)
    blocked_roots = {find(index) for index in blocked}
    for root, indexes in members.items():
        group_id = json_hash(sorted(str(documents[index]["doc_id"]) for index in indexes))[:24]
        fraction = int(hashlib.sha256(f"{config['seed']}:{group_id}".encode()).hexdigest()[:12], 16) / 16**12
        if root in blocked_roots or fraction < config["test_fraction"]:
            split = "test"
        elif fraction < config["test_fraction"] + config["validation_fraction"]:
            split = "validation"
        else:
            split = "train"
        for index in indexes:
            documents[index].update(group_id=group_id, split=split)
    return {"groups": len(members), "largest_group_documents": max(map(len, members.values()), default=0),
            "benchmark_related_groups_reserved_for_test": len(blocked_roots),
            "grouping": "source hash, canonical URL, exact useful chunk, normalized equal title; no global semantic near-duplicate claim"}


def sample_tasks(corpus: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    rng = random.Random(config["seed"] + 1)
    candidates = list(corpus)
    rng.shuffle(candidates)
    buckets = defaultdict(list)
    per_document = Counter()
    for child in candidates:
        if child.get("question_only_risk"):
            continue
        if per_document[child["doc_id"]] >= config["max_query_passages_per_document"]:
            continue
        per_document[child["doc_id"]] += 1
        buckets[(child["language"], child["domain"])].append(child)
    selected = []
    for language, weight in config["query_language_weights"].items():
        target = round(config["query_passages"] * weight)
        source_keys = sorted(key for key in buckets if key[0] == language)
        rng.shuffle(source_keys)
        while source_keys and target:
            next_sources = []
            for key in source_keys:
                if buckets[key] and target:
                    selected.append(buckets[key].pop())
                    target -= 1
                if buckets[key]:
                    next_sources.append(key)
            source_keys = next_sources
    tasks = []
    for child in selected:
        query_language = child["language"]
        if query_language == "zh" and rng.random() < config["vietnamese_queries_for_chinese"]:
            query_language = "vi"
        tasks.append({"task_id": json_hash([child["chunk_id"], query_language])[:24],
                      "chunk_id": child["chunk_id"], "doc_id": child["doc_id"],
                      "group_id": child["group_id"], "split": child["split"],
                      "passage_language": child["language"], "query_language": query_language})
    rng.shuffle(tasks)
    return tasks


def prepare(input_path: Path, work: Path, config: dict[str, Any],
            holdout_paths: list[Path], expected_sha256: str | None = None) -> dict[str, Any]:
    """Create a bounded, balanced corpus without modifying the source dataset."""
    holdout_ids = set()
    holdout_hashes = []
    for path in holdout_paths:
        values = json.loads(path.read_text(encoding="utf-8"))
        holdout_hashes.append(json_hash(values))
        holdout_ids.update(item["source_doc_id"] for item in values)
    signature = json_hash({"config": config, "holdouts": sorted(holdout_hashes), "version": PIPELINE_VERSION})
    manifest_path = work / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["configuration_sha256"] != signature:
            raise ValueError("Existing output has a different configuration; use a new output directory")
        if manifest["source_size_bytes"] != input_path.stat().st_size:
            raise ValueError("Existing output belongs to a different source size")
        if expected_sha256 and manifest["source_sha256"] != expected_sha256:
            raise ValueError("Existing output belongs to a different source checksum")
        return manifest
    if work.exists() and any(work.iterdir()):
        raise FileExistsError("Refusing to write into a nonempty directory without a pipeline manifest")
    work.mkdir(parents=True, exist_ok=True)
    rng = random.Random(config["seed"])
    seen = Counter()
    counts = Counter()
    rejected = Counter()
    reservoirs = defaultdict(list)
    reserved = []
    digest = hashlib.sha256()
    started = last_log = monotonic()
    for document in iter_documents(input_path, digest):
        counts["documents_scanned"] += 1
        counts["source_chunks"] += len(document.get("children", []))
        if document.get("status") != "ok" or not document.get("children"):
            counts["skipped_or_empty_documents"] += 1
            continue
        sample = "\n".join(child.get("chunk_text", "") for child in document["children"][:2])[:2500]
        language = infer_language(sample)
        if language not in config["query_language_weights"]:
            counts["unknown_language_documents"] += 1
            continue
        key = (language, urlsplit(document["url"]).netloc.casefold())
        seen[key] += 1
        bucket = reservoirs[key]
        replacement = len(bucket) if len(bucket) < config["documents_per_source"] else rng.randrange(seen[key])
        is_reserved = document["doc_id"] in holdout_ids
        if replacement < config["documents_per_source"] or is_reserved:
            counts["quality_evaluated_sampled_documents"] += 1
            filtered = filtered_document(document, language, config, rejected)
            if filtered:
                if is_reserved:
                    reserved.append(filtered)
                if replacement < config["documents_per_source"]:
                    if replacement == len(bucket):
                        bucket.append(filtered)
                    else:
                        bucket[replacement] = filtered
        if monotonic() - last_log >= 30:
            print(f"prepare documents={counts['documents_scanned']:,} source_chunks={counts['source_chunks']:,} elapsed={monotonic()-started:.0f}s", flush=True)
            last_log = monotonic()
    if expected_sha256 and digest.hexdigest() != expected_sha256:
        raise ValueError("The complete source checksum does not match the expected merged.json")
    documents_by_id = {document["doc_id"]: document for bucket in reservoirs.values() for document in bucket}
    documents_by_id.update({document["doc_id"]: document for document in reserved})
    documents = sorted(documents_by_id.values(), key=lambda document: str(document["doc_id"]))
    grouping = group_documents(documents, reserved, config)
    rng.shuffle(documents)
    corpus = []
    identities = set()
    for document in documents:
        document_text = "\n".join(child["text"] for child in document["children"])
        question_only_risk = bool(document["doc_type"] == "qa" and QA_QUESTION_MARKERS.search(document_text)
                                  and not QA_ANSWER_MARKERS.search(document_text))
        for child in document["children"]:
            if len(corpus) >= config["max_corpus_chunks"]:
                break
            if child["text_hash"] in identities:
                counts["selected_duplicate_chunks_removed"] += 1
                continue
            identities.add(child["text_hash"])
            corpus.append({**child, "url": document["url"], "domain": document["domain"],
                           "doc_type": document["doc_type"], "source_sha256": document["source_sha256"],
                           "group_id": document["group_id"], "split": document["split"],
                           "question_only_risk": question_only_risk})
    tasks = sample_tasks(corpus, config)
    if not tasks or len(corpus) < config["negative_count"] + 1:
        raise ValueError("Insufficient useful passages after filtering")
    write_jsonl(work / "corpus.jsonl", corpus)
    write_jsonl(work / "tasks.jsonl", tasks)
    manifest = {
        "pipeline_version": PIPELINE_VERSION, "configuration_sha256": signature,
        "configuration": config, "source_path": str(input_path),
        "source_size_bytes": input_path.stat().st_size, "source_sha256": digest.hexdigest(),
        "holdout_query_file_sha256": sorted(holdout_hashes), "reserved_benchmark_documents_found": len(reserved),
        "stages": {"prepare": {**counts, **grouping, "sampled_chunk_rejections": dict(rejected),
                    "corpus_chunks": len(corpus), "generation_tasks": len(tasks),
                    "corpus_by_language": dict(Counter(row["language"] for row in corpus)),
                    "corpus_by_split": dict(Counter(row["split"] for row in corpus)),
                    "tasks_by_query_language": dict(Counter(row["query_language"] for row in tasks)),
                    "tasks_by_split": dict(Counter(row["split"] for row in tasks)),
                    "elapsed_seconds": round(monotonic()-started, 2), "complete": True}},
        "label_status": "synthetic silver; no human relevance judgments",
    }
    write_json(manifest_path, manifest)
    print(json.dumps(manifest["stages"]["prepare"], ensure_ascii=False), flush=True)
    return manifest
