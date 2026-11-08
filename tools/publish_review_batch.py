"""Validate human-authored readable (format 2) summaries, map by source hash, and persist by title.

Usage: python3 tools/publish_review_batch.py knowledge/review-batch-NN.json

The batch maps a fulltext file-name prefix -> summary. Each summary must follow format 2
(see AGENTS.md): organization, coverage, tldr, conclusion[], sections[{title, points[], pages, kind}],
forecast[], limitations[], glossary[{term, note}]. Validation is shared with apply_readable_batch.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_readable_batch import validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
notes = json.loads((ROOT/'knowledge/app-import.json').read_text(encoding='utf-8'))['notes']
destination = ROOT/'knowledge/additional-reviewed-summaries.json'
reviews = json.loads(destination.read_text(encoding='utf-8'))
batch = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
for prefix, review in batch.items():
    sources = list((ROOT/'knowledge/fulltext').glob(prefix+'*.json'))
    assert len(sources) == 1, prefix
    source = json.loads(sources[0].read_text(encoding='utf-8'))
    digest = source['sha256']
    matches = [n for n in notes if n['id'] == 'r-'+digest[:12]]
    assert matches, prefix
    for field in ['organization', 'coverage']:
        assert isinstance(review.get(field), str) and review[field].strip(), (prefix, field)
    validate(prefix, review)
    review['sourceSha256'] = digest
    review['pageCount'] = len(source['pages'])
    review['format'] = 2
    for note in matches:
        reviews[note['title']] = review
destination.write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Published {len(batch)} reviewed sources; {len(reviews)} title mappings')
