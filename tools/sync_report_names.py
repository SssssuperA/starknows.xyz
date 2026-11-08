"""Refresh renamed sources by content identity, preserving summaries and years."""
import hashlib
import json
from pathlib import Path
from build_report_library import infer_org, infer_institution_type

ROOT = Path(__file__).resolve().parents[1]
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

index_path = ROOT / 'knowledge/report-index.json'
index = read(index_path)
by_source = {r['source']: r['sha256'] for r in index['reports']}
current = {}
for p in sorted((ROOT / 'reports/inbox').glob('*.pdf')):
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    current.setdefault(digest, []).append(p.relative_to(ROOT).as_posix())

app_path = ROOT / 'knowledge/app-import.json'
app = read(app_path)
review_paths = [ROOT / 'knowledge' / name for name in
                ['reviewed-summaries.json', 'additional-reviewed-summaries.json']]
reviews = {p: read(p) for p in review_paths if p.exists()}
changed = []
# Validate before changing any persisted data; no fuzzy filename matches.
for note in app['notes']:
    digest = note.get('sourceSha256') or by_source[note['source']]
    if digest not in current:
        raise RuntimeError(f"Source removed or changed; review required: {note['title']}")
for note in app['notes']:
    old_title, old_source = note['title'], note['source']
    digest = note.get('sourceSha256') or by_source[old_source]
    paths = current[digest]
    source = old_source if old_source in paths else paths[0]
    title = Path(source).stem
    note['sourceSha256'] = digest
    if source == old_source:
        continue
    note.update(title=title, source=source)
    # Explicit new filename attribution takes priority; retain existing if unknown.
    organization = infer_org(title, '')
    if organization != '未识别':
        note['organization'] = organization
        note['institutionType'] = infer_institution_type(organization, title)
    for data in reviews.values():
        if old_title in data:
            data[title] = data.pop(old_title)
            if organization != '未识别':
                data[title]['organization'] = organization
    for record in index['reports']:
        if record['source'] == old_source:
            record.update(source=source, title=title, organization=note['organization'])
    full_path = ROOT / 'knowledge/fulltext' / (digest + '.json')
    if full_path.exists():
        full = read(full_path)
        full['source'] = source
        write(full_path, full)
    changed.append({'old':old_title, 'new':title})
write(app_path, app)
write(index_path, index)
for p, data in reviews.items():
    write(p, data)
write(ROOT / 'knowledge/filename-refresh.json', changed)
print(json.dumps({'renamed':len(changed),'unique_current':len(current),'changes':changed}, ensure_ascii=False, indent=2))
