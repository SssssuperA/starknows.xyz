#!/usr/bin/env python3
"""Build the free static site; preserve local PDFs and omit assets over 25 MiB.

The output is outside the source workspace by default. All report/summary hashes
are verified before an existing generated build is replaced. No cloud API calls.
"""
import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from apply_readable_batch import validate
from report_sorting import enrich_dates

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 25 * 1024 * 1024
DATA_PATTERN = r"<!-- REPORT_DATA_START -->(.*?)<!-- REPORT_DATA_END -->"
LOCAL_MARKER = '<meta name="starknows-deployment" content="local" />'
CLOUD_MARKER = '<meta name="starknows-deployment" content="cloudflare-static" />'
TEMP_ROOT = Path("/tmp") if Path("/tmp").is_dir() else Path(tempfile.gettempdir())
DEFAULT_OUTPUT = TEMP_ROOT / "starknows-cloudflare-build"
BUILD_MARKER = ".starknows-generated-build"
MESSAGE = "因文件过大，无云端存储，请回到本地源文件"
# Five already-reviewed legacy entries predate provenance fields on summaries.
# Only these fixed IDs may use their matching fulltext record as provenance.
LEGACY_REVIEW_IDS = {
    "r-dfc0316bcf1c", "r-ca85c060278b", "r-29c54977b7ec",
    "r-ce64c7d8f7ef", "r-7878647e2ed4",
}


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(root):
    html = (root / "index.html").read_text(encoding="utf-8")
    matches = list(re.finditer(DATA_PATTERN, html, re.S))
    if len(matches) != 1 or html.count(LOCAL_MARKER) != 1:
        raise ValueError("Expected one local deployment marker and one report data block.")
    notes = json.loads(matches[0].group(1))
    if not isinstance(notes, list) or not notes:
        raise ValueError("Report data is empty or invalid.")
    reviews = {}
    for name in ("reviewed-summaries.json", "additional-reviewed-summaries.json"):
        reviews.update(json.loads((root / "knowledge" / name).read_text(encoding="utf-8")))
    approved = json.loads((root / "knowledge/app-import.json").read_text(encoding="utf-8"))["notes"]
    if {n["id"] for n in notes} != {n["id"] for n in approved}:
        raise ValueError("Published index has changed; run tools/embed_report_library.py first.")
    allowed_pairs = {(n["id"], n["source"]) for n in approved}
    seen = set()
    manifest = []
    inbox = (root / "reports/inbox").resolve()
    for note in notes:
        source = (root / note["source"]).resolve()
        if inbox not in source.parents or source.suffix.lower() != ".pdf" or not source.is_file():
            raise ValueError("Invalid/missing PDF source: " + note["source"])
        if (note["id"], note["source"]) not in allowed_pairs:
            raise ValueError("Source is not in the approved publication list: " + note["title"])
        digest = file_hash(source)
        if digest in seen:
            raise ValueError("Duplicate report content: " + note["title"])
        seen.add(digest)
        if note.get("sourceSha256") != digest or note["id"] != "r-" + digest[:12]:
            raise ValueError("PDF changed since review: " + note["title"])
        review = note.get("reviewedSummary")
        if not review or review.get("format") != 2:
            raise ValueError("Missing reviewed format-2 summary: " + note["title"])
        if review != reviews.get(note["title"]):
            raise ValueError("Summary changed; run tools/embed_report_library.py: " + note["title"])
        legacy = review.get("sourceSha256") is None and review.get("pageCount") is None
        if legacy and note["id"] in LEGACY_REVIEW_IDS:
            fulltext = json.loads((root / "knowledge/fulltext" / (digest + ".json")).read_text())
            if fulltext.get("sha256") != digest or len(fulltext["pages"]) != note.get("pages"):
                raise ValueError("Legacy fulltext provenance mismatch: " + note["title"])
        elif review.get("sourceSha256") != digest or review.get("pageCount") != note.get("pages"):
            raise ValueError("Summary source hash/page count mismatch: " + note["title"])
        validate(note["title"], review)
        size = source.stat().st_size
        available = size <= LIMIT
        note["cloudStorage"] = {
            "available": available,
            "bytes": size,
            "reason": None if available else "file-too-large",
        }
        manifest.append({
            "id": note["id"], "title": note["title"], "source": note["source"],
            "sha256": digest, "bytes": size, "cloudAvailable": available,
            "reviewProvenance": "legacy-fulltext-record" if legacy else "reviewed-summary",
        })
    expected_dates = [dict(note) for note in notes]
    enrich_dates(expected_dates, root)
    for note, expected in zip(notes, expected_dates):
        for key in ("sortDate", "sortBasis", "sortLabel", "uploadOrder", "dateEvidence"):
            if note.get(key) != expected[key]:
                raise ValueError("Sort dates changed; run tools/embed_report_library.py: " + note["title"])
    encoded = json.dumps(notes, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = re.sub(DATA_PATTERN, lambda _: "<!-- REPORT_DATA_START -->" + encoded +
                  "<!-- REPORT_DATA_END -->", html, count=1, flags=re.S)
    html = html.replace(LOCAL_MARKER, CLOUD_MARKER)
    html = html.replace('content="本地行业研究报告检索、筛选与智能摘要工作台"',
                        'content="行业研究报告检索、筛选与智能总结知识库"')
    version = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return html, manifest, version


def split_cloud_library(root, html):
    """Keep the catalogue inline; load reviewed content only when needed."""
    notes = json.loads(re.search(DATA_PATTERN, html, re.S).group(1))
    assets = {}

    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

    def resource(prefix, value):
        text = encode(value)
        digest = hashlib.sha256(text.encode()).hexdigest()[:20]
        path = f"library/{prefix}-{digest}.json"
        assets[path] = text
        return path

    catalogue = []
    fields = ("id", "title", "tags", "source", "fileType", "institutionType",
              "industry", "organization", "year", "pages", "textStatus", "cloudStorage",
              "createdAt", "uploadOrder", "sortDate", "sortBasis", "sortLabel")
    for note in notes:
        item = {k: note[k] for k in fields if k in note}
        item["reviewedSummary"] = {"tldr": note["reviewedSummary"]["tldr"]}
        item["detailFile"] = resource(note["id"], {
            "id": note["id"], "reviewedSummary": note["reviewedSummary"],
        })
        catalogue.append(item)
    # Search/export fetch bounded chunks. Failed chunks can be retried independently.
    chunks, batch, batch_bytes = [], [], 0
    for note in notes:
        size = len(encode(note).encode())
        if batch and batch_bytes + size > 180000:
            chunks.append({"url": resource("search", batch), "ids": [n["id"] for n in batch]})
            batch, batch_bytes = [], 0
        batch.append(note)
        batch_bytes += size
    if batch:
        chunks.append({"url": resource("search", batch), "ids": [n["id"] for n in batch]})
    block_pattern = r'<script id="reportData" type="application/json">.*?</script>'
    if len(re.findall(block_pattern, html, re.S)) != 1:
        raise ValueError("Expected one report script element.")
    loader = (root / "cloudflare/library-loader.js").read_text(encoding="utf-8")
    if "</script" in loader.lower():
        raise ValueError("Unsafe inline loader closing tag.")
    replacement = (
        '<script id="reportData" type="application/json"><!-- REPORT_DATA_START -->' +
        encode(catalogue) + '<!-- REPORT_DATA_END --></script>\n'
        '<script id="cloudLibraryConfig" type="application/json">' +
        encode({"chunks": chunks}) + '</script>\n<script>' + loader + '</script>')
    html = re.sub(block_pattern, lambda _: replacement, html, count=1, flags=re.S)
    html = html.replace('id="importBtn">导入 JSON', 'id="importBtn">更新说明')
    html = html.replace(
        '<section class="filter-panel"',
        '<div id="libraryStatus" class="library-status" role="status" aria-live="polite">'
        '<span>正在载入报告目录…</span></div>'
        '<noscript><p class="library-status">请启用浏览器 JavaScript 后刷新，'
        '以查看报告目录与总结。</p></noscript>\n<section class="filter-panel"', 1)
    html = html.replace('</style>', (
        '.library-status{margin:18px 0;padding:14px 18px;border:1px solid var(--line);'
        'border-radius:10px;background:var(--paper);color:var(--ink)}'
        '.library-status[hidden]{display:none}.library-status button,.library-status a'
        '{margin-left:12px;color:var(--blue)}.summary-loading{padding:14px 0}\n</style>'), 1)
    watchdog = """<script>
    (function(){
      function failed(){
        if(document.documentElement.getAttribute('data-library-ready')==='true')return;
        var box=document.getElementById('libraryStatus');
        if(box){box.hidden=false;box.innerHTML='<span>页面尚未加载完成，请检查网络后重试。</span> <a href="/">重新加载页面</a>';}
      }
      window.addEventListener('error',failed);
      setTimeout(failed,15000);
    })();
    </script>"""
    html = html.replace('<body>', '<body>' + watchdog, 1)
    worker = (root / "cloudflare/service-worker.js").read_text(encoding="utf-8")
    cache_version = hashlib.sha256((html + worker).encode()).hexdigest()[:24]
    html = html.replace("</head>", '<meta name="starknows-cache-version" content="' +
                        cache_version + '" />\n</head>', 1)
    assets["sw.js"] = worker.replace("__BUILD_VERSION__", cache_version)
    return html, assets, {
        "homepageBytes": len(html.encode()), "detailFiles": len(notes),
        "searchChunks": len(chunks),
        "detailBytes": sum(len(assets[n["detailFile"]].encode()) for n in catalogue),
        "largestJsonBytes": max(len(text.encode()) for path, text in assets.items()
                               if path.endswith(".json")),
    }


def build(root, output):
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents or output in root.parents:
        raise ValueError("Build output must be outside the source workspace.")
    if output.exists() and not (output / BUILD_MARKER).is_file():
        raise ValueError("Refusing to replace an unrecognized output directory: " + str(output))
    html, reports, _ = prepare(root)
    html, library_assets, loading = split_cloud_library(root, html)
    version = hashlib.sha256(html.encode("utf-8")).hexdigest()
    # A staging directory keeps incomplete/failed copies away from a deployable build.
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="starknows-stage-", dir=output.parent))
    try:
        public = staging / "public"
        public.mkdir()
        (public / "index.html").write_text(html, encoding="utf-8")
        for relative, content in library_assets.items():
            target = public / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        for report in reports:
            if not report["cloudAvailable"]:
                continue
            target = public / report["source"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / report["source"], target)
            if file_hash(target) != report["sha256"]:
                raise ValueError("Source changed while copying: " + report["source"])
        (public / "404.html").write_text(
            '<!doctype html><html lang="zh-CN"><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>文件未发布 · 星知 StarKnows</title>'
            '<body style="max-width:640px;margin:12vh auto;padding:24px;'
            'font:16px/1.8 system-ui;background:#faf8f2;color:#292d45">'
            '<h1>未找到云端文件</h1><p>该地址没有可用的云端文件。'
            '部分较大的报告仅保留在本地，请返回知识库查看对应说明。</p>'
            '<p><a href="/">返回知识库</a></p></body></html>', encoding="utf-8")
        (public / "_headers").write_text(
            "/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: same-origin\n"
            "  X-Frame-Options: SAMEORIGIN\n"
            "/\n  Cache-Control: no-cache\n"
            "/index.html\n  Cache-Control: no-cache\n"
            "/sw.js\n  Cache-Control: no-cache\n  Service-Worker-Allowed: /\n"
            "/library/*\n  Cache-Control: public, max-age=31536000, immutable\n"
            "/reports/inbox/*\n  Cache-Control: private, max-age=3600\n",
            encoding="utf-8")
        files = [p for p in public.rglob("*") if p.is_file()]
        if any(p.stat().st_size > LIMIT for p in files) or len(files) > 20000:
            raise ValueError("Build exceeds Cloudflare Free static asset limits.")
        config = json.loads((root / "cloudflare/wrangler.jsonc").read_text(encoding="utf-8"))
        if set(config) - {"name", "compatibility_date", "workers_dev", "preview_urls", "assets", "routes"}:
            raise ValueError("Unexpected cloud service configuration; this is a static-only build.")
        if config["assets"] != {
                "directory": "./public", "html_handling": "auto-trailing-slash",
                "not_found_handling": "404-page"}:
            raise ValueError("Unexpected static asset routing configuration.")
        (staging / "wrangler.jsonc").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        uploaded = [r for r in reports if r["cloudAvailable"]]
        manifest = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "buildVersion": version,
            "maxAssetBytes": LIMIT, "summaryCount": len(reports),
            "cloudPdfCount": len(uploaded),
            "localOnlyPdfCount": len(reports) - len(uploaded),
            "cloudPdfBytes": sum(r["bytes"] for r in uploaded),
            "loading": loading,
            "oversizedMessage": MESSAGE, "reports": reports,
        }
        (staging / "publication-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / BUILD_MARKER).write_text("Generated by tools/build_cloudflare_site.py\n")
        if output.exists():
            shutil.rmtree(output)
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps({
        "output": str(output), "summaries": len(reports), "cloudPdfs": len(uploaded),
        "localOnlyPdfs": len(reports) - len(uploaded),
        "cloudPdfBytes": manifest["cloudPdfBytes"], "buildVersion": version,
        "loading": loading,
    }, ensure_ascii=False, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(ROOT, args.output)


if __name__ == "__main__":
    main()
