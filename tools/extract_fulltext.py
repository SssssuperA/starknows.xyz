"""Extract every PDF page, preserving source hashes and a resumable manifest."""
import json
import logging
from pathlib import Path
from pypdf import PdfReader
from build_report_library import ROOT, sha256

logging.disable(logging.CRITICAL)
out = ROOT / 'knowledge' / 'fulltext'
out.mkdir(parents=True, exist_ok=True)
manifest = []
for file in sorted((ROOT / 'reports/inbox').glob('*.pdf')):
    digest = sha256(file)
    target = out / (digest + '.json')
    if target.exists() and target.stat().st_size:
        item = json.loads(target.read_text())
    else:
        reader = PdfReader(file, strict=False)
        pages = []
        for i, page in enumerate(reader.pages):
            try:
                text = page.extract_text() or ''
                error = None
            except Exception as exc:
                text, error = '', str(exc)
            pages.append({'page': i+1, 'text': text, 'method': 'pdf-text', 'error': error})
        item = {'sha256': digest, 'source': str(file.relative_to(ROOT)), 'pages': pages}
        target.write_text(json.dumps(item, ensure_ascii=True), encoding='utf-8')
    manifest.append({'title': file.stem, 'sha256': digest, 'pages': len(item['pages']),
                     'characters': sum(len(p['text']) for p in item['pages']),
                     'sparse_pages': [p['page'] for p in item['pages'] if len(p['text'].strip()) < 80]})
    print(len(manifest), file.stem, manifest[-1]['pages'], manifest[-1]['characters'], flush=True)
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
(out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
