"""Benchmark IVF-PQ accuracy with 50 random corpus queries against exact search."""

from __future__ import annotations

import __future__
import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
from typing import Iterator, TextIO

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / 'BackEnd/app/Database/FAISS_index_chunks.ipynb'
KS = (1, 5, 10, 20, 50)


def sha256(path: Path) -> str:
    """Hash an input without loading the whole file."""
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_records(path: Path) -> list[dict]:
    """Reuse the insertion notebook's filtering/order without running its cells."""
    namespace = {'json': json, 'Iterator': Iterator, 'TextIO': TextIO}
    notebook = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            for node in ast.parse(''.join(cell['source'])).body:
                if isinstance(node, ast.FunctionDef) and node.name in {
                    'iter_merged_documents', 'iter_chunk_records',
                }:
                    exec(compile(ast.Module(body=[node], type_ignores=[]),
                                 str(NOTEBOOK), 'exec',
                                 flags=__future__.annotations.compiler_flag), namespace)
    with path.open(encoding='utf-8-sig') as handle:
        return list(namespace['iter_chunk_records'](handle))


def recall_at_k(found: np.ndarray, exact: np.ndarray, k: int) -> float:
    """Average top-k ID overlap; duplicate/missing IDs cannot inflate recall."""
    values = []
    for actual, reference in zip(found[:, :k], exact[:, :k]):
        truth = {int(value) for value in reference if value >= 0}
        result = {int(value) for value in actual if value >= 0}
        values.append(len(result & truth) / len(truth) if truth else 0)
    return float(np.mean(values))


def remove_sources(ids: np.ndarray, sources: np.ndarray, k: int) -> np.ndarray:
    """Remove a query's own vector to measure its other neighbors separately."""
    result = np.full((len(ids), k), -1, dtype=np.int64)
    for row, source in enumerate(sources):
        keep = ids[row][(ids[row] >= 0) & (ids[row] != source)][:k]
        result[row, :len(keep)] = keep
    return result


def benchmark(index: faiss.IndexIVFPQ, vectors: np.ndarray, count: int,
              seed: int, nprobes: list[int]) -> tuple[list[dict], np.ndarray]:
    """Search random raw vectors against exact and PQ indexes using identical IDs."""
    if vectors.shape != (index.ntotal, index.d) or vectors.dtype != np.float32:
        raise ValueError('Expected float32 vectors with shape (index.ntotal, index.d)')
    if not 1 <= count <= index.ntotal or index.ntotal <= max(KS):
        raise ValueError('Invalid query count or corpus smaller than requested top-k')
    sources = np.random.default_rng(seed).choice(index.ntotal, count, replace=False)
    queries = np.ascontiguousarray(vectors[sources])
    if not np.isfinite(queries).all() or not np.allclose(np.linalg.norm(queries, axis=1), 1, atol=1e-3):
        raise ValueError('Query vectors must be finite and L2 normalized')
    exact_index = faiss.IndexFlatIP(index.d)
    exact_index.add(vectors)
    _, exact = exact_index.search(queries, max(KS) + 1)
    neighbor_truth = remove_sources(exact, sources, 10)
    original_nprobe = index.nprobe
    rows = []
    try:
        for nprobe in sorted({min(value, index.nlist) for value in nprobes}
                             | {original_nprobe, index.nlist}):
            index.nprobe = nprobe
            _, found = index.search(queries, max(KS) + 1)
            rows.append({
                'nprobe': nprobe,
                **{f'recall@{k}': recall_at_k(found, exact, k) for k in KS},
                'self_hit@1': float(np.mean(found[:, 0] == sources)),
                'self_hit@10': float(np.mean(np.any(found[:, :10] == sources[:, None], axis=1))),
                'neighbor_recall@10': recall_at_k(remove_sources(found, sources, 10), neighbor_truth, 10),
            })
    finally:
        index.nprobe = original_nprobe
    return rows, sources


def main() -> None:
    """Use the completed GPU embedding cache and export a small accuracy report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=ROOT / 'BackEnd/tests/index.faiss')
    parser.add_argument('--data', type=Path, default=ROOT / 'test_merged.json')
    parser.add_argument('--cache', type=Path, default=ROOT / 'BackEnd/tests/benchmark_cache/gte')
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    parser.add_argument('--queries', type=int, default=50)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--nprobes', type=int, nargs='+', default=[1, 4, 8, 16, 32, 64, 128, 256, 512, 1024])
    args = parser.parse_args()
    if args.output.exists():
        parser.error('--output must be a new directory')
    if args.threads < 1 or min(args.nprobes) < 1:
        parser.error('Threads and nprobe must be positive')
    faiss.omp_set_num_threads(args.threads)
    index_hash = sha256(args.index)
    index = faiss.read_index(str(args.index))
    if not isinstance(index, faiss.IndexIVFPQ) or index.metric_type != faiss.METRIC_INNER_PRODUCT:
        raise ValueError('Expected a trained inner-product IVF-PQ index')
    state = json.loads((args.cache / 'embedding_state.json').read_text())
    identity = state['identity']
    if (not state.get('complete') or identity['index_sha256'] != index_hash
            or identity['data_sha256'] != sha256(args.data)
            or identity['notebook_sha256'] != sha256(NOTEBOOK)
            or identity['start_doc_id'] != 0 or identity['end_doc_id'] != -1):
        raise ValueError('Embedding cache is incomplete or belongs to different inputs')
    vector_path = args.cache / 'corpus.npy'
    if sha256(vector_path) != state['corpus_sha256']:
        raise ValueError('Embedding cache checksum mismatch')
    records = read_records(args.data)
    if len(records) != index.ntotal:
        raise ValueError('Eligible chunk count differs from index.ntotal')
    vectors = np.load(vector_path, mmap_mode='r')
    rows, sources = benchmark(index, vectors, args.queries, args.seed, args.nprobes)
    if sha256(args.index) != index_hash:
        raise RuntimeError('Source index changed during benchmark')
    args.output.mkdir(parents=True)
    report = {
        'query_count': args.queries, 'seed': args.seed, 'vectors': index.ntotal,
        'dimension': index.d, 'nlist': index.nlist, 'pq_m': index.pq.M,
        'pq_nbits': index.pq.nbits, 'stored_nprobe': index.nprobe,
        'model_info': state['model_info'], 'index_sha256': index_hash,
        'query_source_ids': sources.tolist(), 'rows': rows,
        'method': 'Random eligible chunk embeddings versus IndexFlatIP over all regenerated raw GTE vectors',
        'limitations': ['In-corpus queries; no independent human relevance labels.',
                        'Reference vectors regenerated on GPU; original insertion vectors unavailable.',
                        'Recall compares exact neighbor IDs; equal-score duplicate chunks may differ.',
                        'neighbor_recall@10 removes the source vector from both result sets.'],
    }
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    with (args.output / 'results.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    sampled = [{'vector_id': int(i), 'chunk_id': records[int(i)]['chunk_id'],
                'text': records[int(i)]['chunk_text']} for i in sources]
    (args.output / 'sampled_queries.json').write_text(json.dumps(sampled, ensure_ascii=False, indent=2))
    lines = ['# Benchmark độ chính xác IVF-PQ', '',
             f'{args.queries} chunk ngẫu nhiên, seed {args.seed}; exact reference trên {index.ntotal:,} vector GTE chưa nén.', '',
             '| nprobe | Recall@1 | Recall@5 | Recall@10 | Recall@20 | Recall@50 | Recall@10 bỏ self |',
             '|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['nprobe']} | " + ' | '.join(
            f"{row[key]:.2%}" for key in ['recall@1', 'recall@5', 'recall@10', 'recall@20', 'recall@50', 'neighbor_recall@10']) + ' |')
    current = next(row for row in rows if row['nprobe'] == index.nprobe)
    full = next(row for row in rows if row['nprobe'] == index.nlist)
    lines.extend(['', f"Ở nprobe={index.nprobe}: tự tìm lại source top-1 {current['self_hit@1']:.0%}, top-10 {current['self_hit@10']:.0%}.", '',
                  f"Recall@10 hiện tại {current['recall@10']:.2%}, quét toàn bộ cụm {full['recall@10']:.2%}. "
                  'Tăng nprobe cải thiện rất ít trên mẫu này; phần mất recall còn lại chủ yếu do xếp hạng PQ.', '',
                  'Query là chunk nằm trong corpus; kết quả không phải độ đúng ngữ nghĩa do con người gán nhãn. '
                  'Exact dùng embedding GTE tái tạo, không dùng vector reconstruct từ PQ. '
                  'FAISS search chạy CPU; cache GTE đã được tạo trên GPU trong .venv. Index nguồn không thay đổi.', ''])
    (args.output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))
    print(f'Output: {args.output}')


if __name__ == '__main__':
    main()
