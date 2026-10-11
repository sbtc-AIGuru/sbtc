"""Numerical and safety regression checks for the HNSW benchmark."""
from pathlib import Path

import faiss
import numpy as np
import pytest

from BackEnd.tests.benchmark_faiss import sha256
from BackEnd.tests.benchmark_hnsw import (
    MemoryMonitor,
    build_exact_index,
    latency_benchmark,
    per_query_recall,
    score_admissibility,
    validate_index,
    write_json,
)


@pytest.fixture
def small_index():
    previous_threads = faiss.omp_get_max_threads()
    faiss.omp_set_num_threads(1)
    vectors = np.random.default_rng(42).normal(size=(128, 16)).astype(np.float32)
    faiss.normalize_L2(vectors)
    index = faiss.IndexHNSWFlat(16, 8, faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = 40
    index.hnsw.efSearch = 64
    index.add(vectors)
    metadata = {str(i): {"doc_id": i} for i in range(len(vectors))}
    try:
        yield index, vectors, metadata
    finally:
        faiss.omp_set_num_threads(previous_threads)


def test_exact_reference_uses_original_vectors_and_preserves_input(small_index, tmp_path: Path) -> None:
    index, vectors, metadata = small_index
    path = tmp_path / "source.faiss"
    faiss.write_index(index, str(path))
    before = sha256(path)
    validate_index(index, metadata)
    exact = build_exact_index(index)
    np.testing.assert_array_equal(exact.reconstruct_n(0, len(vectors)), vectors)
    exact_scores, exact_ids = exact.search(vectors[:50], 10)
    scores, ids = index.search(vectors[:50], 10)
    assert ids[:, 0].tolist() == list(range(50))
    assert np.all(per_query_recall(ids, exact_ids, 10) > 0.9)
    assert score_admissibility(scores, ids, exact_scores, 10) > 0.99
    assert sha256(path) == before
    assert index.hnsw.efSearch == 64


def test_id_recall_and_equal_score_boundary_are_distinct() -> None:
    found = np.array([[2, 4], [5, -1]])
    exact = np.array([[2, 3], [5, 6]])
    scores = np.array([[1.0, 0.7], [1.0, -np.inf]])
    exact_scores = np.array([[1.0, 0.7], [1.0, 0.8]])
    np.testing.assert_array_equal(per_query_recall(found, exact, 2), [0.5, 0.5])
    assert score_admissibility(scores, found, exact_scores, 2) == 0.75


@pytest.mark.parametrize("mutation", ["missing_id", "extra_record", "unnormalized"])
def test_invalid_index_metadata_cannot_be_benchmarked(small_index, mutation) -> None:
    index, _, metadata = small_index
    if mutation == "missing_id":
        metadata["unmapped"] = metadata.pop("0")
    elif mutation == "extra_record":
        metadata["128"] = {"doc_id": 128}
    else:
        index.reset()
        index.add(np.ones((128, 16), dtype=np.float32))
    with pytest.raises(ValueError):
        validate_index(index, metadata)


def test_latency_uses_all_queries_each_repeat_and_does_not_change_index(small_index) -> None:
    index, vectors, _ = small_index
    stats, samples = latency_benchmark(index, vectors[:5], repeats=2, seed=42)
    assert stats["samples"] == len(samples) == 10
    for repeat in range(2):
        assert sorted(sample["query_number"] for sample in samples if sample["repeat"] == repeat) == list(range(5))
    assert 0 <= stats["p50_ms"] <= stats["p95_ms"] <= stats["p99_ms"]
    assert stats["serial_qps_from_timed_calls"] > 0
    assert stats["batch"]["batch_size"] == 5
    assert index.ntotal == 128 and index.hnsw.efSearch == 64


def test_memory_phases_include_native_process_rss() -> None:
    with MemoryMonitor() as monitor:
        with monitor.phase("allocation"):
            data = np.ones((512, 512), dtype=np.float32)
        result = monitor.result()
        assert data.nbytes > 0
    assert not monitor.thread.is_alive()
    assert result["rss_bytes"] > 0 and result["peak_rss_bytes"] > 0
    assert [event["stage"] for event in result["events"]] == [
        "baseline", "allocation_before", "allocation_after",
    ]
    assert result["events"][-1]["seconds"] >= 0


def test_reports_do_not_overwrite_existing_files(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_json(path, {"existing": True})
    with pytest.raises(FileExistsError):
        write_json(path, {"replacement": True})
    assert path.read_text().find('"existing": true') != -1
