"""Benchmark downloaded IVF-PQ files with authored queries, high nprobe and RAM."""
from __future__ import annotations

import argparse
import gc
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from BackEnd.tests.benchmark_faiss import recall_at_k, sha256
from BackEnd.tests.benchmark_hnsw import (
    KS, MODEL_CACHE, MODEL_SNAPSHOT, NOTEBOOK, MemoryMonitor,
    bootstrap_interval, latency_benchmark, load_gpu_encoder, per_query_recall,
    reference_scores, statistics, validate_reference, write_csv, write_json,
)


def validate_ivfpq(index: faiss.Index, metadata: dict) -> None:
    """Check every stored ID against metadata without creating a direct map."""
    if (not isinstance(index, faiss.IndexIVFPQ) or not index.is_trained
            or index.metric_type != faiss.METRIC_INNER_PRODUCT):
        raise ValueError('Expected a trained inner-product IndexIVFPQ')
    if index.ntotal <= max(KS) or len(metadata) != index.ntotal:
        raise ValueError('Metadata count differs from index or corpus is too small')
    if set(metadata) != {str(i) for i in range(index.ntotal)}:
        raise ValueError('Metadata must cover all sequential vector IDs')
    ids = []
    for list_id in range(index.nlist):
        size = index.invlists.list_size(list_id)
        pointer = index.invlists.get_ids(list_id)
        try:
            ids.append(faiss.rev_swig_ptr(pointer, size).copy())
        finally:
            index.invlists.release_ids(list_id, pointer)
    if not np.array_equal(np.sort(np.concatenate(ids)), np.arange(index.ntotal)):
        raise ValueError('FAISS IDs must be unique and match every metadata ID')


def load_inputs(args: argparse.Namespace, monitor: MemoryMonitor) -> tuple:
    with monitor.phase('load_index'):
        index = faiss.read_index(str(args.index))
    with monitor.phase('load_metadata'):
        with args.metadata.open(encoding='utf-8') as handle:
            metadata = json.load(handle)
    with monitor.phase('validate_inputs'):
        validate_ivfpq(index, metadata)
    return index, metadata


def set_ivf_nprobe(index: faiss.Index, nprobe: int) -> None:
    """Set the C++ IVF parameter and verify it through the extracted IVF index."""
    faiss.ParameterSpace().set_index_parameter(index, 'nprobe', nprobe)
    actual = int(faiss.extract_index_ivf(index).nprobe)
    if actual != nprobe:
        raise ValueError(f'nprobe was not applied: requested={nprobe}, actual={actual}')


def audit_search_work(index: faiss.Index, queries: np.ndarray) -> dict:
    """Count actual IVF scans separately from the timed search calls."""
    faiss.cvar.indexIVF_stats.reset()
    index.search(queries, 10)
    stats = faiss.cvar.indexIVF_stats
    ivf = faiss.extract_index_ivf(index)
    result = {'effective_nprobe': int(ivf.nprobe), 'query_count': int(stats.nq),
              'nonempty_lists_visited': int(stats.nlist), 'distances_computed': int(stats.ndis),
              'vectors_scanned_per_query': float(stats.ndis) / len(queries)}
    if result['query_count'] != len(queries):
        raise ValueError('Unexpected query count in IVF search statistics')
    if ivf.nprobe == ivf.nlist and result['distances_computed'] != len(queries) * index.ntotal:
        raise ValueError('Full nprobe did not scan every vector')
    return result


def source_retrieval_metrics(ids: np.ndarray, records: list[dict], metadata: dict) -> dict:
    """Measure retrieval of question source documents, allowing multiple chunks per doc."""
    doc_ranks = []
    chunk_hits = []
    for found, record in zip(ids, records):
        matches = [rank + 1 for rank, vector_id in enumerate(found)
                   if vector_id >= 0 and metadata[str(int(vector_id))]['doc_id'] == record['source_doc_id']]
        doc_ranks.append(matches[0] if matches else None)
        chunk_hits.append(record['source_vector_id'] in found)
    return {'source_chunk_hit': float(np.mean(chunk_hits)),
            'source_doc_hit': float(np.mean([rank is not None for rank in doc_ranks])),
            'source_doc_mrr': float(np.mean([1 / rank if rank else 0 for rank in doc_ranks])),
            'source_doc_ranks': doc_ranks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--queries', type=Path, default=ROOT / 'BackEnd/tests/hnsw_queries_50.json')
    parser.add_argument('--reference-index', type=Path, default=ROOT / 'BackEnd/tests/index_hnsw.faiss')
    parser.add_argument('--reference-metadata', type=Path, default=ROOT / 'BackEnd/tests/metadata.json')
    parser.add_argument('--model', type=Path, default=MODEL_SNAPSHOT)
    parser.add_argument('--hf-cache', type=Path, default=MODEL_CACHE)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--repeats', type=int, default=20)
    parser.add_argument('--embedding-batch-size', type=int, default=16)
    parser.add_argument('--nprobes', type=int, nargs='+', default=[16, 64, 128, 256, 512, 1024, 2048, 4096])
    parser.add_argument('--end-to-end-nprobe', type=int, default=512)
    parser.add_argument('--memory-only', action='store_true')
    parser.add_argument('--questions-only', action='store_true',
                        help='Measure question retrieval, latency and RAM without a raw-vector reference')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('--output must be a new directory')
    if min(args.nprobes + [args.threads, args.repeats, args.embedding_batch_size,
                          args.end_to_end_nprobe]) < 1:
        parser.error('Thread, repeat, batch and nprobe values must be positive')
    args.output.mkdir(parents=True)
    faiss.omp_set_num_threads(args.threads)
    if args.memory_only:
        with MemoryMonitor() as monitor:
            index, metadata = load_inputs(args, monitor)
            monitor.mark('index_and_metadata_ready')
            write_json(args.output / 'memory.json', monitor.result())
        return

    started = perf_counter()
    paths = {'index': args.index, 'metadata': args.metadata, 'queries': args.queries,
             'encoder_notebook': NOTEBOOK, 'benchmark_script': Path(__file__).resolve()}
    if not args.questions_only:
        paths.update(reference_index=args.reference_index, reference_metadata=args.reference_metadata)
    before_hashes = {name: sha256(path) for name, path in paths.items()}
    if not args.questions_only and before_hashes['metadata'] != before_hashes['reference_metadata']:
        raise ValueError('Reference metadata must match byte-for-byte for exact ID alignment')
    subprocess.run([
        sys.executable, str(Path(__file__).resolve()), '--memory-only', '--index', str(args.index),
        '--metadata', str(args.metadata), '--threads', str(args.threads),
        '--output', str(args.output / 'memory_only'),
    ], check=True)
    isolated_ram = json.loads((args.output / 'memory_only/memory.json').read_text())
    query_records = json.loads(args.queries.read_text())
    texts = [r['text'] for r in query_records]
    if len(texts) != 50 or len(set(texts)) != 50:
        raise ValueError('Expected exactly 50 unique authored queries')
    write_json(args.output / 'queries.json', query_records)
    latency_samples, per_query, rows = [], [], []
    with MemoryMonitor() as monitor:
        index, metadata = load_inputs(args, monitor)
        original_nprobe = index.nprobe
        original_max_codes = index.max_codes
        if original_max_codes != 0:
            raise ValueError('max_codes must be zero so high-nprobe searches are not capped')
        for r in query_records:
            if metadata[str(r['source_vector_id'])]['doc_id'] != r['source_doc_id']:
                raise ValueError('Query annotation differs from downloaded metadata')
        with monitor.phase('load_model_and_embed_queries'):
            encoder, model_info = load_gpu_encoder(args, index)
            query_vectors = encoder['encode_texts'](texts)
        np.save(args.output / 'query_vectors.npy', query_vectors)
        if not args.questions_only:
            with monitor.phase('load_exact_reference'):
                reference = faiss.read_index(str(args.reference_index))
                validate_reference(reference, index, metadata)
                exact = faiss.downcast_index(reference.storage)
                source_vectors = encoder['encode_texts']([
                    metadata[str(r['source_vector_id'])]['chunk_text'] for r in query_records
                ])
                stored_vectors = np.stack([reference.reconstruct(r['source_vector_id']) for r in query_records])
                agreement = np.sum(source_vectors * stored_vectors, axis=1)
                if np.min(agreement) < 0.99:
                    raise ValueError('GPU encoder differs from uncompressed reference embeddings')
                exact_scores, exact_ids = exact.search(query_vectors, max(KS))
                exact_latency, exact_samples = latency_benchmark(exact, query_vectors, 5, 42)
                latency_samples.extend({'engine': 'exact', 'nprobe': 0, **r} for r in exact_samples)
        nprobes = sorted({min(v, index.nlist) for v in args.nprobes}
                        | {original_nprobe, index.nlist, min(args.end_to_end_nprobe, index.nlist)})
        print(f'GPU embeddings ready; testing nprobe={nprobes}', flush=True)
        try:
            for nprobe in nprobes:
                set_ivf_nprobe(index, nprobe)
                with monitor.phase(f'search_nprobe_{nprobe}'):
                    row = {'nprobe': nprobe, 'search_work': audit_search_work(index, query_vectors)}
                    found = {}
                    for k in KS:
                        scores, ids = index.search(query_vectors, k)
                        found[k] = (scores, ids)
                        metrics = source_retrieval_metrics(ids, query_records, metadata)
                        for name in ('source_chunk_hit', 'source_doc_hit', 'source_doc_mrr'):
                            row[f'{name}@{k}'] = metrics[name]
                        if not args.questions_only:
                            row[f'recall@{k}'] = recall_at_k(ids, exact_ids, k)
                    scores10, ids10 = found[10]
                    source_ranks = source_retrieval_metrics(ids10, query_records, metadata)['source_doc_ranks']
                    if not args.questions_only:
                        qrecall = per_query_recall(ids10, exact_ids, 10)
                        row['recall@10_bootstrap_95_ci'] = bootstrap_interval(qrecall)
                        row['queries_full_exact_top10'] = int(np.count_nonzero(qrecall == 1))
                        raw_top1 = reference_scores(reference, query_vectors, found[1][1])
                        row['mean_top1_score_regret'] = float(np.maximum(exact_scores[:, 0] - raw_top1[:, 0], 0).mean())
                    latency, samples = latency_benchmark(index, query_vectors, args.repeats, 42)
                    row['search_top10_latency'] = latency
                    latency_samples.extend({'engine': 'ivfpq', 'nprobe': nprobe, **r} for r in samples)
                    rows.append(row)
                    for position, r in enumerate(query_records):
                        result = {
                            'query_id': r['query_id'], 'nprobe': nprobe,
                            'found_ids': ids10[position].tolist(), 'found_scores': scores10[position].tolist(),
                            'source_doc_rank@10': source_ranks[position],
                            'source_chunk_hit@10': bool(r['source_vector_id'] in ids10[position]),
                        }
                        if not args.questions_only:
                            result.update({'recall@10': float(qrecall[position]),
                                           'exact_ids': exact_ids[position, :10].tolist(),
                                           'exact_scores': exact_scores[position, :10].tolist()})
                        per_query.append(result)
                quality = (f'Source doc Hit@10={row["source_doc_hit@10"]:.2%}' if args.questions_only
                           else f'Recall@10={row["recall@10"]:.2%}')
                print(f'nprobe={nprobe}: {quality}, mean={latency["mean_ms"]:.3f}ms, p95={latency["p95_ms"]:.3f}ms', flush=True)
        finally:
            set_ivf_nprobe(index, original_nprobe)
        if not args.questions_only:
            del exact, reference, source_vectors, stored_vectors
        gc.collect()
        monitor.mark('serving_ready_without_reference')
        e2e_rows = []
        try:
            for nprobe in sorted({original_nprobe, min(args.end_to_end_nprobe, index.nlist)}):
                set_ivf_nprobe(index, nprobe)
                with monitor.phase(f'end_to_end_nprobe_{nprobe}'):
                    samples = []
                    for repeat in range(3):
                        for position in np.random.default_rng(42 + repeat).permutation(50):
                            t = perf_counter()
                            vector = encoder['encode_texts']([texts[position]])
                            _, ids = index.search(vector, 10)
                            matched = [metadata[str(int(v))] for v in ids[0] if v >= 0]
                            if len(matched) != 10:
                                raise ValueError('Search returned fewer than ten mapped results')
                            samples.append({'repeat': repeat, 'query_number': int(position),
                                            'latency_ms': (perf_counter() - t) * 1000})
                    e2e_rows.append({'nprobe': nprobe, **statistics([s['latency_ms'] for s in samples])})
                    latency_samples.extend({'engine': 'embedding_search_metadata', 'nprobe': nprobe, **s} for s in samples)
        finally:
            set_ivf_nprobe(index, original_nprobe)
        ram = monitor.result()
        torch = encoder['torch']
        report = {
            'created_at': datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).isoformat(),
            'index': {'path': str(args.index), 'type': type(index).__name__, 'vectors': index.ntotal,
                      'dimension': index.d, 'nlist': index.nlist, 'stored_nprobe': original_nprobe,
                      'max_codes': original_max_codes, 'pq_m': index.pq.M, 'pq_nbits': index.pq.nbits,
                      'code_size': index.code_size, 'by_residual': bool(index.by_residual),
                      'disk_bytes': args.index.stat().st_size, 'metric': 'inner product'},
            'metadata': {'path': str(args.metadata), 'records': len(metadata), 'disk_bytes': args.metadata.stat().st_size},
            'query_count': 50, 'query_kind': 'corpus-informed authored Vietnamese questions',
            'evaluation_mode': 'questions_only' if args.questions_only else 'raw_vector_reference',
            'nprobe_setter': 'ParameterSpace.set_index_parameter + extract_index_ivf verification',
            'environment': {'python': sys.version.split()[0], 'platform': platform.platform(),
                            'faiss': faiss.__version__, 'faiss_threads': args.threads},
            'model': model_info, 'rows': rows, 'end_to_end': e2e_rows,
            'model_reference_cosine': ({'min': float(agreement.min()), 'mean': float(agreement.mean())}
                                       if not args.questions_only else None),
            'reference': {'path': str(args.reference_index), 'metadata_byte_identical': True,
                          'method': 'Exact FlatIP search of original uncompressed HNSWFlat storage'} if not args.questions_only else None,
            'exact_top10_latency': exact_latency if not args.questions_only else None,
            'isolated_index_metadata_ram': isolated_ram, 'full_benchmark_ram': ram,
            'gpu_vram': {'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
                         'peak_reserved_bytes': torch.cuda.max_memory_reserved()},
            'elapsed_seconds': perf_counter() - started,
            'limitations': [
                '50 corpus-informed questions, no independent human relevance labels; recall measures exact top-k ID overlap.',
                'Ground truth is a separately built uncompressed index with identical ordered metadata; original IVF insertion vectors/build environment are unavailable.',
                'nprobe=nlist scans all IVF lists but still ranks compressed PQ vectors, so it is not exact raw-vector search.',
                'Warm in-process latency excludes HTTP, concurrency, reranking and generation; 20 shuffled repeats per question.',
                'RAM is process RSS/PSS; full benchmark temporarily includes model and exact reference, isolated probe includes only index and metadata.',
                'Load times are page-cache warm; RSS sampling at 20ms can miss short spikes, OS peak RSS remains recorded.',
            ],
        }
        if args.questions_only:
            report['limitations'] = [
                '50 corpus-informed questions from known source documents, not independent traffic or exhaustive human relevance labels.',
                'Source-document Hit@k and MRR@k evaluate finding the document used to author a question; other documents may also contain valid answers.',
                'No reference index is read and no raw-vector recall is computed; model identity depends on the configured GTE encoder.',
                'Warm local in-process latency excludes HTTP, concurrency, reranking and generation; 20 shuffled repeats per question.',
                'RAM includes process libraries and allocators; isolated probe loads only index and metadata, full benchmark also loads GTE.',
                'Load times are page-cache warm; 20ms RSS sampling can miss short spikes, OS peak RSS remains recorded.',
            ]
    after_hashes = {name: sha256(path) for name, path in paths.items()}
    if before_hashes != after_hashes:
        raise RuntimeError('Benchmark input changed during execution')
    report.update(input_sha256_before=before_hashes, input_sha256_after=after_hashes)
    write_json(args.output / 'report.json', report)
    write_json(args.output / 'per_query_sweep.json', per_query)
    write_csv(args.output / 'latency_samples.csv', latency_samples)
    write_csv(args.output / 'results.csv', [
        {'nprobe': r['nprobe'], **r['search_work'],
         **{name: value for name, value in r.items() if name.startswith(('recall@', 'source_'))
            and 'bootstrap' not in name},
         **{name: r['search_top10_latency'][name] for name in ('mean_ms', 'p50_ms', 'p95_ms', 'p99_ms')},
         'serial_qps': r['search_top10_latency']['serial_qps_from_timed_calls'],
         'batch_qps': r['search_top10_latency']['batch']['qps'],
         'source_chunk_hit@10': r['source_chunk_hit@10'], 'source_doc_hit@10': r['source_doc_hit@10']}
        for r in rows
    ])
    print(f'Completed in {report["elapsed_seconds"]:.2f}s: {args.output}', flush=True)


if __name__ == '__main__':
    main()
