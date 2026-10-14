#!/usr/bin/env python3
"""Deterministic retrieval over the packaged formula records.

Usage
-----
    python3 scripts/search.py --query "老是咳嗽有痰"
    python3 scripts/search.py --condition 咳嗽 --limit 5
    python3 scripts/search.py --list-conditions
    python3 scripts/search.py --stats

The script never calls a model. It returns the ranked source records so the
host assistant can shape the answer; it also returns the safety annotation so
the assistant does not have to re-derive it.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDS = SKILL_ROOT / "assets" / "records.jsonl"

sys.path.insert(0, str(SKILL_ROOT / "scripts"))
from safety import scan_herbs, worst_level  # noqa: E402

STOP_GRAMS = {
    "什么", "哪些", "怎么", "如何", "是否", "有没有", "多少", "需要", "可以",
    "适合", "一下", "请问", "偏方", "秘方", "验方", "方子", "原书", "书上",
    "治疗", "治一下", "方法", "办法", "帮我", "我想", "最近", "一直",
}

# Colloquial phrasing -> canonical condition name in the book.
SYNONYMS: dict[str, str] = {
    "感冒": "感冒", "受凉": "感冒", "伤风": "感冒", "着凉": "感冒",
    "咳嗽": "咳嗽", "咳痰": "咳嗽", "干咳": "咳嗽", "老咳": "咳嗽",
    "百日咳": "百日咳", "哮喘": "哮喘", "气喘": "哮喘", "支气管哮喘": "支气管哮喘",
    "气管炎": "支气管炎", "支气管炎": "支气管炎", "支气管扩张": "支气管扩张",
    "肺脓肿": "肺脓肿", "肺结核": "肺结核", "肺炎": "肺炎",
    "胃痛": "胃痛", "胃疼": "胃痛", "胃炎": "胃炎", "慢性胃炎": "慢性胃炎",
    "胃溃疡": "胃及十二指肠溃疡", "十二指肠溃疡": "胃及十二指肠溃疡",
    "胃下垂": "胃下垂", "打嗝": "呃逆", "呃逆": "呃逆", "呕吐": "呕吐",
    "拉肚子": "腹泻", "腹泻": "腹泻", "痢疾": "痢疾", "便秘": "便秘",
    "便血": "便血", "消化不良": "消化不良", "肠梗阻": "肠梗阻",
    "胆囊炎": "胆囊炎", "胆石症": "胆石症", "黄疸": "黄疸", "肝炎": "肝炎",
    "肝硬化": "肝硬化", "脂肪肝": "脂肪肝", "腹水": "浮肿、腹水",
    "心律不齐": "心律失常", "心律失常": "心律失常", "心悸": "心悸",
    "心绞痛": "心绞痛", "冠心病": "冠心病", "高血压": "高血压",
    "低血压": "低血压", "贫血": "贫血", "白血病": "白血病", "紫癜": "紫癜",
    "中风": "脑中风", "脑中风": "脑中风", "尿道炎": "尿道炎",
    "膀胱炎": "膀胱炎", "尿路结石": "尿路结石", "肾结石": "尿路结石",
    "尿血": "尿血", "遗尿": "遗尿", "尿潴留": "尿潴留",
    "小便不利": "小便不利", "小便不通": "小便不通", "尿毒症": "尿毒症",
    "肾病": "肾病综合征", "癫痫": "癫痫", "癔病": "癔病",
    "神经衰弱": "神经衰弱", "失眠": "神经衰弱", "精神分裂": "精神分裂症",
    "抑郁": "抑郁性神经症", "头痛": "头痛", "偏头痛": "头痛",
    "坐骨神经痛": "坐骨神经痛", "三叉神经痛": "三叉神经痛",
    "面瘫": "面神经炎", "糖尿病": "糖尿病", "肥胖": "肥胖症",
    "甲状腺": "甲状腺肿大", "腮腺炎": "流行性腮腺炎、扁桃体炎",
    "扁桃体炎": "流行性腮腺炎、扁桃体炎", "淋巴结炎": "淋巴结核、慢性淋巴结炎",
    "疝气": "疝气", "阑尾炎": "阑尾炎", "脉管炎": "脉管炎", "丹毒": "丹毒",
    "烫伤": "水火烫伤", "烧伤": "水火烫伤", "褥疮": "褥疮",
    "蛇咬": "蛇咬伤", "破伤风": "破伤风", "脑震荡": "脑震荡",
    "乳腺炎": "乳腺炎（乳痛）", "痔疮": "痔疮", "鸡眼": "鸡眼",
    "跌打": "跌打损伤", "骨结核": "骨结核", "骨髓炎": "骨髓炎",
    "阳痿": "阳痿", "早泄": "早泄", "遗精": "遗精", "不射精": "不射精症",
    "逆行射精": "逆行射精", "无精": "无精子症", "少精": "少精子症",
    "死精": "死精子症", "精液不液化": "精液不液化", "前列腺炎": "前列腺炎",
    "前列腺增生": "前列腺增生症", "睾丸炎": "睾丸炎",
    "月经不调": "月经先后不定期", "痛经": "痛经", "闭经": "闭经",
    "崩漏": "崩漏", "子宫肌瘤": "子宫肌瘤", "阴道炎": "阴道炎",
    "盆腔炎": "盆腔炎", "流产": "先兆流产", "习惯性流产": "习惯性流产",
    "妊娠呕吐": "妊娠呕吐", "产后缺乳": "产后缺乳", "回乳": "回乳",
    "更年期": "更年期综合症", "小儿发热": "小儿发热", "小儿感冒": "小儿感冒",
    "小儿惊风": "小儿惊风", "小儿腹泻": "小儿泄泻", "小儿遗尿": "小儿遗尿",
    "小儿夜啼": "小儿夜啼", "小儿厌食": "小儿厌食和异食癖",
    "中耳炎": "中耳炎", "耳鸣": "耳鸣", "鼻炎": "鼻炎", "鼻出血": "鼻出血",
    "咽喉炎": "咽喉炎", "牙痛": "牙痛", "牙周炎": "牙周炎",
    "口腔溃疡": "口腔溃疡", "口臭": "口臭", "湿疹": "湿疹",
    "荨麻疹": "荨麻疹", "牛皮癣": "银屑病", "皮肤瘙痒": "皮肤瘙痒",
    "痱子": "痱子", "脱发": "脱发", "白发": "白发",
}


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value)).lower()
    return "".join(ch for ch in text if ch.isalnum() or "\u3400" <= ch <= "\u9fff")


def grams(text: str, sizes=(2, 3, 4)) -> set[str]:
    normalized = normalize(text)
    result: set[str] = set()
    for size in sizes:
        for index in range(max(0, len(normalized) - size + 1)):
            gram = normalized[index:index + size]
            if gram not in STOP_GRAMS:
                result.add(gram)
    return result


def load_records(path: Path = DEFAULT_RECORDS) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(
            f"资料库未安装：{path}。请先接入拥有使用许可的 records.jsonl；"
            "不要用未获授权的 PDF、页图或转录替代。"
        )
    records: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{number}: {exc}") from exc
    return records


def field_text(record: dict, field: str) -> str:
    return record.get(field) or ""


def searchable(record: dict) -> str:
    parts = [
        field_text(record, "condition"),
        field_text(record, "title"),
        field_text(record, "name"),
        field_text(record, "ingredients"),
        field_text(record, "usage"),
        field_text(record, "effect"),
    ]
    return normalize(" ".join(parts))


def score(record: dict, query: str, query_grams: set[str]) -> float:
    condition = normalize(field_text(record, "condition"))
    title = normalize(field_text(record, "title"))
    name = normalize(field_text(record, "name"))
    effect = normalize(field_text(record, "effect"))
    body = searchable(record)

    value = 0.0
    normalized_query = normalize(query)
    if condition and condition == normalized_query:
        value += 60.0
    elif condition and condition in normalized_query:
        value += 45.0
    elif normalized_query and normalized_query in condition:
        value += 30.0
    if name and name == normalized_query:
        value += 25.0
    elif name and (name in normalized_query or normalized_query in name):
        value += 12.0
    if title and normalized_query and normalized_query in title:
        value += 10.0
    if effect and normalized_query and normalized_query in effect:
        value += 8.0

    body_grams = grams(body)
    overlap = query_grams & body_grams
    value += len(overlap) * 0.6
    return value


def resolve_conditions(query: str, conditions: list[str]) -> list[str]:
    """Map a colloquial query onto book condition names."""
    hits: list[str] = []
    normalized_query = normalize(query)
    for phrase, condition in sorted(SYNONYMS.items(), key=lambda kv: -len(kv[0])):
        if phrase in query or normalize(phrase) in normalized_query:
            if condition in conditions and condition not in hits:
                hits.append(condition)
    for condition in conditions:
        if normalize(condition) in normalized_query and condition not in hits:
            hits.append(condition)
    return hits


def annotate(record: dict) -> dict:
    herbs = scan_herbs(f"{record.get('ingredients', '')} {record.get('usage', '')}")
    return {
        "id": record.get("id"),
        "chapter": record.get("chapter"),
        "condition": record.get("condition"),
        "condition_no": record.get("condition_no"),
        "formula_no": record.get("formula_no"),
        "title": record.get("title"),
        "name": record.get("name"),
        "ingredients": record.get("ingredients"),
        "usage": record.get("usage"),
        "effect": record.get("effect"),
        "effect_label": record.get("effect_label"),
        "extra": record.get("extra", []),
        "pdf_page": record.get("pdf_page"),
        "book_page": record.get("book_page"),
        "source_refs": record.get("source_refs", []),
        "risk_herbs": herbs,
        "risk_level": worst_level(herbs),
    }


def run_search(query: str, records: list[dict], limit: int = 5,
               chapter: str | None = None,
               condition: str | None = None) -> dict:
    conditions = sorted({r.get("condition", "") for r in records if r.get("condition")})
    matched_conditions = [condition] if condition else resolve_conditions(query, conditions)

    pool = records
    if chapter:
        pool = [r for r in pool if chapter in (r.get("chapter") or "")]
    if matched_conditions:
        narrowed = [r for r in pool if r.get("condition") in matched_conditions]
        if narrowed:
            pool = narrowed

    query_grams = grams(query)
    ranked = sorted(
        ((score(r, query, query_grams), r) for r in pool),
        key=lambda item: (-item[0], item[1].get("pdf_page") or 0,
                          item[1].get("formula_no") or 0),
    )
    results = [annotate(r) for s, r in ranked[:limit] if s > 0]
    if not results:
        results = [annotate(r) for _, r in ranked[:limit]]

    return {
        "query": query,
        "matched_conditions": matched_conditions,
        "available_conditions": conditions if not matched_conditions else [],
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--condition", default=None)
    parser.add_argument("--chapter", default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--records", default=str(DEFAULT_RECORDS))
    parser.add_argument("--list-conditions", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    records = load_records(Path(args.records))

    if args.stats:
        conditions = {r.get("condition") for r in records}
        chapters = {r.get("chapter") for r in records}
        print(json.dumps({
            "records": len(records),
            "chapters": len(chapters),
            "conditions": len(conditions),
            "risky_records": sum(
                1 for r in records if scan_herbs(r.get("ingredients", "") or "")
            ),
        }, ensure_ascii=False, indent=2))
        return

    if args.list_conditions:
        grouped: dict[str, list[str]] = {}
        for record in records:
            grouped.setdefault(record.get("chapter") or "未归类", [])
            condition = record.get("condition") or "未归类"
            if condition not in grouped[record.get("chapter") or "未归类"]:
                grouped[record.get("chapter") or "未归类"].append(condition)
        print(json.dumps(grouped, ensure_ascii=False, indent=2))
        return

    if not args.query and not args.condition:
        parser.error("需要 --query 或 --condition")

    payload = run_search(args.query, records, args.limit, args.chapter, args.condition)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
