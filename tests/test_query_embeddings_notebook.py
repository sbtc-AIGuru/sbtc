import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from Scripts.Qdrant.build_gte_qdrant import encode_records


NOTEBOOK = Path(__file__).resolve().parents[1] / 'BackEnd/app/Database/Notebook/Query_GTE_Embeddings_Colab.ipynb'


def notebook_namespace(tmp_path, rows):
    notebook = json.loads(NOTEBOOK.read_text())
    namespace = {}
    exec(notebook['cells'][2]['source'], namespace)
    source = tmp_path / 'queries.parquet'
    pq.write_table(pa.Table.from_pylist(rows), source)
    namespace.update(INPUT_PATH=str(source), DOWNLOAD_OUTPUT=False, ROW_BATCH_SIZE=2)
    return notebook, namespace


def test_roundtrip_keeps_ids_languages_and_extra_columns(tmp_path):
    rows = [
        dict(id=9, query='Tiếng Việt', english='English one', chinese='中文一', extra='a'),
        dict(id=2, query='Câu hai', english='English two', chinese='中文二', extra=None),
        dict(id=5, query='Câu ba', english='English three', chinese='中文三', extra='c'),
    ]
    notebook, namespace = notebook_namespace(tmp_path, rows)
    exec(notebook['cells'][3]['source'], namespace)
    exec(notebook['cells'][5]['source'], namespace)
    encoded = []

    def encoder(texts):
        encoded.extend(texts)
        vectors = np.zeros((len(texts), 768), dtype=np.float32)
        for index, text in enumerate(texts):
            vectors[index, sum(text.encode('utf-8')) % 768] = 1
        return vectors

    namespace.update(encode_texts=encoder, inference_dtype=namespace['torch'].float32, device='cpu')
    exec(notebook['cells'][6]['source'], namespace)
    result = pq.read_table(namespace['output_path'])
    assert result.select(list(rows[0])).to_pylist() == rows
    assert encoded == [row[name] for row in rows for name in ('query', 'english', 'chinese')]
    for index, row in enumerate(rows):
        output = result.slice(index, 1).to_pylist()[0]
        for text_column, vector_column in namespace['VECTOR_COLUMNS'].items():
            assert np.argmax(output[vector_column]) == sum(row[text_column].encode('utf-8')) % 768
    metadata = json.loads(result.schema.metadata[b'query_embedding'])
    assert metadata['encoder']['revision'] == '9bbca17d9273fd0d03d5725c7a4b0f6b45142062'
    assert namespace['validate_output'](namespace['output_path']) == 3
    assert not list(tmp_path.glob('*.partial'))


@pytest.mark.parametrize('rows', [
    [dict(id=1, query='a', english='b', chinese='c')] * 2,
    [dict(id=1, query='a', english='', chinese='c')],
])
def test_invalid_input_fails_before_loading_encoder(tmp_path, rows):
    notebook, namespace = notebook_namespace(tmp_path, rows)
    with pytest.raises(ValueError):
        exec(notebook['cells'][3]['source'], namespace)
    assert not list(tmp_path.glob('*embeddings.parquet'))


def test_window_pooling_matches_existing_index_encoder(tmp_path):
    notebook, namespace = notebook_namespace(tmp_path, [dict(id=1, query='a', english='b', chinese='c')])
    exec(notebook['cells'][5]['source'], namespace)

    class Tokenizer:
        def __call__(self, texts, **kwargs):
            return {'input_ids': [[ord(char) for char in text] for text in texts]}

        def num_special_tokens_to_add(self, **kwargs):
            return 2

        def build_inputs_with_special_tokens(self, piece):
            return [1, *piece, 2]

    def forward(windows):
        vectors = np.array([[sum(window['input_ids']), len(window['input_ids']),
                             max(window['input_ids']), 1] for window in windows], dtype=np.float32)
        return namespace['normalize_vectors'](vectors)

    texts = ['ab', '越南語中文English dài hơn cửa sổ', 'x']
    namespace.update(tokenizer=Tokenizer(), forward=forward)
    namespace['ENCODER'].update(max_length=7, dimension=4)
    actual = namespace['encode_texts'](texts)
    config = dict(max_length=7, dimension=4, batch_size=8, token_budget=8192)
    expected, long_count = encode_records([{'text': text} for text in texts], Tokenizer(), forward, config)
    assert long_count == 1
    np.testing.assert_allclose(actual, expected, rtol=0, atol=0)
