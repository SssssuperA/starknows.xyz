#!/usr/bin/env python3
"""Embed the lightweight report cards into the single-file knowledge base."""

import json
import hashlib
import re
from pathlib import Path
from report_sorting import enrich_dates

root = Path(__file__).resolve().parents[1]
html_path = root / "index.html"
data_path = root / "knowledge" / "app-import.json"

payload = json.loads(data_path.read_text(encoding="utf-8"))["notes"]
review_path = root / "knowledge" / "reviewed-summaries.json"
reviews = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else {}
additional_path = root / 'knowledge/additional-reviewed-summaries.json'
if additional_path.exists():
    reviews.update(json.loads(additional_path.read_text(encoding='utf-8')))
seen = set()
unique = []
for note in payload:
    digest = hashlib.sha256((root / note['source']).read_bytes()).hexdigest()
    if digest in seen:
        continue
    seen.add(digest)
    note['sourceSha256'] = digest
    unique.append(note)
payload = unique
for note in payload:
    review = reviews.get(note["title"])
    note["reviewedSummary"] = review
    if review:
        note["organization"] = review["organization"]
enrich_dates(payload, root)
encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
html = html_path.read_text(encoding="utf-8")
pattern = r"<!-- REPORT_DATA_START -->.*?<!-- REPORT_DATA_END -->"
replacement = f"<!-- REPORT_DATA_START -->{encoded}<!-- REPORT_DATA_END -->"
updated, count = re.subn(pattern, lambda _: replacement, html, count=1, flags=re.S)
if count != 1:
    raise RuntimeError("Report data marker not found exactly once")
version = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]
updated, version_count = re.subn(
    r"const REPORT_VERSION = '[^']+';",
    f"const REPORT_VERSION = '{version}';",
    updated,
    count=1,
)
if version_count != 1:
    raise RuntimeError("Report version marker not found exactly once")
html_path.write_text(updated, encoding="utf-8")
print(f"Embedded {len(payload)} report cards into {html_path.name} (version {version})")
