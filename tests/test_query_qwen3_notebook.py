import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


NOTEBOOK = (Path(__file__).resolve().parents[1] /
            'BackEnd/app/Database/Notebook/Query_Qwen3_06B_1024_FP16_Colab.ipynb')


def load_notebook(tmp_path, table):
    cells = {cell['id']: cell['source'] for cell in json.loads(NOTEBOOK.read_text())['cells']}
    namespace = {}
    exec(cells['config'], namespace)
    source = tmp_path / 'queries.parquet'
    pq.write_table(table, source)
    namespace.update(INPUT_PATH=str(source), ROW_BATCH_SIZE=2, DOWNLOAD_OUTPUT=False)
    return cells, namespace, source


def vector_for(text):
    vector = np.zeros(1024, dtype=np.float16)
    vector[sum(text.encode('utf-8')) % 1024] = 1
    return vector


def test_roundtrip_replaces_text_and_preserves_other_columns(tmp_path):
    source_table = pa.table({
        'id': pa.array([9, 2, 5, 1, 7], type=pa.int64()),
        'query': ['Việt', 'Câu hai', 'Ba', 'Bốn', 'Năm'],
        'english': ['one', 'two', 'three', 'four', 'five'],
        'chinese': ['一', '二', '三', '四', '五'],
        'dense_weight': [0.1, 0.9, 0.3, 0.6, 1.0],
        'extra': ['keep', None, 'unchanged', '', 'last'],
    }).replace_schema_metadata({b'custom': b'preserve', b'pandas': b'old-text-types'})
    cells, namespace, source = load_notebook(tmp_path, source_table)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    exec(cells['input'], namespace)
    exec(cells['functions'], namespace)
    encoded = []

    def encode(texts):
        encoded.extend(texts)
        return np.stack([vector_for(text) for text in texts])

    namespace['encode_texts'] = encode
    exec(cells['embed'], namespace)
    result = pq.read_table(namespace['output_path'])
    assert result.column_names == source_table.column_names
    for name in ('id', 'dense_weight', 'extra'):
        assert result[name].equals(source_table[name])
        assert result.schema.field(name) == source_table.schema.field(name)
    for name in namespace['TEXT_COLUMNS']:
        assert result.schema.field(name).type == pa.list_(pa.float16(), 1024)
        expected = np.stack([vector_for(text) for text in source_table[name].to_pylist()])
        np.testing.assert_array_equal(result[name].to_pylist(), expected)
    assert len(encoded) == 15
    assert result.schema.metadata[b'custom'] == b'preserve'
    assert b'pandas' not in result.schema.metadata
    info = json.loads(result.schema.metadata[b'query_embedding'])
    assert info['source_sha256'] == before
    assert info['encoder']['storage_dtype'] == 'float16'
    assert namespace['validate_output'](namespace['output_path']) == 5
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob('*.partial'))


@pytest.mark.parametrize('bad_text', [None, '', '   '])
def test_invalid_text_rejected_before_model_load(tmp_path, bad_text):
    table = pa.table({'id': [1], 'query': [bad_text], 'english': ['a'], 'chinese': ['b']},
                     schema=pa.schema([('id', pa.int64()), ('query', pa.string()),
                                       ('english', pa.string()), ('chinese', pa.string())]))
    cells, namespace, _ = load_notebook(tmp_path, table)
    with pytest.raises(ValueError, match='null/'):
        exec(cells['input'], namespace)
    assert not list(tmp_path.glob('*fp16.parquet'))


def test_token_sorting_restores_order_and_never_truncates(tmp_path):
    table = pa.table({'query': ['a'], 'english': ['b'], 'chinese': ['c']})
    cells, namespace, _ = load_notebook(tmp_path, table)
    exec(cells['functions'], namespace)
    seen = []

    class Tokenizer:
        def __call__(self, texts, **kwargs):
            assert kwargs['truncation'] is False
            seen.extend(texts)
            return {'input_ids': [list(text.encode('utf-8')) for text in texts]}

    def forward(items):
        vectors = np.zeros((len(items), 1024), dtype=np.float16)
        for index, item in enumerate(items):
            vectors[index, sum(item['input_ids']) % 1024] = 1
        return vectors

    namespace.update(tokenizer=Tokenizer(), forward_with_retry=forward,
                     ENCODER_BATCH_SIZE=2, PADDED_TOKEN_BUDGET=256)
    texts = ['a', 'Tiếng Việt dài hơn', '中文']
    actual = namespace['encode_texts'](texts)
    expected_texts = [namespace['format_query'](text) for text in texts]
    assert seen == expected_texts
    assert expected_texts[0].endswith('\nQuery:a')
    np.testing.assert_array_equal(actual, np.stack([vector_for(text) for text in expected_texts]))
    namespace['ENCODER']['max_length'] = 4
    with pytest.raises(ValueError, match='không cắt text'):
        namespace['encode_texts'](['too long'])
