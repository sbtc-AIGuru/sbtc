"""Measure the existing baseline and save real source examples, read-only inputs."""
from array import array
from collections import Counter,defaultdict
import csv,hashlib,json,re,sys,time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path.cwd()))
from sbtc.Scripts.Clawler.verbatim import clean_with_report
from sbtc.Scripts.Preprocess.chunking import extract_paragraphs,HEADING_RE,CLAUSE_END

ROOT=Path('sbtc/Scripts/Preprocess/research/format-audit-20261013')
ROWS={int(x['id']):x for x in csv.DictReader((ROOT/'test_rows.csv').open())}
SECTIONS=re.compile(r'(?im)^(?:background|objectives?|methods?|results?|conclusions?|purpose|design|setting|participants|interventions|outcomes|aims?|findings|interpretation)\s*:')
NAV=re.compile(r'跳转到：|相关条目|更多医学百科条目|原文\s*→|【医生信息】|订阅讨论RSS|试试症状自查工具')
NUM=re.compile(r'\d+[、,，:：]\d+(?:\s*(?:个月|月|岁|天|mg|ml|mmol|g|%))?')
PRESPEC={7156587,7363807,6306459,4265827,4271202,4050109,752978,2335124,1067218,2531165,2996442,236542}
groups={};allc=Counter();risks=Counter();cases=defaultdict(list);caseids=defaultdict(set);manual=[]
def percentile(a):
 if not a:return {}
 a=np.asarray(a);return {'count':len(a),'mean':float(a.mean()),'p50':float(np.percentile(a,50)),'p95':float(np.percentile(a,95)),'p99':float(np.percentile(a,99)),'min':int(a.min()),'max':int(a.max())}
def record_case(kind,raw,o,src,c,detail=None):
 risks[kind]+=1
 if raw['id'] in caseids[kind] or len(cases[kind])>=18:return
 caseids[kind].add(raw['id']);e=c['end_char'];s=c['start_char']
 cs=o['children'];order=c['chunk_order'];nxt=cs[order+1] if order+1<len(cs) else None
 cases[kind].append({'kind':kind,'doc_id':raw['id'],'url':raw['url'],'input_line':o['input_line'],'chunk_order':order,'unit_count':c['unit_count'],'doc_units':o.get('source_units'),'doc_type':o.get('doc_type'),'parent_id':c['parent_id'],'start_char':s,'end_char':e,'boundary_type':c.get('boundary_type'),'short_chunk_reason':c.get('short_chunk_reason'),'overlap_units':c.get('overlap_units'),'detail':detail,'chunk_head':c['chunk_text'][:180],'chunk_tail':c['chunk_text'][-240:],'source_at_boundary':src[max(0,e-130):e]+' ⟦END⟧ '+src[e:e+160],'next_chunk_start':nxt['start_char'] if nxt else None,'next_chunk_head':nxt['chunk_text'][:240] if nxt else None,'baseline_file':str(ROOT/'baseline_chunks'/f'part-{(o["input_line"]-1)//1000:06d}.jsonl'),'baseline_file_line':(o['input_line']-1)%1000+1})

def output_lines():
 for p in sorted((ROOT/'baseline_chunks').glob('part-*.jsonl')):
  yield from p.open('r',encoding='utf-8')

start=time.time()
for n,(line,oline) in enumerate(zip(Path('data_final/test_20k.jsonl').open(),output_lines()),1):
 raw=json.loads(line);o=json.loads(oline);allc['documents']+=1
 assert raw['id']==o['doc_id'] and n==o['input_line']
 if o['status']!='ok':allc['skipped']+=1;continue
 src,cleaning=clean_with_report(raw['text']);meta=ROWS[raw['id']];fam=meta['url_family']
 if fam not in groups:groups[fam]={'documents':0,'chunks':0,'parents':0,'doc_units':array('I'),'chunk_units':array('I'),'sizes':Counter(),'short_reasons':Counter(),'boundaries':Counter(),'risks':Counter(),'eligible_transitions':0,'overlap_30_50':0,'coverage_total':0,'coverage_covered':0}
 g=groups[fam];g['documents']+=1;g['parents']+=len(o['parents']);g['doc_units'].append(o['source_units']);g['coverage_total']+=o['coverage']['non_whitespace_total'];g['coverage_covered']+=o['coverage']['non_whitespace_covered']
 label_positions=[m.start() for m in SECTIONS.finditer(src)];pubmed=fam=='pubmed_abstract'
 if pubmed and len(label_positions)>=2:allc['pubmed_structured_documents']+=1
 if pubmed and int(meta['cjk_chars'])>=20:allc['pubmed_with_CJK_20plus']+=1
 paras=extract_paragraphs(src);repeated=[x for x,cnt in Counter(p.text.strip() for p in paras if len(p.text.strip())>=100).items() if cnt>=2]
 if repeated:
  allc['documents_repeated_100char_paragraph']+=1
  record_case('repeated_source_paragraph',raw,o,src,o['children'][0],{'repeated_prefix':repeated[0][:220],'occurrences':src.count(repeated[0])})
 numeric_headings=[p for p in paras[1:] if p.role=='heading' and re.match(r'^\d+[.、．)]',p.text) and re.search(r'\d.*(?:%|mg|ml|mmol|kg|g/|℃)',p.text,re.I)]
 if numeric_headings:record_case('possible_dose_as_heading',raw,o,src,o['children'][0],{'paragraph':numeric_headings[0].text,'offset':numeric_headings[0].start})
 parents={p['parent_id']:p for p in o['parents']};seenparents=set()
 # Parenthesis depth at all child end offsets, in a single source pass.
 ends={c['end_char'] for c in o['children']};depth=0;depths={}
 for idx,ch in enumerate(src,1):
  if ch in '(（[':depth+=1
  elif ch in ')）]':depth=max(depth-1,0)
  if idx in ends:depths[idx]=depth
 for c in o['children']:
  u=c['unit_count'];g['chunks']+=1;g['chunk_units'].append(u);bucket='0-49' if u<50 else '50-99' if u<100 else '100-149' if u<150 else '150-219' if u<220 else '220-300' if u<=300 else '>300';g['sizes'][bucket]+=1
  g['short_reasons'][c.get('short_chunk_reason') or 'none']+=1;g['boundaries'][c.get('boundary_type') or 'unknown']+=1
  if c['parent_id'] in seenparents:g['eligible_transitions']+=1;g['overlap_30_50']+=30<=c['overlap_units']<=50
  seenparents.add(c['parent_id']);e=c['end_char'];s=c['start_char'];has_more=bool(src[e:].strip())
  if u>300:record_case('oversized',raw,o,src,c)
  if u<50 and o['source_units']>=150:record_case('tiny_chunk_in_long_document',raw,o,src,c)
  if u<10 and o['source_units']>=150:record_case('tiny_1_to_9_units',raw,o,src,c)
  nav=NAV.findall(c['chunk_text'])
  if nav:
   g['risks']['navigation_or_doctor_info_chunks']+=1;record_case('indexed_navigation_or_bio',raw,o,src,c,{'markers':nav[:4]})
  nlabels=sum(s<=p<e for p in label_positions)
  if pubmed and nlabels>=2:
   g['risks']['pubmed_multiple_section_labels']+=1;record_case('pubmed_multiple_section_labels',raw,o,src,c,{'labels':SECTIONS.findall(c['chunk_text'])})
  if has_more and src[e-1:e] in CLAUSE_END:
   allc['nonfinal_clause_delimiter_end']+=1;g['risks']['nonfinal_clause_delimiter_end']+=1
   if depths.get(e,0)>0:record_case('clause_boundary_in_parentheses',raw,o,src,c,{'depth':depths[e]})
   if pubmed:record_case('pubmed_clause_boundary',raw,o,src,c)
  winstart=max(0,e-18)
  for m in NUM.finditer(src[winstart:e+25]):
   a=winstart+m.start();b=winstart+m.end()
   if a<e<b:
    g['risks']['numeric_expression_cut']+=1;record_case('numeric_expression_cut',raw,o,src,c,{'expression':m.group(0),'expr_start':a,'expr_end':b});break
  if has_more and c['end_char']==parents[c['parent_id']]['end_char'] and c['chunk_text'].strip().endswith(':'):
   record_case('parent_ends_at_leadin_colon',raw,o,src,c)
 if raw['id'] in PRESPEC:
  manual.append({'doc_id':raw['id'],'url':raw['url'],'input_line':n,'family':fam,'raw_chars':len(raw['text']),'source_units':o['source_units'],'doc_type':o['doc_type'],'source':src if len(src)<12000 else src[:6500]+'\n⟦excerpt omitted⟧\n'+src[-2000:],'excluded_spans':o['excluded_spans'],'parents':o['parents'],'children':[{**c,'chunk_text':c['chunk_text'] if len(c['chunk_text'])<2000 else c['chunk_text'][:1000]+'⟦excerpt omitted⟧'+c['chunk_text'][-450:]} for c in o['children']]})
 if n%5000==0:print('review',n,round(time.time()-start,1),flush=True)

report={'input':'data_final/test_20k.jsonl','seconds':round(time.time()-start,3),'counters':dict(allc),'risk_flags_not_ground_truth':dict(risks),'groups':{fam:{k:(dict(v) if isinstance(v,Counter) else v) for k,v in g.items() if k not in {'doc_units','chunk_units'}}|{'doc_units':percentile(g['doc_units']),'chunk_units':percentile(g['chunk_units'])} for fam,g in groups.items()}}
(ROOT/'chunk_metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
(ROOT/'review_cases.json').write_text(json.dumps(dict(cases),ensure_ascii=False,indent=2)+'\n')
(ROOT/'manual_format_cases.json').write_text(json.dumps(manual,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'counters':report['counters'],'risks':report['risk_flags_not_ground_truth'],'seconds':report['seconds']},ensure_ascii=False))
