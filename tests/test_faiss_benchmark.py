"""Focused numerical checks for the random-query accuracy benchmark."""
from pathlib import Path

import faiss
import numpy as np
import pytest

from BackEnd.tests.benchmark_faiss import benchmark, read_records, recall_at_k, remove_sources, sha256


def test_recall_ignores_duplicate_and_missing_ids() -> None:
    found = np.array([[1, 1, -1], [3, 2, 1]])
    exact = np.array([[1, 2, 3], [1, 2, 3]])
    assert recall_at_k(found, exact, 3) == pytest.approx(2 / 3)


def test_source_removal_preserves_rank_and_padding() -> None:
    found = np.array([[1, 2, 3], [7, -1, -1]])
    assert remove_sources(found, np.array([1, 7]), 2).tolist() == [[2, 3], [-1, -1]]


def test_notebook_reader_does_not_execute_model_cells(tmp_path: Path) -> None:
    path = tmp_path / 'empty.json'
    path.write_text('[]')
    assert read_records(path) == []


def test_benchmark_is_reproducible_and_preserves_index(tmp_path: Path) -> None:
    faiss.omp_set_num_threads(1)
    vectors = np.random.default_rng(7).standard_normal((256, 16)).astype(np.float32)
    faiss.normalize_L2(vectors)
    index = faiss.IndexIVFPQ(faiss.IndexFlatIP(16), 16, 4, 4, 2, faiss.METRIC_INNER_PRODUCT)
    index.train(vectors)
    index.add_with_ids(vectors, np.arange(len(vectors), dtype=np.int64))
    index.nprobe = 2
    path = tmp_path / 'index.faiss'
    faiss.write_index(index, str(path))
    before = sha256(path)
    rows, sources = benchmark(index, vectors, 50, 42, [1, 4])
    repeated, repeated_sources = benchmark(index, vectors, 50, 42, [1, 4])
    assert rows == repeated
    assert np.array_equal(sources, repeated_sources)
    assert len(sources) == len(set(sources)) == 50
    assert [row['nprobe'] for row in rows] == [1, 2, 4]
    assert index.nprobe == 2
    assert sha256(path) == before


def test_benchmark_rejects_wrong_vector_shape() -> None:
    index = faiss.IndexIVFPQ(faiss.IndexFlatIP(16), 16, 4, 4, 2, faiss.METRIC_INNER_PRODUCT)
    with pytest.raises(ValueError, match='shape'):
        benchmark(index, np.zeros((256, 8), dtype=np.float32), 50, 42, [1])
