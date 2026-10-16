#!/usr/bin/env python3
"""Build structured formula records from OCR output of 《妙用偏方秘方》.

Input : data/ocr/part_*.jsonl   (page -> lines with normalized bbox)
Output: assets/records.jsonl    (one JSON object per formula)
        data/parse_report.txt   (parse diagnostics)

Design notes
------------
The scanned book uses a highly regular layout:

    【方 16】 羊血米醋治疗便血          <- formula heading
    【药方】羊血500克，米醋60毫升。      <- ingredients
    【制用法】将羊血煮熟，拌醋，分2次服。  <- preparation / usage
    【效用】止血祛淤。用于治疗便血。       <- effect / indication

Section headings (conditions) are centred and use Chinese numerals:

    二七、消化不良

Chapter headings sit at the page footer:

    第一章 内科

Body lines start around x=0.15 while continuation lines start around x=0.11,
so indentation is used to stitch wrapped lines back together.

OCR is not perfect. We keep the raw text in `raw` and apply only a small,
explicit, documented correction table (`OCR_FIXES`) plus whitespace
normalisation. Anything uncertain is left as-is rather than invented.
"""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import re
import unicodedata
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OCR_DIR = SKILL_ROOT / "data" / "ocr"
DEFAULT_OUT = SKILL_ROOT / "assets" / "records.jsonl"
DEFAULT_REPORT = SKILL_ROOT / "data" / "parse_report.txt"

CN_DIGITS = "〇零一二三四五六七八九十百千"

# ---------------------------------------------------------------------------
# OCR correction table.
# Only unambiguous, layout-independent substitutions. Every entry is applied
# to body text; the untouched original is preserved in the `raw` field.
# ---------------------------------------------------------------------------
OCR_FIXES = [
    ("硏", "研"),          # 硏末 -> 研末
    ("壽", "痔"),
    ("寿疮", "痔疮"),
    ("特疮", "痔疮"),
    ("尊麻疹", "荨麻疹"),
    ("脸缘炎", "睑缘炎"),
    ("人荸荠", "入荸荠"),
    ("人锅", "入锅"),
    ("人药", "入药"),
    ("装人", "装入"),
    ("加人", "加入"),
    ("放人", "放入"),
    ("人内", "入内"),
    ("插人", "插入"),
    ("调人", "调入"),
    ("拌人", "拌入"),
    ("浸人", "浸入"),
    ("敷人", "敷入"),
    ("倒人", "倒入"),
    ("塞人", "塞入"),
    ("送人", "送入"),
    ("放人锅", "放入锅"),
    ("功効", "功效"),
    ("効", "效"),
    ("菷", "帚"),
    ("茏", "笼"),
]

# Field labels that appear as 【label】 at the start of a line.
FIELD_LABELS = [
    "药方", "制用法", "效用", "功用", "主治", "用法", "配方", "组成",
    "备注", "说明", "禁忌", "来源", "材料", "制作", "服法", "功效",
]
# Vision mangles the label glyphs constantly (药方 -> 药,方 / 精方 / 對方 /
# 效方; 制用法 -> 制用 / 利用法 / 用科). Labels are therefore matched
# structurally and then routed by meaning rather than by exact string.
BRACKETED_LABEL_RE = re.compile(r"^[【\[（(•·\s]*([^】\]）)]{1,6})\s*[】\]）)]\s*(.*)$")
BARE_LABEL_RE = re.compile(
    r"^[•·\s]*(药方|药\s*,?\s*方|配方|组成|材料|用科|药料|"
    r"制用法|制用|用法|制作|服法|利用法|制法|"
    r"效用|功用|功效|主治|用途)\s*[：:，,、;；]?\s*(.*)$"
)
INGREDIENT_KEYS = ("药", "方", "组成", "配方", "材料", "用科", "料")
USAGE_KEYS = ("制用", "制法", "用法", "制作", "服法", "服用", "服")
EFFECT_KEYS = ("效", "功", "主治", "用途", "作用")


def canon_label(raw: str) -> str | None:
    """Route a messy OCR label onto one of the three known fields."""
    cleaned = "".join(ch for ch in raw if "\u4e00" <= ch <= "\u9fff")
    if not cleaned:
        return None
    if any(key in cleaned for key in INGREDIENT_KEYS):
        return "药方"
    if any(key in cleaned for key in USAGE_KEYS):
        return "制用法"
    if any(key in cleaned for key in EFFECT_KEYS):
        return "效用"
    return None


def match_field(text: str) -> tuple[str, str] | None:
    """Return (canonical_label, value) when a line opens a labelled field."""
    bracketed = BRACKETED_LABEL_RE.match(text)
    if bracketed:
        label = canon_label(bracketed.group(1))
        if label:
            return label, bracketed.group(2).strip()
    bare = BARE_LABEL_RE.match(text)
    if bare:
        label = canon_label(bare.group(1))
        if label:
            return label, bare.group(2).strip()
    return None


FIELD_RE = re.compile(
    r"^[【\[（(]?\s*(?:"
    + "|".join(r"\s*".join(label) for label in FIELD_LABELS)
    + r")\s*[】\]）)]\s*(.*)$"
)
FORMULA_RE = re.compile(
    r"^[【\[（(]?\s*方\s*([0-9０-９]{1,3})\s*[】\]）)]\s*(.*)$"
)
SECTION_RE = re.compile(
    r"^[" + CN_DIGITS + r"]{1,4}\s*[、.．,，]\s*(.+?)\s*$"
)
CHAPTER_RE = re.compile(r"^第\s*([" + CN_DIGITS + r"]{1,4})\s*章\s*(.*)$")
# Tolerant form used for detection and name extraction: Vision misreads both the
# numeral (二 -> 三) and the 章 glyph (章 -> 童), so neither is required to be
# exact. The chapter name carries the real signal.
CHAPTER_LOOSE_RE = re.compile(r"^第[^\s]{0,3}[章童竟]\s*(.*)$")
PAGENO_RE = re.compile(r"^妙用偏方秘方[「『\[\(]?\s*([0-9０-９]{1,4})\s*$")
# A bare number sitting on its own in the footer band.
BARE_PAGENO_RE = re.compile(r"^([0-9０-９]{1,4})$")
# The running footer also repeats the book title; it must never be read as a
# chapter heading.
TITLE_RE = re.compile(r"^妙用偏方秘方")

CN_NUM = {
    "〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}

# The book has exactly seven chapters. Chapter numbers survive OCR reliably
# while the chapter names do not ("内科" is frequently read as "丙科"/"內科"),
# so the canonical name is looked up by chapter number.
CANONICAL_CHAPTERS = {
    1: "内科",
    2: "外科",
    3: "男科病",
    4: "妇科病",
    5: "小儿科疾病",
    6: "五官科",
    7: "皮肤科",
    8: "美容",
}

TOC_PAGES = range(3, 12)

# Units that mark a fragment as a dosage rather than prose.
UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:克|千克|公斤|毫升|升|毫克|g|ml|两|钱|分|枚|个|只|"
    r"条|片|块|朵|粒|张|把|撮|寸|尺|杯|碗|匙|勺|滴|剂|丸|包|根|段|斤)"
)
AMOUNT_RE = re.compile(r"适量|少许|酌量|各等分|等量|若干")


def int_to_cn(number: int) -> str:
    """1 -> 一, 10 -> 十, 21 -> 二一 (matches the book's own numbering style)."""
    if number <= 0:
        return str(number)
    units = "〇一二三四五六七八九"
    if number < 10:
        return units[number]
    if number < 20:
        return "十" + (units[number % 10] if number % 10 else "")
    return units[number // 10] + units[number % 10]


def cn_to_int(text: str) -> int | None:
    """Convert a Chinese numeral (up to a few hundred) to int."""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if any(ch not in CN_DIGITS for ch in text):
        return None
    total, section, number = 0, 0, 0
    for ch in text:
        if ch in CN_NUM:
            number = CN_NUM[ch]
        elif ch == "十":
            section += (number or 1) * 10
            number = 0
        elif ch == "百":
            section += (number or 1) * 100
            number = 0
        elif ch == "千":
            section += (number or 1) * 1000
            number = 0
    total = section + number
    return total if total > 0 else None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u3000", " ")
    for src, dst in OCR_FIXES:
        text = text.replace(src, dst)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_pages(ocr_dir: Path) -> dict[int, dict]:
    pages: dict[int, dict] = {}
    for path in sorted(glob.glob(str(ocr_dir / "part_*.jsonl"))):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                pages[record["page"]] = record
    return pages


def page_lines(page: dict) -> tuple[list[dict], str, int | None]:
    """Split a page into body lines plus footer metadata.

    The scanned book prints the chapter heading and the running page number in
    the bottom band of the page (y < 0.085), e.g.

        第一章   内科   妙用偏方秘方「59

    Vision splits those into separate boxes, so the band is re-assembled by
    grouping boxes that share the same baseline.
    """
    lines = sorted(page["lines"], key=lambda item: (-item["y"], item["x"]))
    body: list[dict] = []
    footer: list[dict] = []
    for line in lines:
        text = line["text"].strip()
        if not text:
            continue
        item = {
            "text": text, "page": page["page"], "y": line["y"],
            "x": line["x"], "w": line["w"], "h": line["h"],
            "conf": line.get("conf", 0.0),
        }
        if line["y"] < 0.085:
            footer.append(item)
        elif line["y"] > 0.955:
            continue  # running header band
        else:
            body.append(item)

    body = join_same_baseline(body)

    # Group the footer band by baseline (tolerance 0.004).
    chapter = ""
    book_page = None
    for item in sorted(footer, key=lambda x: -x["y"]):
        text = normalize(item["text"])
        match = PAGENO_RE.match(text)
        if match:
            book_page = cn_to_int(match.group(1))
        elif BARE_PAGENO_RE.match(text):
            book_page = cn_to_int(text)
    groups: list[list[dict]] = []
    for item in sorted(footer, key=lambda x: -x["y"]):
        if groups and abs(groups[-1][0]["y"] - item["y"]) <= 0.004:
            groups[-1].append(item)
        else:
            groups.append([item])
    for group in groups:
        parts = sorted(
            (i for i in group
             if not PAGENO_RE.match(normalize(i["text"]))
             and not TITLE_RE.match(normalize(i["text"]))),
            key=lambda x: x["x"],
        )
        if not parts:
            continue
        joined = normalize("".join(i["text"] for i in parts))
        if CHAPTER_LOOSE_RE.match(joined):
            chapter = clean_chapter(joined)
    return body, chapter, book_page


def clean_condition(text: str) -> str:
    """Strip TOC leader dots, bullets and stray page numbers from a name."""
    name = SECTION_RE.match(text).group(1) if SECTION_RE.match(text) else text
    name = re.sub(r"[•·⋯…\.．,，\s]+$", "", name)
    name = re.sub(r"\s*[0-9０-９]{1,4}$", "", name)
    return name.strip(" .．·•　")


def parse_toc(pages: dict[int, dict]) -> dict[int, list[str]]:
    """Extract the canonical condition list per chapter from the contents pages."""
    toc: dict[int, list[str]] = {}
    chapter_no = None
    for page_no in TOC_PAGES:
        if page_no not in pages:
            continue
        body, _, _ = page_lines(pages[page_no])
        for line in sorted(body, key=lambda item: (-item["y"], item["x"])):
            text = normalize(line["text"])
            if CHAPTER_LOOSE_RE.match(text):
                chapter_no = chapter_no_of(clean_chapter(text))
                if chapter_no is not None:
                    toc.setdefault(chapter_no, [])
                continue
            section_match = SECTION_RE.match(text)
            if section_match and chapter_no is not None:
                name = clean_condition(text)
                if 1 < len(name) <= 22 and name not in toc[chapter_no]:
                    toc[chapter_no].append(name)
    return toc


def clean_chapter(text: str) -> str:
    """Normalise a chapter heading, trusting the *name* over the numeral.

    The footer numeral is unreliable in both directions: Vision reads 第二章 as
    "第三章" on some pages, and the 章 glyph itself is misread as 童. Mapping the
    numeral through CANONICAL_CHAPTERS then yields a confidently wrong chapter
    ("第三章外科" -> "第三章 男科病"). The chapter *name* is far more stable, so
    it is matched first and the numeral is only used when the name is unusable.
    """
    loose = CHAPTER_LOOSE_RE.match(normalize(text))
    if not loose:
        return text
    ocr_name = "".join(ch for ch in loose.group(1) if "\u4e00" <= ch <= "\u9fff")

    canonical_names = list(CANONICAL_CHAPTERS.values())
    if ocr_name in canonical_names:
        number = _chapter_number(ocr_name)
        return f"第{int_to_cn(number)}章 {ocr_name}"

    close = difflib.get_close_matches(ocr_name, canonical_names, n=1, cutoff=0.6)
    if close:
        number = _chapter_number(close[0])
        return f"第{int_to_cn(number)}章 {close[0]}"

    number = cn_to_int(loose.group(0).split("章")[0].replace("第", "").strip())
    if number in CANONICAL_CHAPTERS:
        return f"第{int_to_cn(number)}章 {CANONICAL_CHAPTERS[number]}"

    # Neither the name nor the numeral resolved. Returning "" makes the caller
    # carry the previous chapter forward, which is correct: a chapter spans
    # many pages, so one unreadable footer must not invent a new chapter.
    return ""


def _chapter_number(canonical_name: str) -> int:
    for number, name in CANONICAL_CHAPTERS.items():
        if name == canonical_name:
            return number
    return 0


def chapter_no_of(chapter: str) -> int | None:
    """Derive the chapter number from a normalised chapter string."""
    name = chapter.split("章", 1)[-1].strip()
    return _chapter_number(name) or None


def join_same_baseline(lines: list[dict], tolerance: float = 0.008,
                       max_gap: float = 0.055) -> list[dict]:
    """Re-assemble OCR boxes that Vision split on the same printed line.

    Vision frequently cuts a bracketed label in half, e.g.

        【药            (x=0.176)
        方】南瓜藤液…    (x=0.226)

    Both boxes share a baseline, so grouping by y and sorting by x restores the
    original line. A maximum horizontal gap is enforced so that unrelated items
    sharing a baseline — the running "目录" header next to a contents entry, or
    a page number column — are never glued together.
    """
    groups: list[list[dict]] = []
    for line in sorted(lines, key=lambda item: (-item["y"], item["x"])):
        if groups and abs(groups[-1][0]["y"] - line["y"]) <= tolerance:
            groups[-1].append(line)
        else:
            groups.append([line])

    joined: list[dict] = []
    for group in groups:
        group = sorted(group, key=lambda item: item["x"])
        run: list[dict] = []
        for item in group:
            if run and item["x"] - (run[-1]["x"] + run[-1]["w"]) > max_gap:
                joined.append(_merge_run(run))
                run = []
            run.append(item)
        if run:
            joined.append(_merge_run(run))
    return joined


def _merge_run(run: list[dict]) -> dict:
    first = run[0]
    if len(run) == 1:
        return first
    return {
        "text": re.sub(r"^(?:MULU|目录|日录|目錄)+", "",
                       "".join(item["text"].strip() for item in run)),
        "page": first["page"],
        "y": first["y"],
        "x": first["x"],
        "w": max(item["x"] + item["w"] for item in run) - first["x"],
        "h": max(item["h"] for item in run),
        "conf": min(item["conf"] for item in run),
    }


def merge_lines(lines: list[dict]) -> list[dict]:
    """Stitch wrapped continuation lines onto their logical line.

    Two shapes occur in this book:

        【制用法】将豆腐渣焙干研末，每天服2次，每次20～30克，用红糖水
        送服。                                  <- more indented than the field

        【制用法】
        洗净焙干研末。每日服2次，每次10克，黄酒送服，连服     <- label-only line
        3~5天。                                 <- more indented

    So a line continues the previous one when the previous line is a field line
    and either its value is empty or the new line is indented further left.
    """
    merged: list[dict] = []
    for line in lines:
        text = normalize(line["text"])
        if not text:
            continue
        starts_field = bool(
            FORMULA_RE.match(text) or FIELD_RE.match(text) or match_field(text)
        )
        centred = line["x"] > 0.25 and abs(line["x"] + line["w"] / 2 - 0.5) < 0.16
        is_section = bool(
            SECTION_RE.match(text) and line["h"] >= 0.023 and line["x"] > 0.20
        )
        is_heading = centred or is_section

        if merged and not starts_field and not is_heading:
            prev = merged[-1]
            if prev["kind"] == "field":
                empty_value = prev["text"].rstrip().endswith("】")
                if empty_value or line["x"] < prev["x"] - 0.02:
                    prev["text"] += text
                    continue

        kind = "field" if starts_field else ("heading" if is_heading else "body")
        merged.append({
            "text": text, "page": line["page"], "y": line["y"],
            "x": line["x"], "h": line["h"], "kind": kind,
        })
    return merged


def looks_like_ingredients(text: str) -> bool:
    """True when a fragment reads as a dosage list rather than a formula name."""
    if not text or len(text) < 4:
        return False
    return bool(UNIT_RE.search(text) or AMOUNT_RE.search(text))


def split_formula_line(payload: str) -> tuple[str, str]:
    """Separate the formula name from an inline ingredient list.

    Most entries are written as

        【方16】 羊血米醋治疗便血

    but a minority drop the 【药方】 label entirely and put the ingredients
    straight after the number:

        【方1】 白芨适量，糯米100克，大枣5枚，蜂蜜25克。

    The second shape must not be mistaken for a long formula name.
    """
    payload = payload.strip()
    if not payload:
        return "", ""
    if not looks_like_ingredients(payload):
        return payload, ""

    # "白芨汤治疗咳嗽，白芨10克…" — keep the named prefix, take the rest.
    named = re.match(r"^(.*?(?:治疗|适用于|用于|治)[^，,。；;]*)[，,](.+)$", payload)
    if named and looks_like_ingredients(named.group(2)):
        return named.group(1).strip(), named.group(2).strip()

    # No name at all: the whole payload is the ingredient list.
    return "", payload


def snap_condition(name: str, canonical: list[str]) -> str:
    """Snap an OCR'd section heading onto the table-of-contents spelling."""
    if not canonical or name in canonical:
        return name
    match = difflib.get_close_matches(name, canonical, n=1, cutoff=0.72)
    return match[0] if match else name


def resolve_section(name: str, listed: list[str], cursor: int,
                    report: list[str], page_no: int) -> tuple[str, int]:
    """Resolve a body section heading against the chapter's contents list.

    Vision sometimes drops a glyph from a heading — 七四、癔病 comes through as
    "七四、 病" — leaving a one-character name that cannot be matched by string
    similarity. The contents list is the book's own section order, so when a
    heading is unreadable the next unvisited entry is the correct answer.

    Returns (section_name, new_cursor).
    """
    if not listed:
        return (name, cursor) if len(name) > 1 else (name, cursor)

    snapped = snap_condition(name, listed)
    if snapped != name or name in listed:
        return snapped, listed.index(snapped)

    if len(name) < 2:
        nxt = min(cursor + 1, len(listed) - 1)
        report.append(
            f"p{page_no} 标题不可辨 {name!r} -> 按目录顺序取 {listed[nxt]!r}")
        return listed[nxt], nxt

    return name, cursor


def parse_pages(pages: dict[int, dict], toc: dict[int, list[str]] | None = None
                ) -> tuple[list[dict], list[str], dict[int, int]]:
    toc = toc or {}
    records: list[dict] = []
    report: list[str] = []
    candidates: dict[int, int] = {}

    chapter = ""
    chapter_no = None
    section = ""
    section_no = None
    toc_cursor = -1
    current: dict | None = None
    counter = 0

    def close() -> None:
        nonlocal current
        if current and (current.get("ingredients") or current.get("usage")
                        or current.get("effect")):
            current.pop("_last_field", None)
            counter = len(records) + 1
            current["id"] = f"F{counter:04d}"
            current["source_refs"] = [{
                "source_id": "S01",
                "pdf_page": current["pdf_page"],
                "book_page": current.get("book_page"),
            }]
            records.append(current)
        current = None

    started = False
    for page_no in sorted(pages):
        body, footer_chapter, page_candidate = page_lines(pages[page_no])
        if page_candidate:
            candidates[page_no] = page_candidate

        if not started:
            if footer_chapter:
                started = True
                chapter = footer_chapter
                chapter_no = chapter_no_of(footer_chapter)
                toc_cursor = -1
            else:
                continue  # cover / TOC / preface
        elif footer_chapter:
            if footer_chapter != chapter:
                toc_cursor = -1  # a new chapter restarts the contents order
            chapter = footer_chapter
            chapter_no = chapter_no_of(footer_chapter)

        for line in merge_lines(body):
            text = line["text"]

            formula_match = FORMULA_RE.match(text)
            if formula_match:
                close()
                title, inline = split_formula_line(formula_match.group(2))
                current = {
                    "chapter": chapter,
                    "chapter_no": chapter_no,
                    "condition": section,
                    "condition_no": section_no,
                    "formula_no": int(unicodedata.normalize("NFKC", formula_match.group(1))),
                    "title": title,
                    "title_present": bool(title),
                    "name": re.split(r"(?:治疗|适用于|治)", title)[0].strip() or title,
                    "ingredients": inline,
                    "usage": "",
                    "effect": "",
                    "effect_label": "",
                    "extra": [],
                    "_last_field": "ingredients" if inline else "",
                    "pdf_page": page_no,
                    "book_page": None,
                    "raw": [],
                }
                current["raw"].append(text)
                continue

            # Section (condition) headings are centred and set in a larger
            # type size than the body text. They close the running formula.
            if text and not text.startswith("【"):
                section_match = SECTION_RE.match(text)
                if section_match and line["h"] >= 0.023 and line["x"] > 0.20:
                    name = clean_condition(text)
                    if len(name) <= 22:
                        close()
                        listed = toc.get(chapter_no or 0, [])
                        section, toc_cursor = resolve_section(
                            name, listed, toc_cursor, report, page_no)
                        section_no = text.split("、")[0].split(".")[0].strip()
                        continue

            field = match_field(text)
            if field and current is not None:
                label, value = field
                current["raw"].append(text)
                if label == "药方":
                    current["ingredients"] += value
                    current["_last_field"] = "ingredients"
                elif label == "制用法":
                    current["usage"] += value
                    current["_last_field"] = "usage"
                elif label == "效用":
                    current["effect"] += value
                    current["effect_label"] = "效用"
                    current["_last_field"] = "effect"
                continue

            if current is not None:
                current["raw"].append(text)
                # Continuation of the field that was last opened.
                target = current.get("_last_field") or "usage"
                if target == "ingredients":
                    current["ingredients"] += text
                elif target == "effect":
                    current["effect"] += text
                elif target == "extra" and current["extra"]:
                    current["extra"][-1]["text"] += text
                else:
                    current["usage"] += text
            else:
                report.append(f"p{page_no} orphan: {text[:60]}")

    close()
    return records, report, candidates


def assign_book_pages(records: list[dict], candidates: dict[int, int]) -> dict:
    """Derive the printed page number for every record from the front-matter offset.

    The printed page number is OCR'd page by page and is unreliable: Vision
    sometimes reads the bracket in the running footer ("妙用偏方秘方「59") as a
    digit, producing "159" instead of "59". What *is* stable is the constant
    offset between the PDF page and the printed page, so the offset is derived
    from the modal value across the whole book and then applied uniformly.

    Every record records whether its own footer confirmed the number.
    """
    offsets: dict[int, int] = {}
    for pdf_page, printed in candidates.items():
        offset = pdf_page - printed
        if 0 <= offset <= 40:
            offsets[offset] = offsets.get(offset, 0) + 1
    offset = max(offsets.items(), key=lambda item: item[1])[0] if offsets else 0

    confirmed = 0
    for record in records:
        printed = record["pdf_page"] - offset
        record["book_page"] = printed if printed >= 1 else None
        record["book_page_confirmed"] = candidates.get(record["pdf_page"]) == printed
        if record["book_page_confirmed"]:
            confirmed += 1
        for ref in record.get("source_refs", []):
            ref["book_page"] = record["book_page"]
    return {
        "offset": offset,
        "pages_with_footer": len(candidates),
        "records_confirmed": confirmed,
        "records_total": len(records),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-dir", default=str(DEFAULT_OCR_DIR))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--toc", default=str(SKILL_ROOT / "assets" / "toc.json"))
    args = parser.parse_args()

    pages = load_pages(Path(args.ocr_dir))
    if not pages:
        raise SystemExit("no OCR pages found")
    toc = parse_toc(pages)
    records, report, candidates = parse_pages(pages, toc)
    page_stats = assign_book_pages(records, candidates)

    toc_path = Path(args.toc) if args.toc else None
    if toc_path:
        toc_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "chapters": [
                {
                    "chapter_no": number,
                    "chapter": f"第{int_to_cn(number)}章 "
                               f"{CANONICAL_CHAPTERS.get(number, '')}".strip(),
                    "conditions": conditions,
                }
                for number, conditions in sorted(toc.items())
            ]
        }
        toc_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write(f"pages={len(pages)} records={len(records)}\n")
        handle.write(f"front_matter_offset={page_stats['offset']}\n")
        handle.write(f"footer_pages_read={page_stats['pages_with_footer']}\n")
        handle.write(f"book_page_confirmed={page_stats['records_confirmed']}"
                     f"/{page_stats['records_total']}\n")
        handle.write(f"missing_ingredients="
                     f"{sum(1 for r in records if not r['ingredients'])}\n")
        handle.write(f"missing_usage="
                     f"{sum(1 for r in records if not r['usage'])}\n")
        handle.write(f"missing_effect="
                     f"{sum(1 for r in records if not r['effect'])}\n")
        conditions = sorted({r["condition"] for r in records if r["condition"]})
        chapters = sorted({r["chapter"] for r in records if r["chapter"]})
        handle.write(f"chapters={len(chapters)}\n")
        for chapter in chapters:
            handle.write(f"  {chapter}\n")
        handle.write(f"conditions={len(conditions)}\n")
        for condition in conditions:
            count = sum(1 for r in records if r["condition"] == condition)
            handle.write(f"  {condition}: {count}\n")
        handle.write(f"orphan_lines={len(report)}\n")
        for line in report[:200]:
            handle.write(f"  {line}\n")

    print(f"pages={len(pages)} records={len(records)} orphans={len(report)} "
          f"offset={page_stats['offset']} "
          f"page_confirmed={page_stats['records_confirmed']}")
    print(f"written -> {out}")


if __name__ == "__main__":
    main()
