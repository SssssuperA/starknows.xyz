"""Deterministic report chronology, independent of file paths and modification times."""
import calendar
import json
import re
from datetime import date


def end_date(value):
    """Month-only dates sort at month end; retain original precision for display."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", value):
        raise ValueError("Expected YYYY-MM or YYYY-MM-DD: " + str(value))
    parts = [int(p) for p in value.split("-")]
    year, month = parts[:2]
    day = parts[2] if len(parts) == 3 else calendar.monthrange(year, month)[1]
    return date(year, month, day).isoformat()


def title_date(title):
    """Only explicit title dates/periods; never scan narrative or forecast numbers."""
    if re.search(r"预测|展望|规划|前瞻", title):
        return None
    # Full and abbreviated range endpoints: 2026/1/1—3/31, 2026年1月—3月.
    month_day = r"(\d{1,2})(?!\d)(?:\s*月(?:\s*(\d{1,2})\s*日)?|\s*[./-]\s*(\d{1,2})(?!\d))?"
    atom = r"(?<!\d)(20\d{2})\s*[年./-]\s*" + month_day
    separator = r"\s*(?:->|→|至|到|[—–~～－-])\s*"
    candidates = []
    for match in re.finditer(atom, title):
        y, m, chinese_day, numeric_day = match.groups()
        d = chinese_day or numeric_day
        value = f"{int(y):04}-{int(m):02}" + (f"-{int(d):02}" if d else "")
        try:
            end_date(value)
        except ValueError:
            return None
        candidates.append(value)
        tail = title[match.end():]
        short = re.match(separator + month_day, tail)
        if short:
            month, chinese_day, numeric_day = short.groups()
            day = chinese_day or numeric_day
            value = f"{int(y):04}-{int(month):02}" + (f"-{int(day):02}" if day else "")
            try:
                end_date(value)
                candidates.append(value)
            except ValueError:
                return None
    if candidates:
        return {"date": max(candidates, key=end_date),
                "basis": "period" if len(candidates) > 1 else "published", "quote": title}
    # Dated broker filenames; do not interpret unqualified 0808 as a date.
    suffix = re.search(r"[-_](?:(20\d{2})(\d{2})(\d{2})|(\d{2})(\d{2})(\d{2}))$", title)
    if suffix:
        y, m, d, yy, mm, dd = suffix.groups()
        value = f"{y or '20' + yy}-{m or mm}-{d or dd}"
        try:
            end_date(value)
            return {"date": value, "basis": "published", "quote": title}
        except ValueError:
            pass
    half = re.search(r"(20\d{2})\s*年?\s*(?:H([12])|([上下])半年)", title, re.I)
    quarter = re.search(r"(20\d{2})\s*年?\s*(?:Q([1-4])(?:\s*[-—–至]\s*Q?([1-4]))?|第?([一二三四1-4])季度)", title, re.I)
    if half:
        year, number, word = half.groups()
        month = 6 if number == "1" or word == "上" else 12
    elif quarter:
        year, first, last, chinese = quarter.groups()
        if chinese:
            number = "一二三四".index(chinese) + 1 if chinese in "一二三四" else int(chinese)
        else:
            number = int(last or first)
        month = number * 3
    else:
        return None
    return {"date": f"{year}-{month:02}", "basis": "period", "quote": title}


def enrich_dates(notes, root):
    """Attach reviewed date evidence and stable original ingestion order."""
    path = root / "knowledge/report-dates.json"
    reviewed = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for order, note in enumerate(notes):
        entry = reviewed.get(note["id"])
        if entry and entry.get("date"):
            if entry.get("source") == "title":
                evidence = note["title"]
            else:
                full = json.loads((root / "knowledge/fulltext" / (note["sourceSha256"] + ".json")).read_text())
                evidence = next(p["text"] for p in full["pages"] if p["page"] == entry["page"])
            compact = lambda text: re.sub(r"\s+", "", text)
            if compact(entry["quote"]) not in compact(evidence):
                raise ValueError("Date evidence no longer matches source: " + note["title"])
        # A reviewed null date explicitly suppresses ambiguous/invalid title dates.
        timing = entry if entry is not None else title_date(note["title"])
        note["uploadOrder"] = order
        if timing and timing.get("date"):
            value = timing["date"]
            validated = end_date(value)
            note["sortDate"] = value + "-01" if len(value) == 7 and timing["basis"] == "published" else validated
            note["sortBasis"] = timing["basis"]
            note["sortLabel"] = ("数据截至 " if timing["basis"] == "period" else "发布于 ") + value
            note["dateEvidence"] = timing
        else:
            note["sortDate"] = None
            note["sortBasis"] = "uploaded"
            note["sortLabel"] = "入库于 " + note.get("createdAt", "")[:10]
            note["dateEvidence"] = timing
