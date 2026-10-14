"""Read-only corpus/profile audit; does not alter input records."""
import argparse
from array import array
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path.cwd()))
from sbtc.Scripts.Preprocess.build_test_20k import classify_record

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
VI = re.compile(r"[ăĂđĐơƠưƯ\u1ea0-\u1ef9]")
SECTIONS = re.compile(r"(?im)^(?:background|objectives?|methods?|results?|conclusions?|purpose|design|setting|participants|interventions|outcomes|aims?|findings|interpretation)\s*:")
QA = re.compile(r"健康咨询描述|问题描述|病情描述|医生回答|医生回复|医生解答|指导意见|病情分析")

def stats(values):
    a = np.asarray(values, dtype=np.int64)
    if not len(a): return {}
    qs = np.percentile(a, [10,25,50,75,90,95,99])
    return dict(zip(['p10','p25','p50','p75','p90','p95','p99'], map(float,qs)), count=len(a), mean=float(a.mean()), min=int(a.min()), max=int(a.max()))

def family(domain,path):
    if domain == 'pubmed.ncbi.nlm.nih.gov': return 'pubmed_abstract'
    if domain in {'ask.39.net','www.120ask.com','120ask.com'}: return 'medical_qa'
    if domain == 'nhathuoclongchau.com.vn': return 'longchau_article' if path.startswith('/bai-viet/') else 'longchau_other'
    if domain.endswith('vinmec.com'): return 'vinmec_article'
    if domain == 'jbk.39.net': return 'disease_symptom_catalogue'
    if domain.endswith('a-hospital.com') or domain.endswith('zhongyibaodian.net') or domain.endswith('wujue.com'): return 'medical_encyclopedia'
    if domain in {'zysjonline.com','www.zysj.com.cn','zysj.com.cn','www.zydcd.com','zydcd.com'}: return 'tcm_book_dictionary'
    if domain.endswith('baidu.com'): return 'baidu_encyclopedia'
    if domain.endswith('iiyi.com'): return 'medical_forum'
    if domain.endswith('.cn') or domain.endswith('cnkang.com') or domain.endswith('youlai.cn'): return 'zh_health_article'
    if domain in {'medlatec.vn','bachmai.gov.vn','benhvien108.vn'}: return 'hospital_article'
    return 'other_health_news'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('input');ap.add_argument('output');ap.add_argument('--sample',action='store_true');args=ap.parse_args()
    p=Path(args.input);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    initial=p.stat();start=time.time();digest=hashlib.sha256()
    tab=pq.read_table('newcorpus/links_corpus_vi_en_zh.parquet',columns=['id','url'])
    official=dict(zip(tab['id'].to_pylist(),tab['url'].to_pylist()))
    domains={}; groups={}; languages={}; counters=Counter();families=Counter();patterns=defaultdict(Counter);signals=Counter();mismatch_examples=[];max_docs=[];seen=set()
    def slot(store,key):
        if key not in store:store[key]={'records':0,'success':0,'failed':0,'chars':array('I'),'ws_tokens':array('I'),'cjk_chars':array('I')}
        return store[key]
    writer=None
    if args.sample:
        fcsv=(out/'test_rows.csv').open('w',newline='',encoding='utf-8');writer=csv.writer(fcsv)
        writer.writerow(['input_line','id','domain','source_group','source_language_sampler','language_proxy','language_basis','url_family','success','raw_chars','ws_tokens','cjk_chars','vi_marker_chars','pubmed_sections','url'])
    with p.open('rb') as f:
        for n,line in enumerate(f,1):
            digest.update(line)
            try:r=json.loads(line)
            except Exception:counters['json_errors']+=1;continue
            rid=r.get('id');text=r.get('text') or '';success=r.get('success') is True;url=r.get('url') or '';parts=urlsplit(url);domain=parts.hostname or ''
            source_lang,group,_,_=classify_record(url,text)
            chars=len(text);ws=len(text.split());cjk=len(CJK.findall(text));vi=len(VI.findall(text));fam=family(domain,parts.path)
            if not text.strip():lang='empty';basis='empty'
            elif cjk>=20 and cjk/max(chars,1)>=0.10:lang='ZH';basis='CJK-script'
            elif vi>=3:lang='VI';basis='Vietnamese-markers'
            elif domain=='pubmed.ncbi.nlm.nih.gov':lang='EN';basis='PubMed-source-no-CJK'
            elif source_lang=='ZH':lang='ZH';basis='source-short-ambiguous'
            elif domain.endswith('.vn') or domain in {'hellobacsi.com','youmed.vn'}:lang='VI';basis='source-no-VI-markers'
            else:lang='unknown';basis='unknown-Latin'
            counters['records']+=1;counters['success' if success else 'failed']+=1;counters['empty_success']+=success and not text.strip()
            counters['duplicate_id']+=rid in seen;seen.add(rid)
            counters['id_not_in_manifest']+=rid not in official
            counters['url_mismatch']+=rid in official and official[rid]!=url
            counters['replacement_documents']+='\ufffd' in text;counters['replacement_chars']+=text.count('\ufffd')
            if lang in {'VI','ZH','EN'} and source_lang!=lang:
                counters['sampler_language_disagreement']+=1
                if len(mismatch_examples)<50:mismatch_examples.append({'id':rid,'input_line':n,'url':url,'sampler_language':source_lang,'proxy_language':lang,'chars':chars,'cjk_chars':cjk,'snippet':text[:250]})
            for store,key in ((domains,domain),(groups,group),(languages,lang)):
                x=slot(store,key);x['records']+=1;x['success']+=success;x['failed']+=not success
                if success:x['chars'].append(chars);x['ws_tokens'].append(ws);x['cjk_chars'].append(cjk)
            families[fam]+=1
            prefix=parts.path.strip('/').split('/')[0] if parts.path.strip('/') else '/'
            if prefix.isdigit():prefix='<numeric-id>'
            elif len(prefix)>35:prefix='<article-slug>'
            patterns[domain][prefix]+=1
            sections=len(SECTIONS.findall(text)) if args.sample else 0
            if args.sample:
                signals['pubmed_with_labeled_sections']+=domain=='pubmed.ncbi.nlm.nih.gov' and sections>=2
                signals['qa_markers']+=bool(QA.search(text));signals['doctor_info']+='医生信息' in text
                signals['toc_literal']+=bool(re.search(r'目录|Mục lục|Table of contents',text,re.I))
                signals['pipe_lines']+=bool(re.search(r'(?m)^.*\|.*\|',text))
                signals['broken_link']+='](' in text
                writer.writerow([n,rid,domain,group,source_lang,lang,basis,fam,success,chars,ws,cjk,vi,sections,url])
            if success and (len(max_docs)<12 or chars>max_docs[-1]['chars']):
                max_docs.append({'id':rid,'input_line':n,'url':url,'chars':chars,'language_proxy':lang});max_docs.sort(key=lambda d:d['chars'],reverse=True);max_docs=max_docs[:12]
            if n%200000==0:print('profile',p.name,n,'seconds',round(time.time()-start,1),flush=True)
    if writer:fcsv.close()
    def finalize(store):
        return {key:{k:v for k,v in x.items() if k not in {'chars','ws_tokens','cjk_chars'}}|{'char_length':stats(x['chars']),'whitespace_tokens':stats(x['ws_tokens']),'cjk_chars':stats(x['cjk_chars']),'char_bins':dict(Counter('0' if v==0 else '1-299' if v<300 else '300-799' if v<800 else '800-2499' if v<2500 else '2500-5999' if v<6000 else '6000+' for v in x['chars']))} for key,x in store.items()}
    final=p.stat()
    report={'input':str(p.resolve()),'sha256':digest.hexdigest(),'bytes':initial.st_size,'input_stat_unchanged':(initial.st_size,initial.st_mtime_ns)==(final.st_size,final.st_mtime_ns),'seconds':round(time.time()-start,3),'language_method':'proxy only: >=20 CJK and CJK/raw chars>=0.10; >=3 Vietnamese marker chars; otherwise source prior; never ground truth','counters':dict(counters),'domains':finalize(domains),'source_groups_sampler':finalize(groups),'language_proxy':finalize(languages),'url_families':dict(families),'url_prefixes':{d:c.most_common(8) for d,c in patterns.items()},'format_signals_test_only':dict(signals),'sampler_language_disagreement_examples':mismatch_examples,'longest_documents':max_docs}
    (out/('test_profile.json' if args.sample else 'corpus_profile.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'file':str(p),'counters':report['counters'],'language_proxy':{k:v['records'] for k,v in report['language_proxy'].items()},'seconds':report['seconds']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
