import json
import io
import zipfile
from threading import Event
from unittest.mock import Mock

from fastapi import HTTPException, UploadFile
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from BackEnd.app import pipeline
from BackEnd.app.api.main import Jobs, create_app
from test_pipeline import Response, Transport, database, factory, point, write_embedded_queries, write_queries


class VectorTransport(Transport):
    def request(self, method, url, **options):
        if method == 'GET':
            return Response({'config': {'params': {
                'vectors': {'dense': {'size': 768}}, 'sparse_vectors': {'bm25': {}},
            }}})
        return super().request(method, url, **options)


class CaptureTransport(VectorTransport):
    def request(self, method, url, **options):
        if method == 'GET':
            return super().request(method, url, **options)
        self.calls.append(options['json'])
        return Response({'points': []})


@pytest.mark.parametrize('search_mode', ['4-branch', '6-branch'])
@pytest.mark.parametrize('rerank', [False, True])
@pytest.mark.parametrize('max_chunks', [None, 0, 1])
def test_only_top_k_documents_are_saved_independently_of_chunk_output_limit(tmp_path, search_mode, rerank, max_chunks):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(1,))
    hits = [point('8:a', 8, 'Eighth'), point('7:a', 7, 'Seventh'),
            point('9:a', 9, 'Outside top-k'), point('8:b', '8', 'Duplicate document'),
            point('10:a', 10, '')]
    transport = VectorTransport({1: hits})
    reranker = Mock()
    reranker.score.return_value = [0.1, 0.9]
    output, archive = tmp_path / 'output.json', tmp_path / 'output.zip'
    predictions = pipeline.run_pipeline(
        path, output, zip_path=archive, search_mode=search_mode, top_k=2,
        max_chunks=max_chunks, rerank=rerank, reranker=reranker,
        qdrant_factory=factory(transport, []),
    )
    assert predictions[0]['relevant_docs'] == [8, 7]
    expected = [{'doc_id': 8, 'chunk_text': 'Eighth'}, {'doc_id': 7, 'chunk_text': 'Seventh'}]
    if rerank:
        expected.reverse()
        reranker.score.assert_called_once_with('VI 1', ['Eighth', 'Seventh'])
    else:
        reranker.score.assert_not_called()
    assert predictions[0]['relevant_chunks'] == expected[:max_chunks]
    assert transport.calls[0]['limit'] == 2
    with zipfile.ZipFile(archive) as zipped:
        assert json.loads(zipped.read('output.json')) == predictions
    checkpoint = [json.loads(line) for line in output.with_suffix('.checkpoint.jsonl').read_text().splitlines()]
    assert checkpoint[1]['prediction']['relevant_docs'] == [8, 7]


def test_documents_after_duplicate_chunk_top_k_do_not_expand_chunk_pool(tmp_path):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(1,))
    first = point('7:a', 7, 'First')
    transport = VectorTransport({1: [first, first, point('9:a', 9, 'Outside top-k')]})
    result = pipeline.run_pipeline(path, top_k=2, qdrant_factory=factory(transport, []))
    assert result == [{'id': 1, 'relevant_docs': [7],
                       'relevant_chunks': [{'doc_id': 7, 'chunk_text': 'First'}]}]


def test_outside_top_k_document_is_not_requested_or_hydrated(tmp_path):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(1,))
    transport = VectorTransport({1: [point('2:a', 2, 'Top result'),
                                    {'id': 'document-only', 'payload': {'doc_id': '1'}}]})
    database = Mock()
    database.get_submission_chunks.side_effect = AssertionError('Document IDs do not need PostgreSQL')
    result = pipeline.run_pipeline(path, top_k=1, qdrant_factory=factory(transport, []),
                                   postgres_manager=database)
    assert result == [{'id': 1, 'relevant_docs': [2],
                       'relevant_chunks': [{'doc_id': 2, 'chunk_text': 'Top result'}]}]
    database.get_submission_chunks.assert_not_called()


def test_only_top_k_missing_chunk_text_is_hydrated(tmp_path, database):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(1,))
    transport = VectorTransport({1: [point('1:c:0', 1, None), point('2:a', 2, None),
                                    {'id': 'third', 'payload': {'doc_id': 3}}]})
    source = Mock(wraps=database)
    result = pipeline.run_pipeline(path, top_k=1, qdrant_factory=factory(transport, []),
                                   postgres_manager=source)
    source.get_submission_chunks.assert_called_once_with(['1:c:0'])
    assert result == [{'id': 1, 'relevant_docs': [1],
                       'relevant_chunks': [{'doc_id': 1, 'chunk_text': 'Original source\n中文。'}]}]


def test_missing_doc_id_outside_top_k_does_not_fail_query(tmp_path):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(1,))
    transport = VectorTransport({1: [point('2:a', 2, 'Top result'), point('missing', None, None)]})
    source = Mock()
    result = pipeline.run_pipeline(path, top_k=1, qdrant_factory=factory(transport, []), postgres_manager=source)
    assert result[0]['relevant_docs'] == [2]
    source.get_submission_chunks.assert_not_called()


@pytest.mark.parametrize('search_mode,dense_count', [('4-branch', 1), ('6-branch', 3)])
def test_precomputed_vectors_reach_qdrant_without_encoder(tmp_path, monkeypatch, search_mode, dense_count):
    # Repeated texts across rows/languages must still use that row's exact vectors.
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(30, 10),
                                  query=['VI 30', 'VI 10'], english=['same 99', 'same 99'],
                                  chinese=['same 99', 'same 99'])
    rows = pq.read_table(path).to_pylist()
    transport = VectorTransport({30: [point('a', 7)], 10: [point('b', 8)]})
    managers = []
    loader = Mock(side_effect=AssertionError('Must not load GTE'))
    encoder = Mock(side_effect=AssertionError('Must not embed text'))
    monkeypatch.setattr(pipeline, 'load_dense_encoder', loader)
    result = pipeline.run_pipeline(path, search_mode=search_mode, batch_size=2, workers=2,
                                   qdrant_factory=factory(transport, managers), dense_encoder=encoder)
    assert [row['id'] for row in result] == [30, 10]
    loader.assert_not_called()
    encoder.assert_not_called()
    for request in transport.calls:
        identifier = int(request['prefetch'][dense_count]['query']['text'].split()[-1])
        row = next(row for row in rows if row['id'] == identifier)
        assert [branch['query'] for branch in request['prefetch'][:dense_count]] == [
            row[name] for name in list(pipeline.VECTOR_COLUMNS.values())[:dense_count]
        ]
        assert [branch['query']['text'] for branch in request['prefetch'][dense_count:]] == [
            row[name] for name in ('query', 'english', 'chinese')
        ]
        assert request['query']['rrf']['weights'] == pytest.approx([0.5 / dense_count] * dense_count + [0.5 / 3] * 3)
    assert all(manager._config is not None for manager in managers)


@pytest.mark.parametrize('search_mode,dense_count', [('4-branch', 1), ('6-branch', 3)])
@pytest.mark.parametrize('values', [[None, float('nan'), 0, 1, 0.6, 0.2], ['', '  ', '0', '1', '0.6', '0.2']])
def test_per_row_adaptive_weight_defaults_and_extremes(tmp_path, monkeypatch, search_mode, dense_count, values):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=range(1, 7), dense_weight=values)
    rows = pq.read_table(path).to_pylist()
    transport = CaptureTransport({})
    monkeypatch.setattr(pipeline, 'load_dense_encoder', Mock(side_effect=AssertionError('Must not embed')))
    result = pipeline.run_pipeline(path, search_mode=search_mode, batch_size=2, workers=2,
                                   qdrant_factory=factory(transport, []))
    assert [item['id'] for item in result] == list(range(1, 7))
    assert len(transport.calls) == 6
    for request in transport.calls:
        dense = [branch for branch in request['prefetch'] if isinstance(branch['query'], list)]
        lexical = [branch for branch in request['prefetch'] if isinstance(branch['query'], dict)]
        row_index = dense[0]['query'].index(1.0) // 3 if dense else int(lexical[0]['query']['text'].split()[-1]) - 1
        weight = [0.5, 0.5, 0, 1, 0.6, 0.2][row_index]
        assert len(dense) == (dense_count if weight > 0 else 0)
        assert len(lexical) == (3 if weight < 1 else 0)
        assert request['query']['rrf']['weights'] == pytest.approx(
            [weight / dense_count] * len(dense) + [(1 - weight) / 3] * len(lexical)
        )
        assert [branch['query'] for branch in dense] == [
            rows[row_index][name] for name in list(pipeline.VECTOR_COLUMNS.values())[:len(dense)]
        ]


@pytest.mark.parametrize('value', [-0.1, 1.1, float('inf'), 'bad', True])
def test_invalid_weight_fails_only_its_input_row(tmp_path, value):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(1, 2), dense_weight=[value, None])
    transport = CaptureTransport({})
    with pytest.raises(pipeline.PipelineError) as error:
        pipeline.run_pipeline(path, qdrant_factory=factory(transport, []))
    assert error.value.failures == [{'row': 0, 'id': 1, 'stage': 'input', 'error_type': 'ValueError'}]
    assert len(transport.calls) == 1


def test_resume_rejects_changed_dense_weights(tmp_path):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(1, 2), dense_weight=[0.2, 0.8])
    transport = CaptureTransport({})
    output = tmp_path / 'output.json'
    stop = Event()
    options = dict(qdrant_factory=factory(transport, []), resume_tag='adaptive-v1', batch_size=1)

    def progress(state):
        if state['completed'] == 1:
            stop.set()

    with pytest.raises(pipeline.PipelinePaused):
        pipeline.run_pipeline(path, output, stop_event=stop, progress_callback=progress, **options)
    table = pq.read_table(path)
    table = table.set_column(table.schema.get_field_index('dense_weight'), 'dense_weight', pa.array([0.9, 0.8]))
    pq.write_table(table, path)
    with pytest.raises(ValueError, match='configuration changed'):
        pipeline.run_pipeline(path, output, resume=True, **options)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('change', ['model', 'revision', 'pooling', 'mapping', 'missing_metadata', 'dimension'])
def test_bad_embedding_schema_rejected_before_retrieval(tmp_path, change):
    path = write_embedded_queries(tmp_path / 'queries.parquet')
    table = pq.read_table(path)
    metadata = json.loads(table.schema.metadata[b'query_embedding'])
    if change in ('model', 'revision', 'pooling'):
        metadata['encoder'][change] = 'wrong'
    elif change == 'mapping':
        metadata['vector_columns']['english'] = 'vector_chinese'
    elif change == 'dimension':
        table = table.set_column(table.schema.get_field_index('vector_original'), 'vector_original',
                                 pa.array([[1.0, 0.0]] * table.num_rows, type=pa.list_(pa.float32(), 2)))
    table = table.replace_schema_metadata({} if change == 'missing_metadata' else {
        b'query_embedding': json.dumps(metadata).encode(),
    })
    pq.write_table(table, path)
    create = Mock()
    with pytest.raises(ValueError):
        pipeline.run_pipeline(path, qdrant_factory=create)
    create.assert_not_called()


@pytest.mark.parametrize('change', ['changed_text', 'null_value', 'nan', 'zero', 'not_normalized'])
def test_corrupt_row_is_rejected_without_losing_other_rows(tmp_path, change):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(1, 2))
    table = pq.read_table(path)
    rows = table.to_pylist()
    if change == 'changed_text':
        rows[0]['english'] = 'changed translation'
    elif change == 'null_value':
        rows[0]['vector_english'][0] = None
    else:
        rows[0]['vector_english'] = [0.0] * 768
        rows[0]['vector_english'][0] = {'nan': float('nan'), 'zero': 0.0, 'not_normalized': 2.0}[change]
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    transport = VectorTransport({})
    with pytest.raises(pipeline.PipelineError) as error:
        pipeline.run_pipeline(path, qdrant_factory=factory(transport, []))
    assert error.value.failures == [{'row': 0, 'id': 1, 'stage': 'input', 'error_type': 'ValueError'}]
    assert len(transport.calls) == 1


def test_precomputed_range_pause_resume_and_rerank(tmp_path):
    path = write_embedded_queries(tmp_path / 'queries.parquet', identifiers=(1, 2, 3))
    transport = VectorTransport({i: [point(f'{i}:a', i), point(f'{i}:b', i + 10)] for i in (1, 2, 3)})
    reranker = Mock()
    reranker.score.return_value = [0.1, 0.9]
    stop = Event()

    def progress(state):
        if state['completed'] == 1:
            stop.set()

    options = dict(qdrant_factory=factory(transport, []), reranker=reranker, rerank=True,
                   batch_size=1, start=2, resume_tag='precomputed-v1')
    output = tmp_path / 'output.json'
    with pytest.raises(pipeline.PipelinePaused):
        pipeline.run_pipeline(path, output, stop_event=stop, progress_callback=progress, **options)
    result = pipeline.run_pipeline(path, output, resume=True, **options)
    assert [row['id'] for row in result] == [2, 3]
    assert len(transport.calls) == 2
    assert result[0]['relevant_chunks'][0]['doc_id'] == 12


def test_upload_endpoint_accepts_embedded_file_and_rejects_text_only(tmp_path):
    path = write_embedded_queries(tmp_path / 'embedded.parquet')
    text = write_queries(tmp_path / 'text.parquet')
    root = tmp_path / 'jobs'
    root.mkdir()
    app = create_app(jobs_dir=root)
    jobs = Jobs(root, Mock(), {})
    jobs.enqueue = Mock()
    app.state.jobs = jobs
    upload = next(route.endpoint for route in app.routes if route.path == '/api/jobs' and 'POST' in route.methods)
    try:
        with pytest.raises(HTTPException) as error:
            upload(UploadFile(io.BytesIO(text.read_bytes()), filename='text.parquet'))
        assert error.value.status_code == 400 and 'vector' in error.value.detail
        jobs.enqueue.assert_not_called()
        result = upload(UploadFile(io.BytesIO(path.read_bytes()), filename='embedded.parquet'))
        assert result['rows'] == 3 and result['filename'] == 'embedded.parquet'
        jobs.enqueue.assert_called_once_with(result['id'])
    finally:
        jobs.pool.shutdown()
