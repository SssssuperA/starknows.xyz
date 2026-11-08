"""Fill sparse PDF pages locally via Apple Vision; preserve both extraction layers."""
import json
import subprocess
import sys
from pathlib import Path
from build_report_library import ROOT

folder = ROOT / 'knowledge/fulltext'
for target in sorted(folder.glob('*.json')):
    if target.name == 'manifest.json':
        continue
    if len(sys.argv) > 1 and not target.stem.startswith(sys.argv[1]):
        continue
    item = json.loads(target.read_text())
    sparse = [p['page'] for p in item['pages'] if '--all' in sys.argv or (len(p['text'].strip()) < 80 and p['method'] == 'pdf-text')]
    if not sparse:
        continue
    proc = subprocess.Popen(['/private/tmp/kb-ocr-pdf', str(ROOT/item['source']), ','.join(map(str,sparse))], stdout=subprocess.PIPE, text=True)
    for line in proc.stdout:
        page = json.loads(line)
        old = item['pages'][page['page']-1]
        page['pdf_text'] = old['text']
        page['error'] = None
        item['pages'][page['page']-1] = page
        target.write_text(json.dumps(item,ensure_ascii=True),encoding='utf-8')
        print(Path(item['source']).name, page['page'], len(page['text']), flush=True)
    proc.wait()
