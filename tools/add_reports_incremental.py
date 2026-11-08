"""Append new inbox PDFs to the index without rebuilding hand-corrected entries.

Usage: python3 tools/add_reports_incremental.py overrides.json
overrides.json maps a filename to manual fields (category, secondary_categories,
organization, year, industry, institutionType, fileType). Text for highlights and
excerpts is taken from knowledge/fulltext (so OCR-completed pages are used).
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_report_library import (ROOT, INBOX, KNOWLEDGE, SUMMARIES, TOPICS, sha256, clean_text,
                                  classify, extract_pdf, infer_org, infer_year, infer_industry,
                                  infer_file_type, infer_institution_type, useful_lines, make_summary)

overrides = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
index_path = KNOWLEDGE / 'report-index.json'
app_path = KNOWLEDGE / 'app-import.json'
index = json.loads(index_path.read_text(encoding='utf-8'))
app = json.loads(app_path.read_text(encoding='utf-8'))
known = {r['sha256'] for r in index['reports']}
known_sources = {r['source'] for r in index['reports']}

added = []
for name, manual in overrides.items():
    path = INBOX / name
    digest = sha256(path)
    source = str(path.relative_to(ROOT))
    if digest in known or source in known_sources:
        print('skip (already indexed):', name)
        continue
    extracted = extract_pdf(path)
    full = json.loads((KNOWLEDGE / 'fulltext' / f'{digest}.json').read_text())
    pages = full['pages']
    sample_ids = sorted(set(range(min(8, len(pages)))) | set(range(max(0, len(pages) - 2), len(pages))))
    page_samples = [{'page': pages[i]['page'], 'text': clean_text(pages[i]['text'])[:9000]} for i in sample_ids]
    sample = clean_text('\n'.join(pages[i]['text'] for i in range(min(8, len(pages)))))
    title = path.stem
    auto_cat, auto_sec = classify(title, sample)
    category = manual.get('category', auto_cat)
    secondary = manual.get('secondary_categories', auto_sec)
    org = manual.get('organization', infer_org(title, sample))
    year = manual.get('year', infer_year(title, sample, extracted['metadata_year']))
    ocr_pages = sum(1 for p in pages if p['method'] != 'pdf-text')
    status = 'ok' if len(sample) >= 200 else 'needs_ocr'
    safe_name = re.sub(r'[^0-9A-Za-z一-鿿._-]+', '_', title)[:100].strip('_')
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    record = {
        'id': f'r-{digest[:12]}', 'title': title, 'category': category, 'secondary_categories': secondary,
        'organization': org, 'year': year, 'pages': len(pages), 'text_status': status, 'source': source,
        'summary': f'knowledge/summaries/{safe_name}.md', 'sha256': digest, 'duplicate_of': None,
        'keywords': list(dict.fromkeys([category, *secondary, org, year])),
        'highlights': useful_lines(sample)[:8], 'page_samples': page_samples, 'indexed_at': now,
        '_sample': sample,
    }
    (ROOT / record['summary']).write_text(make_summary(record), encoding='utf-8')
    index['reports'].append(record)
    body = '\n'.join([
        f"机构：{org}｜年份：{year}｜页数：{len(pages)}", f"来源：{source}", '',
        '首版内容提要：', *[f'• {x}' for x in record['highlights']], '',
        '提示：重要数字和判断请回到原报告核对页码及统计口径。']).strip()
    app['notes'].append({
        'id': record['id'], 'title': title,
        'tags': list(dict.fromkeys([category, org, year] + secondary)),
        'body': body, 'createdAt': now, 'updatedAt': now, 'source': source, 'kind': 'research-report',
        'fileType': manual.get('fileType', infer_file_type(title, category)),
        'institutionType': manual.get('institutionType', infer_institution_type(org, title)),
        'industry': manual.get('industry', infer_industry(title, category)),
        'organization': org, 'year': year, 'pages': len(pages), 'textStatus': status, 'duplicateOf': None,
        'highlights': record['highlights'],
        'excerpt': '\n\n'.join(f"第 {p['page']} 页\n{p['text']}" for p in page_samples if p['text'])[:70000],
        'sourceSha256': digest,
    })
    added.append((title, category, org, year, ocr_pages))

records = index['reports']
index.update(generated_at=datetime.now().astimezone().isoformat(timespec='seconds'), report_count=len(records),
             unique_file_count=len({r['sha256'] for r in records}),
             categories=dict(Counter(r['category'] for r in records).most_common()),
             text_status=dict(Counter(r['text_status'] for r in records).most_common()))
index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
app_path.write_text(json.dumps(app, ensure_ascii=False, indent=2), encoding='utf-8')

# Catalog and topic pages are derived views; regenerate them using the app notes'
# hand-corrected year/organization where they differ from the raw index.
notes = {n['id']: n for n in app['notes']}
def year_of(r): return notes.get(r['id'], r)['year']
def org_of(r): return notes.get(r['id'], r)['organization']
rows = ['# 行业研究报告目录', '', f"共收录 {len(records)} 份 PDF；去重后 {index['unique_file_count']} 份。", '']
for category in index['categories']:
    rows += [f'## {category}', '']
    for r in records:
        if r['category'] == category:
            dup = f"（与 {r['duplicate_of']} 重复）" if r['duplicate_of'] else ''
            rows.append(f"- [{r['title']}](summaries/{Path(r['summary']).name})｜{org_of(r)}｜{year_of(r)}｜{r['pages']} 页{dup}")
    rows.append('')
(KNOWLEDGE / 'catalog.md').write_text('\n'.join(rows), encoding='utf-8')
for category in index['categories']:
    group = [r for r in records if r['category'] == category and not r['duplicate_of']]
    orgs = Counter(org_of(r) for r in group if org_of(r) != '未识别')
    years = Counter(year_of(r) for r in group if year_of(r) != '年份待确认')
    topic_rows = [f'# {category}', '', f'本主题收录 {len(group)} 份非重复报告。', '', '## 资料结构', '',
                  f"- 主要年份：{'、'.join(f'{k}（{v}份）' for k, v in years.most_common(5)) or '未识别'}",
                  f"- 主要机构：{'、'.join(f'{k}（{v}份）' for k, v in orgs.most_common(8)) or '未识别'}",
                  '', '## 报告清单', '']
    for r in group:
        topic_rows.append(f"- [{r['title']}](../summaries/{Path(r['summary']).name})｜{org_of(r)}｜{year_of(r)}｜{r['pages']} 页")
    topic_rows += ['', '## 跨文件使用建议', '', '围绕具体问题检索本主题时，请同时比较报告年份、数据口径、样本范围和发布机构；结论输出应保留原文件及页码。', '']
    safe_topic = re.sub(r'[^0-9A-Za-z一-鿿._-]+', '_', category)
    (TOPICS / f'{safe_topic}.md').write_text('\n'.join(topic_rows), encoding='utf-8')
for a in added:
    print('added:', a)
print(json.dumps({'reports': len(records), 'unique': index['unique_file_count'], 'categories': index['categories']}, ensure_ascii=False))
