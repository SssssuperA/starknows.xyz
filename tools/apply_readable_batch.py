"""Merge hand-rewritten "readable" (format 2) summaries into the review stores.

Usage:
  python3 tools/apply_readable_batch.py status            # progress: how many summaries are format 2
  python3 tools/apply_readable_batch.py dump N [OFFSET]   # print next N not-yet-rewritten summaries
  python3 tools/apply_readable_batch.py apply batch.json  # validate + merge a rewritten batch

A batch maps report title -> {tldr, conclusion[], sections[{title, points[], pages, kind}],
forecast[], limitations[], glossary[{term, note}]}. organization / coverage / sourceSha256 /
pageCount are carried over from the existing entry unless the batch supplies them.
Rewrites restructure an already hand-written summary; they must not add facts that were not
verified against the source (see AGENTS.md).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORES = [ROOT / 'knowledge/reviewed-summaries.json', ROOT / 'knowledge/additional-reviewed-summaries.json']
KINDS = {'已发生数据', '预测', '观点判断', '建议', '案例', '方法口径', '政策梳理'}


def load():
    return [(p, json.loads(p.read_text(encoding='utf-8'))) for p in STORES]


def displayed_titles():
    notes = json.loads((ROOT / 'knowledge/app-import.json').read_text(encoding='utf-8'))['notes']
    seen, order = set(), []
    for n in sorted(notes, key=lambda n: (-(int(n['year']) if str(n.get('year', '')).isdigit() else 0), n['title'])):
        if n['id'] in seen:
            continue
        seen.add(n['id'])
        order.append(n['title'])
    return order


def validate(title, v):
    def need(cond, msg):
        if not cond:
            raise SystemExit(f'[{title}] {msg}')
    need(isinstance(v.get('tldr'), str) and 10 <= len(v['tldr']) <= 160, 'tldr must be 10-160 chars')
    for f, lo in [('conclusion', 2), ('forecast', 1), ('limitations', 2), ('glossary', 1)]:
        need(isinstance(v.get(f), list) and len(v[f]) >= lo, f'{f} must be a list with >= {lo} items')
    need(all(isinstance(x, str) and x.strip() for x in v['conclusion'] + v['forecast'] + v['limitations']), 'empty bullet')
    need(isinstance(v.get('sections'), list) and 2 <= len(v['sections']) <= 9, 'sections must be 2-9')
    for s in v['sections']:
        need(all(s.get(k) for k in ['title', 'points', 'pages', 'kind']), f'section fields missing: {s.get("title")}')
        need(isinstance(s['points'], list) and len(s['points']) >= 2, f'section needs >=2 points: {s["title"]}')
        need(all(k in KINDS for k in s['kind'].split('、')), f'bad kind {s["kind"]!r}')
        need(not str(s['pages']).startswith('第') and not str(s['pages']).endswith('页'), f'pages should be bare: {s["pages"]}')
    for g in v['glossary']:
        need(g.get('term') and g.get('note'), 'glossary items need term+note')
    need(json.dumps(v, ensure_ascii=False).count('**') % 2 == 0, 'unbalanced ** bold markers (write literal asterisks as ＊)')


def main():
    cmd = sys.argv[1]
    stores = load()
    merged = {t: v for _, d in stores for t, v in d.items()}
    order = displayed_titles()
    todo = [t for t in order if merged.get(t, {}).get('format') != 2]
    if cmd == 'status':
        print(f'format-2: {len(order) - len(todo)} / {len(order)} displayed summaries')
        return
    if cmd == 'dump':
        n = int(sys.argv[2]); off = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        for t in todo[off:off + n]:
            v = {k: merged[t][k] for k in merged[t] if k not in ('sourceSha256', 'pageCount')}
            print('#####', t)
            print(json.dumps(v, ensure_ascii=False, indent=0))
        return
    if cmd == 'apply':
        batch = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
        for title, v in batch.items():
            if title not in merged:
                raise SystemExit(f'unknown title: {title}')
            validate(title, v)
        for path, data in stores:
            changed = False
            for title, v in batch.items():
                if title in data:
                    old = data[title]
                    new = {'organization': old['organization'], 'coverage': old.get('coverage')}
                    new.update(v)
                    for k in ('sourceSha256', 'pageCount'):
                        if k in old:
                            new[k] = old[k]
                    new['format'] = 2
                    data[title] = new
                    changed = True
            if changed:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'applied {len(batch)}; remaining {len(todo) - len([t for t in batch if t in todo])}')


if __name__ == '__main__':
    main()
