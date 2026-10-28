from collections import Counter
from unittest.mock import Mock

import pytest

from BackEnd.app.Database import elastic_search as es


def test_unweighted_request_preserves_existing_behavior_and_filters():
    filters = [{"term": {"doc_id": "7"}}]
    assert es.bm25_query("My SCC level is 1.52, not above normal", "en", filters=filters) == {
        "bool": {"must": [{"match": {"content_en": "My SCC level is 1.52, not above normal"}}],
                 "filter": [{"term": {"lang": "en"}}, *filters]}}


def test_downweighting_keeps_every_analyzed_term_and_or_eligibility():
    tokens = ['i', 'have', 'no', 'fever', 'my', 'scc', 'is', '1.52', 'not', 'above', 'normal', 'mg', 'ml', 'my']
    plan = es.bm25_query('original stays unchanged', 'en', tokens=tokens)
    inner = plan['bool']['must'][0]['bool']
    assert inner['minimum_should_match'] == 1
    matches = [clause['match']['content_en'] for clause in inner['should']]
    assert Counter(term for match in matches for term in match['query'].split()) == Counter(tokens)
    assert all(match['analyzer'] == 'whitespace' for match in matches)
    assert matches[1]['boost'] == .05
    assert matches[0]['query'] == 'have no fever scc is 1.52 not above normal mg ml'
    assert plan['bool']['filter'] == [{'term': {'lang': 'en'}}]
    assert not ({'no', 'not', 'without', 'before', 'after', 'mother', 'baby', 'us'} & es.PERSONAL_TERMS)


@pytest.mark.parametrize('tokens', [[], ['my','i'], ['no','fever','1.52']])
def test_unsplittable_query_uses_original_match(tokens):
    assert es.bm25_query('My query', 'en', tokens=tokens) == es.bm25_query('My query', 'en')


def test_english_search_uses_actual_index_analyzer_and_retains_filters():
    client = Mock()
    client.indices.analyze.return_value = {'tokens': [{'token': token} for token in ['my','scc','not','1.52']]}
    client.search.return_value = {'hits': {'hits': [{'_id': 'found'}]}}
    text = 'My SCC, not 1.52'
    assert es.search_bm25(text, 'en', 100, client=client, index='test',
                          filters=[{'term': {'doc_id': '7'}}]) == [{'_id': 'found'}]
    client.indices.analyze.assert_called_once_with(index='test', analyzer='medical_en', text=text)
    request = client.search.call_args.kwargs
    assert request['size'] == 100
    assert request['query']['bool']['filter'] == [{'term': {'lang': 'en'}}, {'term': {'doc_id': '7'}}]
    assert request['source_excludes'] == ['content_vi','content_en','content_zh']


@pytest.mark.parametrize('text,lang', [('SCC is not 1.52', 'en'), ('suy thận', 'vi'), ('我没有发热', 'zh')])
def test_unaffected_queries_do_not_make_analysis_request(text, lang):
    client = Mock()
    client.search.return_value = {'hits': {'hits': []}}
    es.search_bm25(text, lang, client=client)
    client.indices.analyze.assert_not_called()
    assert client.search.call_args.kwargs['query'] == es.bm25_query(text,lang)
