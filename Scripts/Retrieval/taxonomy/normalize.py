from __future__ import annotations

import importlib.metadata
import re
import unicodedata
from pathlib import Path

from .io import sha_file
from .models import FoundationError, identifier


class Normalizer:
    def __init__(self):
        import opencc
        self.opencc = opencc.OpenCC('t2s')
        root = Path(opencc.__file__).parent
        files = {str(p.relative_to(root)): sha_file(p) for p in sorted(root.rglob('*'))
                 if p.is_file() and p.suffix in {'.txt', '.json', '.py'}}
        self.profile = {'algorithm': 'NFKC-opencc_t2s-whitespace-lower-v1',
                        'unicode_version': unicodedata.unidata_version,
                        'opencc_version': importlib.metadata.version('opencc-python-reimplemented'),
                        'opencc_config': 't2s', 'opencc_data_code_hashes': files}
        self.profile_id = identifier('normalization', self.profile)

    def views(self, text: str, language: str) -> dict[str, str]:
        if not isinstance(text, str) or language not in {'vi', 'en', 'zh'}:
            raise FoundationError('Normalization requires text and vi/en/zh')
        value = unicodedata.normalize('NFKC', text)
        if language == 'zh':
            value = self.opencc.convert(value)
        value = re.sub(r'\s+', ' ', value).strip()
        return {'case_preserved': value, 'normalized': value.lower()}
