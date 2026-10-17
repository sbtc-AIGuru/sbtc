"""Verify complete IVF ID mapping before measuring downloaded indexes."""
import faiss
import numpy as np
import pytest

from BackEnd.tests.benchmark_ivfpq import (
    audit_search_work, set_ivf_nprobe, source_retrieval_metrics, validate_ivfpq,
)


@pytest.fixture
def ivfpq():
    threads = faiss.omp_get_max_threads()
    faiss.omp_set_num_threads(1)
    vectors = np.random.default_rng(42).normal(size=(512, 16)).astype(np.float32)
    faiss.normalize_L2(vectors)
    index = faiss.IndexIVFPQ(faiss.IndexFlatIP(16), 16, 4, 4, 4, faiss.METRIC_INNER_PRODUCT)
    index.train(vectors)
    index.add(vectors)
    metadata = {str(i): {'doc_id': i} for i in range(len(vectors))}
    try:
        yield index, metadata
    finally:
        faiss.omp_set_num_threads(threads)


def test_accepts_unique_sequential_ids_without_direct_map(ivfpq):
    index, metadata = ivfpq
    validate_ivfpq(index, metadata)
    assert index.direct_map.type == faiss.DirectMap.NoMap
    assert index.ntotal == 512


def test_rejects_duplicate_ids_even_with_correct_count(ivfpq):
    index, metadata = ivfpq
    vectors = np.ones((512, 16), dtype=np.float32)
    index.reset()
    index.add_with_ids(vectors, np.zeros(512, dtype=np.int64))
    with pytest.raises(ValueError, match='unique'):
        validate_ivfpq(index, metadata)


def test_rejects_mismatched_metadata(ivfpq):
    index, metadata = ivfpq
    metadata['512'] = metadata.pop('0')
    with pytest.raises(ValueError, match='sequential'):
        validate_ivfpq(index, metadata)


@pytest.mark.parametrize('wrapper', ['direct', 'pretransform', 'idmap2'])
def test_parameter_space_changes_inner_ivf_nprobe(ivfpq, wrapper):
    index, _ = ivfpq
    if wrapper == 'pretransform':
        wrapped = faiss.IndexPreTransform(index)
    elif wrapper == 'idmap2':
        index.reset()
        wrapped = faiss.IndexIDMap2(index)
    else:
        wrapped = index
    set_ivf_nprobe(wrapped, 4)
    assert index.nprobe == 4
    assert faiss.extract_index_ivf(wrapped).nprobe == 4


def test_full_nprobe_really_scans_all_vectors(ivfpq):
    index, _ = ivfpq
    queries = np.ones((3, 16), dtype=np.float32)
    faiss.normalize_L2(queries)
    set_ivf_nprobe(index, 1)
    partial = audit_search_work(index, queries)
    set_ivf_nprobe(index, index.nlist)
    full = audit_search_work(index, queries)
    assert full['effective_nprobe'] == index.nlist
    assert full['distances_computed'] == 3 * index.ntotal
    assert partial['distances_computed'] < full['distances_computed']


def test_source_document_metrics_accept_other_chunks_and_ignore_missing_ids():
    metadata = {'0': {'doc_id': 10}, '1': {'doc_id': 20}, '2': {'doc_id': 10}}
    records = [{'source_doc_id': 10, 'source_vector_id': 0},
               {'source_doc_id': 20, 'source_vector_id': 1}]
    result = source_retrieval_metrics(np.array([[1, 2, 0], [0, -1, 2]]), records, metadata)
    assert result['source_doc_ranks'] == [2, None]
    assert result['source_doc_hit'] == 0.5
    assert result['source_chunk_hit'] == 0.5
    assert result['source_doc_mrr'] == 0.25
