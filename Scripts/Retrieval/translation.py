"""Optional local NLLB query translation. Never transforms source chunks."""
from __future__ import annotations

import json
import os
import re
from datetime import date
from itertools import islice
from pathlib import Path

from .utils import sha_bytes, sha_file


def validate_provenance(value):
    required=('model_id','revision','license','parameters','release_date','open_weights')
    if not isinstance(value,dict) or any(k not in value for k in required):
        raise ValueError('Translation model manifest incomplete')
    if any(not isinstance(value[k],str) or not value[k].strip() for k in ('model_id','revision','license','release_date')):
        raise ValueError('Model identity/revision/license/date must be nonempty text')
    if not re.fullmatch(r'[0-9a-f]{40}',value['revision']):
        raise ValueError('Model revision must be an immutable 40-character commit hash')
    if value['open_weights'] is not True or type(value['parameters']) is not int or not 0<value['parameters']<=15_000_000_000 or date.fromisoformat(value['release_date'])>=date(2026,8,1):
        raise ValueError('Translation model violates competition eligibility manifest')
    return value


class LocalNllbTranslator:
    """A separately provisioned, checksum-verified HF model; optional GPU/CPU."""
    def __init__(self, manifest_path: Path, *, device='cpu'):
        manifest=json.loads(manifest_path.read_text())
        self.provenance=validate_provenance(manifest['provenance'])
        self.directory=Path(manifest['local_directory']).resolve()
        files=manifest.get('files',{})
        if not files or not any(name.endswith('.safetensors') for name in files):
            raise ValueError('Translation assets need checksums and safetensors weights')
        for name,digest in files.items():
            path=(self.directory/name).resolve()
            if self.directory not in path.parents or sha_file(path)!=digest:
                raise ValueError('Translation asset path/checksum mismatch')
        actual={str(p.relative_to(self.directory)) for p in self.directory.rglob('*') if p.is_file() and not str(p.relative_to(self.directory)).startswith('.cache/')}
        if actual != set(files):
            raise ValueError('Every model/tokenizer file must be in checksum manifest')
        # Dependencies loaded here, not in BM25 search/index processes.
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        self.torch=torch
        self.tokenizer=AutoTokenizer.from_pretrained(self.directory,src_lang='vie_Latn',local_files_only=True,trust_remote_code=False)
        self.model=AutoModelForSeq2SeqLM.from_pretrained(self.directory,local_files_only=True,trust_remote_code=False,use_safetensors=True).to(device).eval()
        if sum(p.numel() for p in self.model.parameters())>15_000_000_000:
            raise ValueError('Loaded model exceeds competition parameter ceiling')
        self.device=device

    def translate(self,texts):
        inputs=self.tokenizer(texts,return_tensors='pt',padding=True,truncation=False).to(self.device)
        if inputs['input_ids'].shape[1]>512:
            raise ValueError('Query exceeds NLLB 512-token adapter budget; no silent truncation')
        output={}
        with self.torch.inference_mode():
            for language,code in [('en','eng_Latn'),('zh','zho_Hans')]:
                bos=self.tokenizer.convert_tokens_to_ids(code)
                if bos == self.tokenizer.unk_token_id: raise ValueError('Unknown target language token')
                tokens=self.model.generate(**inputs,forced_bos_token_id=bos,max_new_tokens=512,num_beams=2,do_sample=False)
                output[language]=self.tokenizer.batch_decode(tokens,skip_special_tokens=True)
        return [{language:output[language][i] for language in ('en','zh')} for i in range(len(texts))]


class LocalM2MTranslator:
    """A separately provisioned, checksum-verified M2M100/MultiMed-ST directional model."""
    def __init__(self, manifest_path: Path, *, device=None):
        manifest = json.loads(manifest_path.read_text())
        self.provenance = validate_provenance(manifest['provenance'])
        self.directory = Path(manifest['local_directory']).resolve()
        self.target_language = manifest.get('target_language', 'en')
        files = manifest.get('files', {})
        if not files or not any(name.endswith('.safetensors') for name in files):
            raise ValueError('Translation assets need checksums and safetensors weights')
        for name, digest in files.items():
            path = (self.directory / name).resolve()
            if self.directory not in path.parents or sha_file(path) != digest:
                raise ValueError('Translation asset path/checksum mismatch')
        actual = {str(p.relative_to(self.directory)) for p in self.directory.rglob('*') if p.is_file() and not str(p.relative_to(self.directory)).startswith('.cache/')}
        if actual != set(files):
            raise ValueError('Every model/tokenizer file must be in checksum manifest')
        import torch
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
        self.torch = torch
        if device is None:
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.device = device
        dtype = torch.float16 if (device == 'cuda') else torch.float32
        self.tokenizer = M2M100Tokenizer.from_pretrained(
            self.directory, src_lang='vi', local_files_only=True
        )
        self.model = M2M100ForConditionalGeneration.from_pretrained(
            self.directory, local_files_only=True, use_safetensors=True, torch_dtype=dtype
        ).to(device).eval()
        if sum(p.numel() for p in self.model.parameters()) > 15_000_000_000:
            raise ValueError('Loaded model exceeds competition parameter ceiling')

    def translate(self, texts: list[str]) -> list[str]:
        inputs = self.tokenizer(texts, return_tensors='pt', padding=True, truncation=False).to(self.device)
        if inputs['input_ids'].shape[1] > 512:
            raise ValueError('Query exceeds 512-token adapter budget; no silent truncation')
        bos = self.tokenizer.get_lang_id(self.target_language)
        with self.torch.inference_mode():
            tokens = self.model.generate(
                **inputs,
                forced_bos_token_id=bos,
                max_new_tokens=512,
                num_beams=2,
                do_sample=False
            )
        return self.tokenizer.batch_decode(tokens, skip_special_tokens=True)


class MultiMedCompositeTranslator:
    """Composite translator coordinating two directional MultiMed-ST models (VI->EN, VI->ZH)."""
    def __init__(self, en_translator: LocalM2MTranslator, zh_translator: LocalM2MTranslator):
        self.en_translator = en_translator
        self.zh_translator = zh_translator
        self.provenance = validate_provenance(en_translator.provenance)

    def translate(self, texts: list[str]) -> list[dict[str, str]]:
        en_res = self.en_translator.translate(texts)
        zh_res = self.zh_translator.translate(texts)
        return [{'en': e, 'zh': z} for e, z in zip(en_res, zh_res)]


def write_translation_cache(queries, translator, output: Path, *, batch_size=8):
    validate_provenance(translator.provenance)
    if batch_size<1 or output.exists(): raise ValueError('Invalid batch size or output already exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix(output.suffix+'.partial')
    seen=set();count=0;iterator=iter(queries)
    with temporary.open('w',encoding='utf-8') as f:
        while batch:=list(islice(iterator,batch_size)):
            unique=[]
            for q in batch:
                key=sha_bytes(q['query'].encode())
                if key not in seen:
                    seen.add(key);unique.append(q)
            if not unique:continue
            translated=translator.translate([q['query'] for q in unique])
            if len(translated)!=len(unique): raise ValueError('Translation batch cardinality mismatch')
            for q,texts in zip(unique,translated):
                if any(not isinstance(texts.get(l),str) or (q['query'].strip() and not texts[l].strip()) for l in ('en','zh')):
                    raise ValueError('Translation returned invalid/empty content')
                json.dump({'source_query':q['query'],'query_sha256':sha_bytes(q['query'].encode()),'translations':texts,'provenance':translator.provenance},f,ensure_ascii=False)
                f.write('\n');count+=1
        f.flush();os.fsync(f.fileno())
    os.replace(temporary,output)
    return count
