"""BTC-compatible metrics for separately authorized labels; no bundled qrels."""
from collections import defaultdict
from math import ceil

from .export import btc_normalized


def matches_chunk(prediction: str, reference: str) -> bool:
    a=btc_normalized(prediction).split();b=btc_normalized(reference).split()
    if not b:return False
    target=ceil(2*len(b)/5)
    if len(a)<target:return False
    previous=[0]*(len(b)+1)
    for index,token in enumerate(a):
        current=[0]
        for j,other in enumerate(b,1):
            current.append(previous[j-1]+1 if token==other else max(previous[j],current[-1]))
        if current[-1]>=target:return True
        if current[-1]+len(a)-index-1<target:return False
        previous=current
    return False


def prf(true_predictions, predictions, found_references, references):
    precision=true_predictions/predictions if predictions else 0.0
    recall=found_references/references if references else 0.0
    f2=5*precision*recall/(4*precision+recall) if precision or recall else 0.0
    return {'precision':precision,'recall':recall,'f2':f2}


def evaluate(predictions, references):
    """Lists in BTC submission shape; reference chunks are relevant_chunks.

    Zero denominators use zero. Confirm BTC's convention if empty gold exists.
    Predictions for each query must be present, even when lists are empty.
    """
    def mapping(items):
        result={}
        for item in items:
            key=item['id']
            if type(key) is not int or key in result:raise ValueError('Invalid/duplicate query ID')
            result[key]=item
        return result
    pred,ref=mapping(predictions),mapping(references)
    if set(pred)!=set(ref) or not ref:raise ValueError('Query sets must match and be nonempty')
    per_query=[]
    for q,gold in ref.items():
        item=pred[q]
        docs={str(x) for x in item['relevant_docs']};gold_docs={str(x) for x in gold['relevant_docs']}
        tp=len(docs&gold_docs)
        chunk_refs=gold['relevant_chunks'];groups=defaultdict(list)
        for index,chunk in enumerate(chunk_refs):groups[str(chunk['doc_id'])].append((index,chunk['chunk_text']))
        true_chunks=0;found=set()
        for chunk in item['relevant_chunks']:
            matched=[i for i,text in groups[str(chunk['doc_id'])] if matches_chunk(chunk['chunk_text'],text)]
            true_chunks+=bool(matched);found.update(matched)
        per_query.append({'id':q,'documents':prf(tp,len(docs),tp,len(gold_docs)),
                          'chunks':prf(true_chunks,len(item['relevant_chunks']),len(found),len(chunk_refs))})
    macro={level:{metric:sum(row[level][metric] for row in per_query)/len(ref) for metric in ('precision','recall','f2')} for level in ('documents','chunks')}
    return {'macro':macro,'per_query':per_query}
