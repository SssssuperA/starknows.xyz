#!/usr/bin/env python3
"""Build a local, source-traceable research-report catalog from inbox PDFs."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "reports" / "inbox"
KNOWLEDGE = ROOT / "knowledge"
SUMMARIES = KNOWLEDGE / "summaries"
TOPICS = KNOWLEDGE / "topics"

CATEGORIES = {
    "人工智能与数字科技": ["ai", "人工智能", "大模型", "智能体", "aigc", "算法", "算力", "机器人", "智能穿戴", "具身智能", "智能世界"],
    "品牌营销与消费者": ["品牌", "营销", "消费", "种草", "达人", "媒介", "心智", "忠诚度", "广告", "用户"],
    "电商零售与跨境": ["电商", "零售", "跨境", "供应链", "支付", "双11", "大促", "即时零售", "tiktok shop"],
    "文娱与内容产业": ["影视", "电影", "短剧", "微短剧", "直播", "综艺", "播客", "脱口秀", "传媒", "内容资产", "剧综"],
    "宠物行业": ["宠物"],
    "美妆服饰与时尚": ["美妆", "医美", "美护", "服饰", "服装", "潮玩", "威士忌", "母婴"],
    "旅游体育与生活方式": ["旅游", "文旅", "冰雪", "体育", "养生", "健康", "伤痛"],
    "企业管理与专业服务": ["cio", "cfo", "hr", "项目管理", "组织", "管理", "专业服务", "企业ai", "风控"],
    "宏观经济与城市发展": ["经济", "城市", "商业环境", "数字贸易", "中小企业", "服务消费"],
    "汽车与出行": ["汽车"],
    "金融科技": ["金融", "支付"],
}

STOP_HEADINGS = {"目录", "contents", "免责声明", "法律声明", "版权声明", "前言", "序言"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def classify(title: str, sample: str) -> tuple[str, list[str]]:
    title_hay = title.lower()
    sample_hay = sample[:8000].lower()
    scored = []
    for category, words in CATEGORIES.items():
        # The filename usually carries the report's declared subject; body mentions
        # are supporting evidence and should not overpower that signal.
        score = sum(title_hay.count(word.lower()) * 30 + min(sample_hay.count(word.lower()), 8) for word in words)
        if score:
            scored.append((score, category))
    scored.sort(reverse=True)
    primary = scored[0][1] if scored else "综合研究"
    secondary = [name for _, name in scored[1:3]]
    return primary, secondary


def infer_year(title: str, text: str, metadata_year: str = "") -> str:
    # Prefer plausible publication years in the filename. Future years in titles
    # often describe a forecast horizon (for example "智能世界2035").
    years = re.findall(r"20(?:1[8-9]|2[0-6])", title)
    if years:
        return years[0]
    compact = re.search(r"(?<!\d)(1[8-9]|2[0-6])(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)", title)
    if compact:
        return "20" + compact.group(1)
    if re.fullmatch(r"20(?:1[8-9]|2[0-6])", metadata_year or ""):
        return metadata_year
    cover = text[:3500]
    dated = re.search(r"(20(?:1[8-9]|2[0-6]))\s*年\s*(?:0?[1-9]|1[0-2])\s*月", cover)
    if dated:
        return dated.group(1)
    dated = re.search(r"(20(?:1[8-9]|2[0-6]))[-/.](?:0?[1-9]|1[0-2])(?:[-/.](?:0?[1-9]|[12]\d|3[01]))?", cover)
    if dated:
        return dated.group(1)
    copyright_year = re.search(r"(?:©|copyright)\s*(20(?:1[8-9]|2[0-6]))", cover, re.I)
    return copyright_year.group(1) if copyright_year else "年份待确认"


def infer_org(title: str, text: str) -> str:
    stem = Path(title).stem
    parts = re.split(r"[-—_｜|]", stem)
    candidates = [p.strip("【】[]（）() ") for p in parts if p.strip()]
    known = ["艾瑞咨询", "KPMG", "尼尔森", "益普索", "艺恩", "小红书", "摩根士丹利", "高盛", "华泰证券", "华西证券", "头豹研究院", "埃森哲", "MoonFox", "京东", "电通", "麦肯锡", "安永", "易观分析", "CBNData", "巨量引擎"]
    for org in known:
        if org.lower() in stem.lower() or org.lower() in text[:2500].lower():
            return org
    if len(candidates) > 1 and len(candidates[-1]) <= 16 and not any(k in candidates[-1] for k in ["报告", "洞察", "白皮书", "资产", "趋势", "增长", "经济", "时代", "策略", "革命"]):
        return candidates[-1]
    return "未识别"


def infer_file_type(title: str, category: str) -> str:
    lower = title.lower()
    if "招股" in title or "prospectus" in lower:
        return "招股书"
    if "论文" in title or "journal" in lower:
        return "专业论文"
    if category == "宏观经济与城市发展" or any(k in title for k in ["宏观", "经济观察", "行业中期策略"]):
        return "宏观策略"
    if "财报" in title or (any(k in title for k in ["年报", "半年报", "季度报告"]) and not any(k in title for k in ["行业", "市场", "趋势", "流量", "全站点", "基准", "经济"])):
        return "公司财报"
    if "白皮书" in title:
        return "白皮书"
    if any(k in title for k in ["数据", "调查", "指数", "盘点"]):
        return "数据报告"
    return "行业研究"


def infer_institution_type(org: str, title: str) -> str:
    hay = f"{org} {title}".lower()
    if any(k in hay for k in ["证券", "高盛", "摩根士丹利", "银河"]):
        return "券商与投行"
    if any(k in hay for k in ["艾瑞", "易观", "moonfox", "头豹", "dataeye", "艾媒", "艺恩", "克劳锐", "星图"]):
        return "数据研究机构"
    if any(k in hay for k in ["kpmg", "安永", "埃森哲", "麦肯锡", "益普索", "尼尔森", "奥美", "gartner", "沙利文", "阳狮"]):
        return "咨询机构"
    if any(k in hay for k in ["协会", "研究院", "中国互联网络信息中心"]):
        return "协会与研究院"
    if any(k in hay for k in ["京东", "小红书", "哔哩哔哩", "腾讯", "华为", "巨量引擎", "美团", "tmi", "cbndata"]):
        return "企业与平台"
    return "其他机构"


def infer_industry(title: str, category: str) -> str:
    rules = [
        ("具身智能", ["人形机器人", "具身智能", "物理ai"]),
        ("AI基模", ["大模型", "基模", "模型基准"]),
        ("AI智能体", ["智能体", "agent"]),
        ("AI搜索与GEO", ["ai搜索", "geo", "aibe", "从geo到gao"]),
        ("AI基础设施", ["算力", "基础设施"]),
        ("电商与即时零售", ["电商", "即时零售", "双11", "大促", "tiktok shop"]),
        ("宠物", ["宠物"]),
        ("美妆与医美", ["美妆", "医美", "美护"]),
        ("服饰与时尚", ["服饰", "服装", "纺织"]),
        ("影视与短剧", ["影视", "电影", "短剧", "微短剧", "综艺"]),
        ("内容与传媒", ["传媒", "播客", "直播", "内容资产", "脱口秀"]),
        ("汽车", ["汽车"]),
        ("潮玩与IP", ["潮玩", "labubu", "ai玩具"]),
        ("跨境出海", ["跨境", "东南亚", "出海", "kickstarter"]),
        ("旅游与体育", ["旅游", "文旅", "冰雪", "体育"]),
        ("健康消费", ["健康", "养生", "伤痛"]),
        ("企业管理", ["cio", "cfo", "hr ", "组织", "项目管理", "专业服务"]),
        ("宏观经济", ["经济", "城市", "商业环境", "数字贸易"]),
        ("品牌与营销", ["品牌", "营销", "达人", "媒介", "种草", "消费者"]),
    ]
    lower = title.lower()
    for name, words in rules:
        if any(word.lower() in lower for word in words):
            return name
    fallback = {
        "人工智能与数字科技": "人工智能",
        "品牌营销与消费者": "消费与零售",
        "电商零售与跨境": "电商与即时零售",
        "文娱与内容产业": "内容与传媒",
        "宠物行业": "宠物",
        "美妆服饰与时尚": "消费与零售",
        "旅游体育与生活方式": "旅游与体育",
        "企业管理与专业服务": "企业管理",
        "宏观经济与城市发展": "宏观经济",
        "汽车与出行": "汽车",
    }
    return fallback.get(category, "综合行业")


def useful_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" •·—–-|｜")
        if len(line) < 12 or len(line) > 180:
            continue
        if line.lower() in STOP_HEADINGS:
            continue
        if re.fullmatch(r"[\d\s./%-]+", line):
            continue
        if "发现报告" in line or "fxbaogao" in line.lower():
            continue
        lines.append(line)
    # Preserve order while removing repetitions.
    return list(dict.fromkeys(lines))


def extract_pdf(path: Path) -> dict:
    try:
        reader = PdfReader(str(path), strict=False)
        page_count = len(reader.pages)
        metadata_year = ""
        metadata = reader.metadata or {}
        for key in ("/CreationDate", "/ModDate"):
            match = re.search(r"20(?:1[8-9]|2[0-6])", str(metadata.get(key, "")))
            if match:
                metadata_year = match.group(0)
                break
        first_pages, sampled_pages = [], []
        sample_ids = sorted(set(range(min(8, page_count))) | set(range(max(0, page_count - 2), page_count)))
        for i in sample_ids:
            try:
                txt = clean_text(reader.pages[i].extract_text() or "")
            except Exception:
                txt = ""
            if i < 8:
                first_pages.append(txt)
            sampled_pages.append({"page": i + 1, "text": txt[:9000]})
        full_sample = clean_text("\n".join(first_pages))
        return {"status": "ok" if len(full_sample) >= 200 else "needs_ocr", "pages": page_count, "sample": full_sample, "page_samples": sampled_pages, "metadata_year": metadata_year}
    except Exception as exc:
        return {"status": "error", "pages": 0, "sample": "", "page_samples": [], "metadata_year": "", "error": str(exc)[:240]}


def make_summary(record: dict) -> str:
    lines = useful_lines(record.pop("_sample", ""))
    highlights = lines[:8]
    if not highlights:
        highlights = ["当前文件未提取到足够文本，建议后续进行 OCR 或人工复核。"]
    bullets = "\n".join(f"- {line}" for line in highlights)
    secondary = "、".join(record["secondary_categories"]) or "无"
    return f"""# {record['title']}

## 基本信息

- 主分类：{record['category']}
- 相关分类：{secondary}
- 发布机构：{record['organization']}
- 报告年份：{record['year']}
- 页数：{record['pages']}
- 来源文件：`{record['source']}`
- 文件指纹：`{record['sha256'][:16]}`
- 文本状态：{record['text_status']}

## 首版内容提要

{bullets}

## 使用提示

本页为批量入库生成的首版摘要，优先依据报告前部正文与末页信息整理。涉及市场规模、增速、预测和公司判断时，应回到原报告核对页码、统计口径与时间范围。
"""


def main() -> int:
    KNOWLEDGE.mkdir(parents=True, exist_ok=True)
    SUMMARIES.mkdir(parents=True, exist_ok=True)
    TOPICS.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(INBOX.glob("*.pdf"), key=lambda p: p.name.lower())
    if not pdfs:
        print("No PDFs found", file=sys.stderr)
        return 1

    records, seen_hashes = [], {}
    for idx, path in enumerate(pdfs, 1):
        digest = sha256(path)
        extracted = extract_pdf(path)
        title = path.stem
        category, secondary = classify(title, extracted["sample"])
        duplicate_of = seen_hashes.get(digest)
        seen_hashes.setdefault(digest, path.name)
        safe_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", title)[:100].strip("_") or f"report-{idx}"
        record = {
            "id": f"r-{digest[:12]}",
            "title": title,
            "category": category,
            "secondary_categories": secondary,
            "organization": infer_org(title, extracted["sample"]),
            "year": infer_year(title, extracted["sample"], extracted["metadata_year"]),
            "pages": extracted["pages"],
            "text_status": extracted["status"],
            "source": str(path.relative_to(ROOT)),
            "summary": f"knowledge/summaries/{safe_name}.md",
            "sha256": digest,
            "duplicate_of": duplicate_of,
            "keywords": list(dict.fromkeys([category, *secondary, infer_org(title, extracted["sample"]), infer_year(title, extracted["sample"], extracted["metadata_year"])])),
            "highlights": useful_lines(extracted["sample"])[:8],
            "page_samples": extracted["page_samples"],
            "indexed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "_sample": extracted["sample"],
        }
        summary_path = ROOT / record["summary"]
        summary_path.write_text(make_summary(record), encoding="utf-8")
        records.append(record)
        print(f"[{idx}/{len(pdfs)}] {path.name} -> {category} ({extracted['status']})")

    index = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_directory": "reports/inbox",
        "report_count": len(records),
        "unique_file_count": len({r["sha256"] for r in records}),
        "categories": dict(Counter(r["category"] for r in records).most_common()),
        "text_status": dict(Counter(r["text_status"] for r in records).most_common()),
        "reports": records,
    }
    (KNOWLEDGE / "report-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = ["# 行业研究报告目录", "", f"共收录 {len(records)} 份 PDF；去重后 {index['unique_file_count']} 份。", ""]
    for category in index["categories"]:
        rows += [f"## {category}", ""]
        for r in records:
            if r["category"] == category:
                dup = f"（与 {r['duplicate_of']} 重复）" if r["duplicate_of"] else ""
                rows.append(f"- [{r['title']}](summaries/{Path(r['summary']).name})｜{r['organization']}｜{r['year']}｜{r['pages']} 页{dup}")
        rows.append("")
    (KNOWLEDGE / "catalog.md").write_text("\n".join(rows), encoding="utf-8")

    for category, count in index["categories"].items():
        group = [r for r in records if r["category"] == category and not r["duplicate_of"]]
        orgs = Counter(r["organization"] for r in group if r["organization"] != "未识别")
        years = Counter(r["year"] for r in group if r["year"] != "年份待确认")
        topic_rows = [
            f"# {category}", "",
            f"本主题收录 {len(group)} 份非重复报告。", "",
            "## 资料结构", "",
            f"- 主要年份：{'、'.join(f'{k}（{v}份）' for k, v in years.most_common(5)) or '未识别'}",
            f"- 主要机构：{'、'.join(f'{k}（{v}份）' for k, v in orgs.most_common(8)) or '未识别'}",
            "", "## 报告清单", "",
        ]
        for r in group:
            topic_rows.append(f"- [{r['title']}](../summaries/{Path(r['summary']).name})｜{r['organization']}｜{r['year']}｜{r['pages']} 页")
        topic_rows += ["", "## 跨文件使用建议", "", "围绕具体问题检索本主题时，请同时比较报告年份、数据口径、样本范围和发布机构；结论输出应保留原文件及页码。", ""]
        safe_topic = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", category)
        (TOPICS / f"{safe_topic}.md").write_text("\n".join(topic_rows), encoding="utf-8")

    app_notes = []
    for r in records:
        duplicate_line = f"\n重复文件：{r['duplicate_of']}" if r["duplicate_of"] else ""
        body = "\n".join([
            f"机构：{r['organization']}｜年份：{r['year']}｜页数：{r['pages']}",
            f"来源：{r['source']}",
            duplicate_line.strip(),
            "",
            "首版内容提要：",
            *[f"• {x}" for x in r["highlights"]],
            "",
            "提示：重要数字和判断请回到原报告核对页码及统计口径。",
        ]).strip()
        app_notes.append({
            "id": r["id"], "title": r["title"],
            "tags": list(dict.fromkeys([r["category"], r["organization"], r["year"]] + r["secondary_categories"])),
            "body": body, "createdAt": r["indexed_at"], "updatedAt": r["indexed_at"],
            "source": r["source"], "kind": "research-report",
            "fileType": infer_file_type(r["title"], r["category"]),
            "institutionType": infer_institution_type(r["organization"], r["title"]),
            "industry": infer_industry(r["title"], r["category"]),
            "organization": r["organization"], "year": r["year"], "pages": r["pages"],
            "textStatus": r["text_status"], "duplicateOf": r["duplicate_of"],
            "highlights": r["highlights"],
            "excerpt": "\n\n".join(f"第 {p['page']} 页\n{p['text']}" for p in r["page_samples"] if p["text"])[:70000],
        })
    (KNOWLEDGE / "app-import.json").write_text(json.dumps({"app": "星知 StarKnows 知识库", "notes": app_notes}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"reports": len(records), "unique": index["unique_file_count"], "categories": index["categories"], "status": index["text_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
