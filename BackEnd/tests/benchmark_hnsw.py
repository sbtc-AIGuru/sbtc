"""Benchmark immutable HNSW inputs with real queries, exact search and process RAM."""
from __future__ import annotations

import argparse
import ast
import csv
import gc
import json
import os
import platform
import resource
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter
from types import MethodType
from typing import Iterator, TextIO
from zoneinfo import ZoneInfo

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from BackEnd.tests.benchmark_faiss import recall_at_k, sha256

KS = (1, 5, 10, 20, 50)
MIB = 1024**2
MODEL_CACHE = ROOT / 'BackEnd/tests/benchmark_cache/gte/models'
MODEL_SNAPSHOT = MODEL_CACHE / 'models--Alibaba-NLP--gte-multilingual-base/snapshots/9bbca17d9273fd0d03d5725c7a4b0f6b45142062'
NOTEBOOK = ROOT / 'BackEnd/app/Database/FAISS_HSNW_index.ipynb'


def memory_snapshot() -> dict:
    """Read Linux resident RAM, proportional RAM and OS high-water RSS in bytes."""
    fields = {}
    for line in Path('/proc/self/status').read_text().splitlines():
        name, _, value = line.partition(':')
        if name in {'VmRSS', 'VmHWM'}:
            fields[name] = int(value.split()[0]) * 1024
    pss = None
    try:
        for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
            if line.startswith('Pss:'):
                pss = int(line.split()[1]) * 1024
                break
    except (OSError, PermissionError):
        pass
    return {'rss_bytes': fields['VmRSS'], 'pss_bytes': pss,
            'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}


class MemoryMonitor:
    """Sample only this process's RSS every 20 ms, without summing GPU VRAM."""
    def __init__(self) -> None:
        self.stage = 'baseline'
        self.peaks: dict[str, int] = {}
        self.events: list[dict] = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self.stop_event.is_set():
            for line in Path('/proc/self/status').read_text().splitlines():
                if line.startswith('VmRSS:'):
                    rss = int(line.split()[1]) * 1024
                    stage = self.stage
                    self.peaks[stage] = max(self.peaks.get(stage, 0), rss)
                    break
            self.stop_event.wait(0.02)

    def __enter__(self):
        self.thread.start()
        self.mark('baseline')
        return self

    def __exit__(self, *args):
        self.stop_event.set()
        self.thread.join()

    def mark(self, label: str) -> dict:
        snapshot = {'stage': label, **memory_snapshot()}
        self.events.append(snapshot)
        return snapshot

    @contextmanager
    def phase(self, label: str) -> Iterator[None]:
        self.stage = label
        before = self.mark(label + '_before')
        started = perf_counter()
        try:
            yield
        finally:
            after = self.mark(label + '_after')
            after['seconds'] = perf_counter() - started
            after['rss_delta_bytes'] = after['rss_bytes'] - before['rss_bytes']
            after['sampled_stage_peak_rss_bytes'] = self.peaks.get(label, after['rss_bytes'])

    def result(self) -> dict:
        return {'sampling_interval_ms': 20, 'events': self.events,
                'sampled_stage_peak_rss_bytes': self.peaks, **memory_snapshot()}


def validate_index(index: faiss.Index, metadata: dict) -> None:
    """Check full ID coverage and cosine prerequisites before any benchmark."""
    if (not isinstance(index, (faiss.IndexHNSWFlat, faiss.IndexHNSWPQ))
            or not index.is_trained or index.metric_type != faiss.METRIC_INNER_PRODUCT):
        raise ValueError('Expected a trained inner-product HNSWFlat or HNSWPQ index')
    compressed = isinstance(index, faiss.IndexHNSWPQ)
    if compressed:
        storage = faiss.downcast_index(index.storage)
        if (storage.pq.M != 64 or storage.pq.nbits != 8 or storage.code_size != 64
                or storage.metric_type != faiss.METRIC_INNER_PRODUCT):
            raise ValueError('Expected PQ64 with 8-bit codes and inner-product storage')
    if index.ntotal <= max(KS) or len(metadata) != index.ntotal:
        raise ValueError('Metadata count differs from index or corpus is too small')
    if any(str(vector_id) not in metadata for vector_id in range(index.ntotal)):
        raise ValueError('Metadata must cover every sequential HNSW vector ID')
    for vector_id in np.linspace(0, index.ntotal - 1, min(1_000, index.ntotal), dtype=int):
        vector = index.reconstruct(int(vector_id))
        if (not np.isfinite(vector).all() or np.linalg.norm(vector) <= 1e-12
                or (not compressed and not np.isclose(np.linalg.norm(vector), 1, atol=1e-3))):
            raise ValueError(f'Stored vector is not finite and L2 normalized: {vector_id}')


def statistics(values: list[float] | np.ndarray) -> dict:
    """Summarize measured milliseconds without assuming a normal distribution."""
    samples = np.asarray(values, dtype=np.float64)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ValueError('Expected nonempty finite latency samples')
    return {'samples': len(samples), 'mean_ms': float(samples.mean()),
            'p50_ms': float(np.percentile(samples, 50)), 'p95_ms': float(np.percentile(samples, 95)),
            'p99_ms': float(np.percentile(samples, 99)), 'min_ms': float(samples.min()),
            'max_ms': float(samples.max()), 'std_ms': float(samples.std())}


def latency_benchmark(index: faiss.Index, queries: np.ndarray, repeats: int, seed: int) -> tuple[dict, list[dict]]:
    """Warm the index, then time independent top-10 calls in shuffled query order."""
    for query in queries:
        index.search(query[None, :], 10)
    rng = np.random.default_rng(seed)
    samples = []
    for repeat in range(repeats):
        for position in rng.permutation(len(queries)):
            query = queries[position:position + 1]
            started = perf_counter()
            index.search(query, 10)
            samples.append({'repeat': repeat, 'query_number': int(position),
                            'latency_ms': (perf_counter() - started) * 1_000})
    metrics = statistics([sample['latency_ms'] for sample in samples])
    metrics['serial_qps_from_timed_calls'] = 1_000 / metrics['mean_ms']
    batch_times = []
    index.search(queries, 10)
    for _ in range(repeats):
        started = perf_counter()
        index.search(queries, 10)
        batch_times.append((perf_counter() - started) * 1_000)
    metrics['batch'] = {**statistics(batch_times), 'batch_size': len(queries),
                        'qps': len(queries) * 1_000 / float(np.mean(batch_times))}
    return metrics, samples


def per_query_recall(found: np.ndarray, exact: np.ndarray, k: int) -> np.ndarray:
    return np.array([recall_at_k(a[None, :], b[None, :], k) for a, b in zip(found, exact)])


def score_admissibility(scores: np.ndarray, ids: np.ndarray, exact_scores: np.ndarray, k: int) -> float:
    """Fraction within the exact top-k score boundary, accepting ties at 1e-5."""
    valid = (ids[:, :k] >= 0) & (scores[:, :k] >= exact_scores[:, k - 1:k] - 1e-5)
    return float(valid.mean())


def bootstrap_interval(values: np.ndarray, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    means = values[rng.integers(len(values), size=(2_000, len(values)))].mean(axis=1)
    return [float(value) for value in np.percentile(means, [2.5, 97.5])]


def build_exact_index(index: faiss.IndexHNSWFlat) -> faiss.IndexFlatIP:
    """Copy original uncompressed stored vectors in bounded reconstruction blocks."""
    if not isinstance(index, faiss.IndexHNSWFlat):
        raise ValueError('Exact ground truth must use uncompressed vectors, not PQ reconstructions')
    exact = faiss.IndexFlatIP(index.d)
    for start in range(0, index.ntotal, 8_192):
        vectors = index.reconstruct_n(start, min(8_192, index.ntotal - start))
        exact.add(vectors)
    return exact


def validate_reference(reference: faiss.Index, index: faiss.Index, metadata: dict) -> None:
    """Require an uncompressed, normalized reference with the same ordered vector IDs."""
    if not isinstance(reference, faiss.IndexHNSWFlat):
        raise ValueError('The reference must be an uncompressed HNSWFlat index')
    if reference.ntotal != index.ntotal or reference.d != index.d:
        raise ValueError('Reference and tested index counts/dimensions differ')
    validate_index(reference, metadata)


def reference_scores(reference: faiss.IndexHNSWFlat, queries: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """Rescore returned IDs using original vectors, never compare PQ scores to raw scores."""
    storage = faiss.downcast_index(reference.storage)
    vectors = faiss.rev_swig_ptr(storage.get_xb(), storage.ntotal * storage.d).reshape(-1, storage.d)
    valid = (ids >= 0) & (ids < reference.ntotal)
    selected = vectors[np.where(valid, ids, 0)]
    scores = np.einsum('qd,qkd->qk', queries, selected)
    return np.where(valid, scores, -np.inf)


def load_gpu_encoder(args: argparse.Namespace, index: faiss.IndexHNSWFlat) -> tuple[dict, dict]:
    """Reuse the notebook's GTE repairs, pooling, CUDA checks and adaptive encoder."""
    os.environ['HF_HOME'] = str(args.output / 'hf_runtime')
    os.environ['HF_HUB_CACHE'] = str(args.hf_cache)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '120'
    import torch
    from sentence_transformers import SentenceTransformer
    from importlib.metadata import version

    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable; run outside the sandbox in DL_Env. No CPU fallback.')
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    torch.set_num_threads(args.threads)
    namespace = {'gc': gc, 'json': json, 'np': np, 'faiss': faiss, 'torch': torch,
                 'MethodType': MethodType, 'Iterator': Iterator, 'TextIO': TextIO,
                 'perf_counter': perf_counter, 'index': index, 'use_fp16': True,
                 'effective_batch_size': args.embedding_batch_size, 'device': torch.device('cpu')}
    notebook = json.loads(NOTEBOOK.read_text())
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            nodes = [node for node in ast.parse(''.join(cell['source'])).body
                     if isinstance(node, ast.FunctionDef)]
            exec(compile(ast.Module(body=nodes, type_ignores=[]), str(NOTEBOOK), 'exec'), namespace)
    model = SentenceTransformer(
        str(args.model), device='cpu', trust_remote_code=True,
        model_kwargs={'code_revision': '40ced75c3017eb27626c9d4ea981bde21a2662f4'},
        config_kwargs={'code_revision': '40ced75c3017eb27626c9d4ea981bde21a2662f4'},
    )
    model.float().eval()
    auto_model = model[0].auto_model
    namespace['prepare_gte_model'](auto_model)
    if model.get_sentence_embedding_dimension() != index.d:
        raise ValueError('GTE and index dimensions differ')
    if model.max_seq_length > auto_model.config.max_position_embeddings or getattr(model, 'default_prompt_name', None):
        raise ValueError('Unexpected tokenizer limit or default embedding prompt')
    namespace.update(model=model, auto_model=auto_model)
    smoke = ['Embedding smoke test.', 'Kiểm tra tìm kiếm tiếng Việt.']
    cpu_probe = namespace['encode_texts'](smoke)
    namespace['device'] = torch.device('cuda:0')
    model.to(namespace['device'])
    gpu_probe = namespace['encode_texts'](smoke)
    cosine = np.sum(cpu_probe * gpu_probe, axis=1)
    if np.min(cosine) < 0.99:
        raise ValueError('CPU/GPU embedding smoke probes disagree')
    info = {'name': 'Alibaba-NLP/gte-multilingual-base', 'local_snapshot': str(args.model),
            'code_revision': '40ced75c3017eb27626c9d4ea981bde21a2662f4',
            'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__,
            'cuda_runtime': torch.version.cuda, 'transformers': version('transformers'),
            'sentence_transformers': version('sentence-transformers'),
            'cpu_gpu_smoke_cosine': cosine.tolist(), 'max_seq_length': model.max_seq_length,
            'precision': 'FP32 weights with CUDA FP16 autocast; normalized float32 output'}
    return namespace, info


def write_json(path: Path, value: object) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def write_csv(path: Path, records: list[dict]) -> None:
    with path.open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def load_inputs(args, monitor):
    with monitor.phase('load_index'):
        index = faiss.read_index(str(args.index))
    with monitor.phase('load_metadata'):
        with args.metadata.open(encoding='utf-8') as handle:
            metadata = json.load(handle)
    with monitor.phase('validate_inputs'):
        validate_index(index, metadata)
    return index, metadata


def memory_only(args) -> None:
    with MemoryMonitor() as monitor:
        index, metadata = load_inputs(args, monitor)
        monitor.mark('index_and_metadata_ready')
        result = monitor.result()
        result.update(vectors=index.ntotal, metadata_records=len(metadata),
                      index_disk_bytes=args.index.stat().st_size,
                      metadata_disk_bytes=args.metadata.stat().st_size)
        write_json(args.output / 'memory.json', result)
    print('Isolated index/metadata RAM probe completed', flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=ROOT / 'BackEnd/tests/index_hnsw.faiss')
    parser.add_argument('--metadata', type=Path, default=ROOT / 'BackEnd/tests/metadata.json')
    parser.add_argument('--queries', type=Path, default=ROOT / 'BackEnd/tests/hnsw_queries_50.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', type=Path, default=MODEL_SNAPSHOT)
    parser.add_argument('--hf-cache', type=Path, default=MODEL_CACHE)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--repeats', type=int, default=20)
    parser.add_argument('--embedding-batch-size', type=int, default=16)
    parser.add_argument('--ef-search', type=int, nargs='+', default=[16, 32, 64, 128, 256, 512])
    parser.add_argument('--memory-only', action='store_true')
    parser.add_argument('--reference-index', type=Path, help='Original HNSWFlat corpus for PQ ground truth')
    parser.add_argument('--reference-metadata', type=Path, default=ROOT / 'BackEnd/tests/metadata.json')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be a new directory; existing files will not be overwritten')
    if min(args.threads, args.repeats, args.embedding_batch_size, *args.ef_search) < 1:
        parser.error('Thread, repeat, batch and efSearch values must be positive')
    args.output.mkdir(parents=True)
    faiss.omp_set_num_threads(args.threads)
    if args.memory_only:
        memory_only(args)
        return
    if not args.model.is_dir():
        raise FileNotFoundError(f'Cached GTE snapshot missing: {args.model}; no model was downloaded')
    started = perf_counter()
    input_hashes = {'index': sha256(args.index), 'metadata': sha256(args.metadata),
                    'queries': sha256(args.queries), 'notebook': sha256(NOTEBOOK)}
    if args.reference_index:
        input_hashes['reference_index'] = sha256(args.reference_index)
        input_hashes['reference_metadata'] = sha256(args.reference_metadata)
        if input_hashes['metadata'] != input_hashes['reference_metadata']:
            raise ValueError('Metadata must match the original reference byte-for-byte to align every ID')
    subprocess.run([
        sys.executable, str(Path(__file__).resolve()), '--memory-only',
        '--index', str(args.index), '--metadata', str(args.metadata),
        '--threads', str(args.threads), '--output', str(args.output / 'memory_only'),
    ], check=True)
    isolated_memory = json.loads((args.output / 'memory_only/memory.json').read_text())
    reference_memory = None
    if args.reference_index:
        subprocess.run([
            sys.executable, str(Path(__file__).resolve()), '--memory-only',
            '--index', str(args.reference_index), '--metadata', str(args.reference_metadata),
            '--threads', str(args.threads), '--output', str(args.output / 'reference_memory_only'),
        ], check=True)
        reference_memory = json.loads((args.output / 'reference_memory_only/memory.json').read_text())
    query_records = json.loads(args.queries.read_text())
    if len(query_records) != 50 or len({record['query_id'] for record in query_records}) != 50:
        raise ValueError('Expected exactly 50 unique authored queries')
    texts = [record['text'] for record in query_records]
    write_json(args.output / 'queries.json', query_records)
    latency_samples = []
    with MemoryMonitor() as monitor:
        index, metadata = load_inputs(args, monitor)
        compressed = isinstance(index, faiss.IndexHNSWPQ)
        if compressed and not args.reference_index:
            raise ValueError('PQ accuracy requires --reference-index; reconstructed PQ vectors are not ground truth')
        original_ef = index.hnsw.efSearch
        reference = None
        for record in query_records:
            source = metadata.get(str(record['source_vector_id']))
            if source is None or source['doc_id'] != record['source_doc_id']:
                raise ValueError('Query source annotation does not match downloaded metadata')
        with monitor.phase('model_load_and_smoke'):
            encoder, model_info = load_gpu_encoder(args, index)
        print('GTE loaded on GPU; embedding 50 questions', flush=True)
        with monitor.phase('embedding_batch'):
            batch_started = perf_counter()
            query_vectors = encoder['encode_texts'](texts)
            initial_embedding_seconds = perf_counter() - batch_started
            batch_embedding_times = []
            for _ in range(3):
                t = perf_counter()
                encoder['encode_texts'](texts)
                batch_embedding_times.append((perf_counter() - t) * 1_000)
            encoder['encode_texts']([texts[0]])
            singleton_embedding_times = []
            for text in texts:
                t = perf_counter()
                encoder['encode_texts']([text])
                singleton_embedding_times.append((perf_counter() - t) * 1_000)
        np.save(args.output / 'query_vectors.npy', query_vectors)
        with monitor.phase('build_exact_reference'):
            exact_started = perf_counter()
            if args.reference_index:
                reference = faiss.read_index(str(args.reference_index))
                validate_reference(reference, index, metadata)
                # Keep the owning HNSW reference alive while searching its raw FlatIP storage.
                exact = faiss.downcast_index(reference.storage)
            else:
                exact = build_exact_index(index)
            exact_build_seconds = perf_counter() - exact_started
        with monitor.phase('model_index_compatibility'):
            source_vectors = encoder['encode_texts']([
                metadata[str(record['source_vector_id'])]['chunk_text'] for record in query_records
            ])
            raw_index = reference if reference is not None else index
            stored_vectors = np.stack([raw_index.reconstruct(record['source_vector_id']) for record in query_records])
            agreement = np.sum(source_vectors * stored_vectors, axis=1)
            if np.min(agreement) < 0.99:
                raise ValueError(f'GTE/index embedding mismatch: minimum cosine {np.min(agreement)}')
        pq_agreement = None
        if compressed:
            reconstructed = np.stack([index.reconstruct(record['source_vector_id']) for record in query_records])
            cosine = np.sum(source_vectors * reconstructed, axis=1) / np.linalg.norm(reconstructed, axis=1)
            pq_agreement = {'min': float(cosine.min()), 'mean': float(cosine.mean()), 'max': float(cosine.max())}
            del reconstructed
        print('Exact reference ready; sweeping efSearch', flush=True)
        with monitor.phase('exact_search'):
            exact_scores, exact_ids = exact.search(query_vectors, max(KS))
            exact_latency, raw_exact = latency_benchmark(exact, query_vectors, min(5, args.repeats), 42)
            latency_samples.extend({'engine': 'exact', 'ef_search': 0, **record} for record in raw_exact)
        pq_exact_scores = pq_exact_ids = None
        pq_exhaustive = None
        if compressed:
            with monitor.phase('exhaustive_pq_search'):
                pq_exact_scores, pq_exact_ids = faiss.downcast_index(index.storage).search(query_vectors, max(KS))
                pq_exhaustive = {f'recall@{k}': recall_at_k(pq_exact_ids, exact_ids, k) for k in KS}
        source_ids = np.array([record['source_vector_id'] for record in query_records])
        source_docs = np.array([record['source_doc_id'] for record in query_records])
        rows = []
        reference_rows = []
        per_query_results = []
        ef_values = sorted(set(args.ef_search) | {original_ef})
        for ef in ef_values:
            with monitor.phase(f'hnsw_ef_{ef}'):
                index.hnsw.efSearch = ef
                found_by_k = {k: index.search(query_vectors, k) for k in KS}
                row = {'ef_search': ef}
                for k in KS:
                    scores, ids = found_by_k[k]
                    row[f'recall@{k}'] = recall_at_k(ids, exact_ids, k)
                    comparable_scores = reference_scores(reference, query_vectors, ids) if compressed else scores
                    row[f'score_admissibility@{k}'] = score_admissibility(comparable_scores, ids, exact_scores, k)
                    if compressed:
                        row[f'recall_vs_exhaustive_pq@{k}'] = recall_at_k(ids, pq_exact_ids, k)
                scores10, ids10 = found_by_k[10]
                qrecall = per_query_recall(ids10, exact_ids, 10)
                row['recall@10_bootstrap_95_ci'] = bootstrap_interval(qrecall)
                row['queries_full_exact_top10'] = int(np.count_nonzero(qrecall == 1))
                row['source_chunk_hit@10'] = float(np.any(ids10 == source_ids[:, None], axis=1).mean())
                row['source_doc_hit@10'] = float(np.mean([
                    any(metadata[str(int(v))]['doc_id'] == int(doc) for v in found if v >= 0)
                    for found, doc in zip(ids10, source_docs)
                ]))
                top1_scores = reference_scores(reference, query_vectors, found_by_k[1][1]) if compressed else found_by_k[1][0]
                row['mean_top1_score_regret'] = float(np.maximum(exact_scores[:, 0] - top1_scores[:, 0], 0).mean())
                latency, raw = latency_benchmark(index, query_vectors, args.repeats, 42)
                row['search_top10_latency'] = latency
                latency_samples.extend({'engine': 'hnsw', 'ef_search': ef, **record} for record in raw)
                rows.append(row)
                for position, record in enumerate(query_records):
                    per_query_results.append({
                        'query_id': record['query_id'], 'ef_search': ef,
                        'recall@10': float(qrecall[position]),
                        'found_ids': ids10[position].tolist(), 'found_scores': scores10[position].tolist(),
                        'exact_ids': exact_ids[position, :10].tolist(),
                        'exact_scores': exact_scores[position, :10].tolist(),
                    })
            print(f'efSearch={ef}: Recall@10={row["recall@10"]:.2%}; p95={latency["p95_ms"]:.3f}ms', flush=True)
            if reference is not None:
                with monitor.phase(f'reference_hnsw_ef_{ef}'):
                    previous_ef = reference.hnsw.efSearch
                    reference.hnsw.efSearch = ef
                    try:
                        reference_row = {'ef_search': ef}
                        for k in KS:
                            _, found = reference.search(query_vectors, k)
                            reference_row[f'recall@{k}'] = recall_at_k(found, exact_ids, k)
                        reference_latency, raw_reference = latency_benchmark(reference, query_vectors, args.repeats, 42)
                        reference_row['search_top10_latency'] = reference_latency
                        reference_rows.append(reference_row)
                        latency_samples.extend({'engine': 'hnsw_flat', 'ef_search': ef, **r} for r in raw_reference)
                    finally:
                        reference.hnsw.efSearch = previous_ef
        index.hnsw.efSearch = original_ef
        # The reference is an audit tool; remove it before measuring serving RAM/end-to-end latency.
        del exact, raw_index, source_vectors, stored_vectors
        if reference is not None:
            del reference
        gc.collect()
        monitor.mark('serving_ready_without_exact_reference')
        with monitor.phase('end_to_end'):
            encoder['encode_texts']([texts[0]])
            e2e_samples = []
            for repeat in range(3):
                for position in np.random.default_rng(42 + repeat).permutation(50):
                    t = perf_counter()
                    vector = encoder['encode_texts']([texts[position]])
                    _, found = index.search(vector, 10)
                    matched = [metadata[str(int(v))] for v in found[0] if v >= 0]
                    assert len(matched) == 10
                    e2e_samples.append({'repeat': repeat, 'query_number': int(position),
                                        'latency_ms': (perf_counter() - t) * 1_000})
        latency_samples.extend({'engine': 'embedding_search_metadata', 'ef_search': original_ef, **r} for r in e2e_samples)
        gpu_memory = {'allocated_bytes': encoder['torch'].cuda.memory_allocated(),
                      'reserved_bytes': encoder['torch'].cuda.memory_reserved(),
                      'peak_allocated_bytes': encoder['torch'].cuda.max_memory_allocated(),
                      'peak_reserved_bytes': encoder['torch'].cuda.max_memory_reserved()}
        ram = monitor.result()
        saved_results = next(row for row in rows if row['ef_search'] == original_ef)
        details = []
        for position, record in enumerate(query_records):
            search = next(r for r in per_query_results if r['query_id'] == record['query_id'] and r['ef_search'] == original_ef)
            details.append({**record, **search, 'top_results': [
                {'rank': rank + 1, 'vector_id': vector_id, 'score': search['found_scores'][rank],
                 'doc_id': metadata[str(vector_id)]['doc_id'], 'chunk_id': metadata[str(vector_id)]['chunk_id'],
                 'url': metadata[str(vector_id)]['url'], 'snippet': metadata[str(vector_id)]['chunk_text'][:350]}
                for rank, vector_id in enumerate(search['found_ids']) if vector_id >= 0
            ]})
        report = {
            'created_at': datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).isoformat(),
            'query_count': 50, 'query_kind': 'corpus-informed authored Vietnamese questions; not copied chunk queries',
            'index': {'path': str(args.index), 'type': type(index).__name__, 'vectors': index.ntotal,
                      'dimension': index.d, 'metric': 'inner product on L2 normalized vectors',
                      'M': index.hnsw.nb_neighbors(1), 'efConstruction': index.hnsw.efConstruction,
                      'stored_efSearch': original_ef, 'disk_bytes': args.index.stat().st_size},
            'metadata': {'path': str(args.metadata), 'records': len(metadata), 'disk_bytes': args.metadata.stat().st_size},
            'environment': {'platform': platform.platform(), 'python': sys.version.split()[0],
                            'faiss': faiss.__version__, 'faiss_threads': args.threads,
                            'cpu': next(line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),
                            'host_ram_bytes': int(Path('/proc/meminfo').read_text().splitlines()[0].split()[1]) * 1024},
            'model': model_info, 'model_index_agreement_cosine': {'min': float(agreement.min()), 'mean': float(agreement.mean()), 'max': float(agreement.max())},
            'embedding': {'initial_batch_seconds': initial_embedding_seconds,
                          'batch_50': statistics(batch_embedding_times),
                          'singleton': statistics(singleton_embedding_times),
                          'effective_batch_size': encoder['effective_batch_size'], 'use_fp16': encoder['use_fp16']},
            'exact_build_seconds': exact_build_seconds, 'exact_top10_latency': exact_latency,
            'end_to_end_top10_latency': statistics([r['latency_ms'] for r in e2e_samples]),
            'isolated_index_metadata_ram': isolated_memory, 'full_benchmark_ram': ram,
            'gpu_vram': gpu_memory, 'rows': rows, 'input_sha256_before': input_hashes,
            'pq': ({'subquantizers': faiss.downcast_index(index.storage).pq.M,
                    'bits': faiss.downcast_index(index.storage).pq.nbits,
                    'bytes_per_vector': faiss.downcast_index(index.storage).code_size,
                    'sample_reconstruction_cosine': pq_agreement,
                    'exhaustive_pq_recall_vs_raw_exact': pq_exhaustive} if compressed else None),
            'reference': ({'index_path': str(args.reference_index),
                           'metadata_path': str(args.reference_metadata),
                           'disk_bytes': args.reference_index.stat().st_size,
                           'metadata_byte_identical': True,
                           'isolated_index_metadata_ram': reference_memory,
                           'hnsw_rows': reference_rows} if args.reference_index else None),
            'elapsed_seconds': perf_counter() - started,
            'limitations': [
                '50 authored questions informed by sampled corpus chunks; not independent production traffic or human relevance labels.',
                'Recall measures ANN agreement with exact stored-vector search, not semantic answer correctness.',
                'Source chunk/doc hit rates are diagnostics; other valid answers may occur in other chunks/documents.',
                'Latency is warm local in-process search; excludes HTTP, network, reranking and generation.',
                'RSS includes shared libraries/allocators; PSS apportions shared pages. Host page cache is not process RSS.',
                'RAM loading JSON includes temporary text; full benchmark also includes an extra exact reference.',
                'Disk reads were already page-cache warm; load times are not cold storage benchmarks.',
                'p99 uses repeated queries; no concurrent clients, sustained load or thermal control.',
                'Bootstrap interval reflects this query sample, not corpus-wide guarantees.',
                'GTE matches 50 stored source embeddings by cosine; original uploaded build environment is unknown.',
            ],
        }
        if compressed:
            report['limitations'] += [
                'PQ recall ground truth uses the original HNSWFlat vectors, not reconstructed PQ vectors.',
                'PQ scores are approximate inner products, not exact cosine; score admissibility rescores IDs with raw vectors.',
                'Recall vs exhaustive PQ separates graph misses from quantization ranking changes.',
                'Full benchmark RAM temporarily includes the original HNSWFlat reference; serving RAM is sampled after releasing it.',
            ]
    report['input_sha256_after'] = {'index': sha256(args.index), 'metadata': sha256(args.metadata),
                                    'queries': sha256(args.queries), 'notebook': sha256(NOTEBOOK)}
    if args.reference_index:
        report['input_sha256_after']['reference_index'] = sha256(args.reference_index)
        report['input_sha256_after']['reference_metadata'] = sha256(args.reference_metadata)
    if report['input_sha256_after'] != input_hashes:
        raise RuntimeError('A benchmark input changed while running')
    write_json(args.output / 'report.json', report)
    write_json(args.output / 'query_results.json', details)
    write_json(args.output / 'per_query_sweep.json', per_query_results)
    write_csv(args.output / 'latency_samples.csv', latency_samples)
    write_csv(args.output / 'results.csv', [
        {'ef_search': row['ef_search'], **{f'recall@{k}': row[f'recall@{k}'] for k in KS},
         'score_admissibility@10': row['score_admissibility@10'],
         **{name: row['search_top10_latency'][name] for name in ('mean_ms', 'p50_ms', 'p95_ms', 'p99_ms')},
         'serial_qps': row['search_top10_latency']['serial_qps_from_timed_calls'],
         'batch_qps': row['search_top10_latency']['batch']['qps'],
         'source_chunk_hit@10': row['source_chunk_hit@10'], 'source_doc_hit@10': row['source_doc_hit@10']}
        for row in rows
    ])
    print(f'Benchmark completed in {report["elapsed_seconds"]:.2f}s; output: {args.output}', flush=True)


if __name__ == '__main__':
    main()
