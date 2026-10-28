"""Offline checks for the standalone dense-only Qwen3 snapshot notebook."""

import ast
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import tarfile
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest


FOLDER = Path(__file__).resolve().parents[1] / 'BackEnd/app/Database/Notebook'
NOTEBOOK = FOLDER / 'Qdrant_Qwen3_Embedding_0.6B_1024_Dense_Snapshot_2GPU.ipynb'


@pytest.fixture
def notebook():
    return json.loads(NOTEBOOK.read_text())


def embedded_sources(notebook):
    tree = ast.parse(''.join(notebook['cells'][6]['source']))
    return {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)}


@pytest.fixture
def modules(notebook):
    result = {}
    for name, source in embedded_sources(notebook).items():
        module = ModuleType(name)
        exec(compile(source, f'<{name}>', 'exec'), module.__dict__)
        result[name] = module
    return result


@pytest.fixture
def config(notebook, tmp_path):
    tree = ast.parse(''.join(notebook['cells'][4]['source']))
    value = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'config')
    config = eval(compile(ast.Expression(value), '<config>', 'eval'), {'candidates': [tmp_path / 'source.jsonl']})
    config.update(state_dir=str(tmp_path / 'state'), output=str(tmp_path / 'output'),
                  output_budget_root=str(tmp_path / 'output'), expected_documents=1, expected_chunks=2)
    Path(config['state_dir']).mkdir()
    Path(config['output']).mkdir()
    return config


def test_standalone_and_unrelated_processing_is_preserved(notebook):
    assert notebook['metadata']['kaggle']['isGpuEnabled'] is True
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            compile(''.join(cell['source']), '<notebook_cell>', 'exec')
            assert cell['execution_count'] is None and cell['outputs'] == []
    sources = embedded_sources(notebook)
    assert all('bm25' not in source.lower() and 'hybrid' not in source.lower() for source in sources.values())
    original = json.loads((FOLDER / 'Qdrant_GTE_Snapshot_2GPU.ipynb').read_text())
    original_runner = embedded_sources(original)['runner_source']
    functions = {node.name: ast.dump(node) for node in ast.parse(original_runner).body
                 if isinstance(node, ast.FunctionDef)}
    changed = {'vector_schema', 'load_encoder', 'check_resources', 'create_collection',
               'upsert_batch', 'check_search', 'export_snapshot', 'run_pipeline'}
    for node in ast.parse(sources['runner_source']).body:
        if isinstance(node, ast.FunctionDef) and node.name not in changed:
            assert ast.dump(node) == functions[node.name], node.name
    for index in (1, 2, 9):
        assert notebook['cells'][index] == original['cells'][index]
    assert 'torch_dtype=torch.float16' in sources['runner_source']
    assert 'last_hidden_state[:, -1].float()' in sources['runner_source']
    assert 'dtype=np.float32' in sources['runner_source']


def test_fp16_encoder_last_token_pooling_and_empty_chunks(modules, monkeypatch):
    import torch
    from tokenizers import Tokenizer, models, pre_tokenizers
    import transformers

    runner = modules['runner_source']
    backend = Tokenizer(models.WordLevel(
        {'[UNK]': 0, '[PAD]': 1, '[EOS]': 2, 'one': 3, 'two': 4}, unk_token='[UNK]'))
    backend.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer = transformers.PreTrainedTokenizerFast(
        tokenizer_object=backend, unk_token='[UNK]', pad_token='[PAD]', eos_token='[EOS]',
        model_input_names=['input_ids', 'attention_mask'])
    model = transformers.Qwen3Model(transformers.Qwen3Config(
        vocab_size=5, hidden_size=32, intermediate_size=64, num_hidden_layers=1,
        num_attention_heads=2, num_key_value_heads=1, head_dim=16,
        max_position_embeddings=64, pad_token_id=1, attn_implementation='sdpa'))

    def load_tokenizer(*args, **kwargs):
        tokenizer.padding_side = kwargs['padding_side']
        return tokenizer

    def load_model(*args, **kwargs):
        assert kwargs['torch_dtype'] == torch.float16
        return model.to(dtype=kwargs['torch_dtype'])

    monkeypatch.setattr(transformers.AutoTokenizer, 'from_pretrained', load_tokenizer)
    monkeypatch.setattr(transformers.AutoModel, 'from_pretrained', load_model)
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: True)
    monkeypatch.setattr(torch.cuda, 'device_count', lambda: 1)
    monkeypatch.setattr(torch.cuda, 'synchronize', lambda device: None)
    monkeypatch.setattr(torch.cuda, 'get_device_name', lambda rank: 'CPU test')
    cpu = torch.device('cpu')
    monkeypatch.setattr(torch, 'device', lambda name: cpu)
    config = {'model': 'Qwen/Qwen3-Embedding-0.6B', 'revision': 'test', 'dimension': 32,
              'rank': 0, 'batch_size': 8, 'max_length': 3, 'token_budget': 24}
    previous_threads = torch.get_num_threads()
    try:
        _, forward = runner.load_encoder(config)
        assert next(model.parameters()).dtype == torch.float16
        assert tokenizer.padding_side == 'left' and model.config.use_cache is False
        vectors, long_count = runner.encode_records(
            [{'text': text} for text in ('', 'one two one two', 'two')], tokenizer, forward, config)
        pieces = []
        for ids in ([2], [3, 4, 3], [4]):
            with torch.inference_mode():
                output = model(input_ids=torch.tensor([ids]), use_cache=False)
            assert output.past_key_values is None
            pieces.append(output.last_hidden_state[0, -1].float().numpy())
        pieces = runner.normalize_vectors(np.array(pieces))
        expected = runner.normalize_vectors(np.array([
            pieces[0], 3 * pieces[1] + pieces[2], pieces[2]]))
        np.testing.assert_allclose(vectors, expected, atol=2e-3)
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-6)
        assert long_count == 1 and vectors.dtype == np.float32
    finally:
        torch.set_num_threads(previous_threads)


def test_create_dense_collection_and_keep_original_payload(modules, config, monkeypatch):
    runner = modules['runner_source']
    assert config['dimension'] == 1024 and config['max_length'] == 8192
    assert config['model'] == 'Qwen/Qwen3-Embedding-0.6B'
    assert config['hnsw_m'] == 32 and config['ef_construction'] == 100
    monkeypatch.setattr(runner.requests, 'get', lambda *a, **k: SimpleNamespace(status_code=404))
    calls = []

    def api(config, method, path, body=None, **kwargs):
        calls.append((method, path, body))
        return {'status': 'completed'}

    monkeypatch.setattr(runner, 'api', api)
    runner.create_collection(config)
    collection = calls[0][2]
    assert collection['vectors'] == {'dense': {
        'size': 1024, 'distance': 'Cosine', 'on_disk': True, 'datatype': 'float16'}}
    assert 'sparse_vectors' not in collection and collection['on_disk_payload'] is True
    assert {call[2]['field_name'] for call in calls[1:]} == {'chunk_id', 'parent_id'}
    document = {'doc_id': 1, 'url': 'https://example.org', 'source_language': 'vi'}
    records = [runner.make_record(document, {
        'chunk_id': f'c{i}', 'parent_id': 'p0', 'chunk_order': i, 'start_char': 0,
        'end_char': len(text), 'chunk_text': text, 'retrieval_eligible': False,
    }, 1) for i, text in enumerate(('Tiếng Việt 中文 English', ''))]
    vectors = runner.normalize_vectors(np.ones((2, 1024), dtype=np.float32))
    runner.upsert_batch(config, records, vectors, None)
    points = calls[-1][2]['points']
    for index, point in enumerate(points):
        assert set(point['vector']) == {'dense'}
        assert len(point['vector']['dense']) == 1024
        assert point['payload'] == records[index]
        assert point['id'] == runner.point_id(records[index]['chunk_id'])
    assert points[1]['payload']['empty_text'] is True


@pytest.mark.parametrize('datatype,sparse', [('float32', {}), ('float16', {'lexical': {}})])
def test_reject_wrong_existing_schema(modules, config, monkeypatch, datatype, sparse):
    runner = modules['runner_source']
    params = {'vectors': {'dense': {'size': 1024, 'distance': 'Cosine', 'datatype': datatype}},
              'sparse_vectors': sparse}
    monkeypatch.setattr(runner.requests, 'get', lambda *a, **k: SimpleNamespace(
        status_code=200, raise_for_status=lambda: None,
        json=lambda: {'result': {'config': {'params': params}}}))
    with pytest.raises(ValueError, match='dense-only'):
        runner.create_collection(config)


@pytest.fixture
def sample(modules, config):
    payload = {'chunk_id': 'c0', 'parent_id': 'p0', 'chunk_text': 'Tiếng Việt 中文 English', 'empty_text': False}
    vector = [0.03125] * 1024
    point = {'id': modules['runner_source'].point_id('c0'), 'payload': payload, 'vector': {'dense': vector}}
    info = {'config': {'params': {'vectors': {'dense': {
        'size': 1024, 'datatype': 'float16', 'distance': 'Cosine'}}, 'sparse_vectors': {}}},
        'payload_schema': {'chunk_id': {}, 'parent_id': {}}}
    return point, info


def test_dense_verification_and_readonly_client(modules, config, sample, monkeypatch, tmp_path):
    runner, restore = modules['runner_source'], modules['restore_source']
    point, info = sample
    calls = []

    def api(config, method, path, body=None, **kwargs):
        calls.append((method, path, body))
        if method == 'GET':
            return info
        if path.endswith('/points/count'):
            return {'count': 2}
        if path.endswith('/points/query'):
            assert body['query'] == point['vector']['dense'] and body['using'] == 'dense'
            assert 'prefetch' not in body
            return {'points': [{'score': 1.0, **point}]}
        assert path.endswith('/points/scroll')
        return {'points': [point]}

    monkeypatch.setattr(runner, 'api', api)
    assert runner.check_search(config) == {
        'point_id': point['id'], 'chunk_id': 'c0', 'parent_id': 'p0', 'dense': True, 'payload_lookup': True}
    manifest = {'complete': True, 'collection': config['collection'], 'points': 2,
                'signature': runner.signature(config), 'vector_schema': runner.vector_schema(config)}
    manifest_path = tmp_path / 'snapshot_manifest.json'
    manifest_path.write_text(json.dumps(manifest))

    @contextmanager
    def urlopen(request, timeout):
        body = json.loads(request.data) if request.data else None
        path = request.full_url.removeprefix('http://localhost:6333')
        yield io.BytesIO(json.dumps({'result': api(config, request.method, path, body)}).encode())

    monkeypatch.setattr(restore, 'urlopen', urlopen)
    assert restore.verify(tmp_path, 'http://localhost:6333')['dense'] is True
    session = SimpleNamespace(request=lambda method, url, json, **kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {'result': api(config, method, url, json)}))
    with modules['client_source'].QdrantManager.from_manifest(manifest_path, session=session) as client:
        assert client.search_dense(point['vector']['dense'])[0]['payload'] == point['payload']
    assert all('bm25' not in json.dumps(body or {}).lower() for _, _, body in calls)


@pytest.mark.parametrize('compressed', [False, True])
def test_export_restore_checksum_and_manifest(modules, config, monkeypatch, compressed):
    runner = modules['runner_source']
    folder = Path(config['state_dir']) / 'snapshots' / config['collection']
    folder.mkdir(parents=True)
    raw = folder / 'test.snapshot'
    with tarfile.open(raw, 'w') as archive:
        item = tarfile.TarInfo('data.bin')
        item.size = 2048
        archive.addfile(item, io.BytesIO(b'x' * 2048))
    monkeypatch.setattr(runner, 'count_points', lambda config: 2)
    monkeypatch.setattr(runner, 'api', lambda *args, **kwargs: {'name': raw.name})
    monkeypatch.setattr(runner, 'verify_snapshot_restore', lambda *args: {'verified': True, 'search': {'dense': True}})
    if compressed:
        monkeypatch.setattr(runner, 'output_budget', lambda config: raw.stat().st_size // 2)
    manifest = runner.export_snapshot(config, complete=True)
    assert manifest['embedding']['inference'] == 'float16'
    assert manifest['embedding']['storage'] == 'float16'
    assert manifest['vector_schema'] == {'dense': 'dense', 'dense_datatype': 'float16'}
    assert '_dense.snapshot' in manifest['snapshot_file']
    assert manifest['snapshot_file'].endswith('.gz') == compressed
    _, unpacked = modules['restore_source'].unpack(Path(config['output']))
    assert hashlib.sha256(unpacked.read_bytes()).hexdigest() == manifest['raw_snapshot_sha256']
    assert unpacked.read_bytes() == raw.read_bytes()
