#!/usr/bin/env python3
"""Compose a user-facing answer card from the packaged formula records.

    python3 scripts/improve.py --issue "最近老咳嗽，痰多，没有发烧"
    python3 scripts/improve.py --issue "孩子夜里尿床" --limit 3

The output is a JSON contract, not prose. The host assistant renders it into
the conversational answer described in references/answer-design.md.

Design rules enforced here
--------------------------
* The book's own wording is preserved under `original_*` keys and never
  rewritten into a promise of efficacy.
* The three-step preparation breakdown is derived from the book's own
  【制用法】 text only. Nothing is invented; if the text cannot be split
  confidently the steps degrade to a single verbatim step.
* The shopping list only lists ingredients that appear in the source. No
  substitute ingredient is ever suggested.
* A record whose ingredients carry a `high` risk tier is never presented as
  something the user can prepare themselves.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
from safety import (  # noqa: E402
    RED_FLAGS, scan_emergency, scan_herbs, scan_red_flags, scan_serious,
    worst_level,
)
from search import load_records, run_search  # noqa: E402

# Ingredients that are normally bought in a pharmacy / Chinese medicine shop.
# Checked before FOOD_WORDS because several herb names contain a food-like
# character (瓜蒌 contains 瓜, 牛膝 contains 牛).
KNOWN_HERBS = (
    "瓜蒌", "栝楼", "陈皮", "青皮", "甘草", "半夏", "茯苓", "白术", "苍术",
    "当归", "川芎", "白芍", "赤芍", "熟地", "生地", "黄芪", "党参", "人参",
    "丹参", "红花", "桃仁", "杏仁", "桔梗", "前胡", "贝母", "枇杷叶",
    "桑白皮", "地骨皮", "黄芩", "黄连", "黄柏", "栀子", "连翘", "金银花",
    "板蓝根", "蒲公英", "鱼腥草", "五味子", "山茱萸", "枸杞", "菊花",
    "薄荷", "荆芥", "防风", "羌活", "独活", "桂枝", "麻黄", "细辛",
    "干姜", "肉桂", "附子", "吴茱萸", "木香", "砂仁", "厚朴", "枳实",
    "枳壳", "大黄", "芒硝", "火麻仁", "郁李仁", "车前子", "泽泻", "猪苓",
    "滑石", "木通", "通草", "茵陈", "金钱草", "鸡内金", "山楂", "神曲",
    "麦芽", "莱菔子", "苏子", "白芥子", "葶苈子", "百部", "紫菀",
    "款冬花", "马兜铃", "白果", "鹿茸", "淫羊藿", "巴戟天", "肉苁蓉",
    "杜仲", "续断", "牛膝", "桑寄生", "何首乌", "女贞子", "旱莲草",
    "地榆", "槐花", "白及", "仙鹤草", "三七", "蒲黄", "艾叶", "延胡索",
    "川楝子", "香附", "郁金", "乳香", "没药", "穿山甲", "皂角刺",
    "夏枯草", "牡蛎", "龙骨", "珍珠母", "钩藤", "天麻", "僵蚕", "地龙",
    "石菖蒲", "远志", "酸枣仁", "柏子仁", "合欢皮", "夜交藤", "龙眼肉",
    "桑螵蛸", "覆盆子", "金樱子", "芡实", "莲子", "益智仁", "补骨脂",
    "菟丝子", "沙苑子", "韭菜子", "蛇床子", "苦参", "白鲜皮", "地肤子",
    "土茯苓", "萆薢", "石韦", "海金沙", "瞿麦", "萹蓄", "灯心草",
    "淡竹叶", "芦根", "天花粉", "知母", "石膏", "玄参", "麦冬", "天冬",
    "玉竹", "沙参", "百合", "阿胶", "龟板", "鳖甲", "紫河车", "乌梅",
    "诃子", "肉豆蔻", "赤石脂", "罂粟壳", "雄黄", "硫黄", "明矾",
    "硼砂", "冰片", "樟脑", "儿茶", "血竭", "麝香", "蟾酥", "斑蝥",
    "蜈蚣", "全蝎", "水蛭", "地鳖虫", "九香虫", "海马", "海龙",
    "白花蛇", "乌梢蛇", "蝉蜕", "蛇蜕", "露蜂房", "瓦楞子", "海螵蛸",
    "苏木", "刘寄奴", "骨碎补", "自然铜", "土鳖虫", "马钱子", "雷公藤",
    "青黛", "大青叶", "射干", "山豆根", "胖大海", "木蝴蝶", "胖大海",
    "苍耳子", "辛夷", "白芷", "藁本", "蔓荆子", "桑叶", "牛蒡子",
    "升麻", "柴胡", "葛根", "淡豆豉", "浮萍", "木贼", "谷精草",
    "决明子", "青葙子", "密蒙花", "夜明砂", "石决明", "磁石", "朱砂",
    "琥珀", "茯神", "柏子仁", "浮小麦", "麻黄根", "糯稻根", "乌贼骨",
)
HERB_MARKERS = (
    "参", "术", "芪", "苓", "芍", "芎", "归", "芩", "连", "柏", "栀", "萸",
    "楝", "草", "藤", "仁", "子", "根", "皮", "叶", "花", "实", "果", "核",
    "石", "砂", "黛", "珀", "胶", "酥", "蜕", "蝎", "蚣", "蛭", "蚕", "虫",
    "骨", "角", "甲", "霜", "丹", "散", "丸", "饮", "片", "露", "汁",
)
# Ingredients that are everyday food / market produce.
FOOD_WORDS = (
    "米", "面", "粉", "粥", "汤", "菜", "葱", "姜", "蒜", "醋", "盐", "糖",
    "油", "蛋", "鸡", "鸭", "鱼", "肉", "猪", "牛", "羊", "奶", "豆", "瓜",
    "果", "梨", "枣", "萝卜", "藕", "笋", "菇", "耳", "薯", "芋", "橘",
    "橙", "桃", "杏", "枣", "蜂蜜", "核桃", "芝麻", "花生", "莲", "麦",
)

STEP_HINTS = {
    "准备": ("洗净", "去核", "去皮", "切", "捣", "研", "磨", "晒干", "焙干",
             "研末", "过筛", "备", "取", "择"),
    "操作": ("煮", "炖", "煎", "熬", "蒸", "炒", "泡", "冲", "拌", "熬制",
             "大火", "小火", "煮沸", "焖", "烤", "焯", "炖煮"),
    "收尾": ("服", "饮", "吃", "涂", "敷", "贴", "洗", "含", "漱", "擦",
             "分次", "每日", "每天", "连服", "温服", "趁热"),
}


def split_ingredients(text: str) -> list[str]:
    """Split a 【药方】 string into individual ingredient phrases."""
    if not text:
        return []
    cleaned = re.sub(r"^[，,、。\s]+", "", text.strip())
    parts = re.split(r"[，,；;。]\s*", cleaned)
    result: list[str] = []
    for part in parts:
        part = part.strip(" 。；;，,、")
        if part and len(part) <= 60:
            result.append(part)
    return result


def classify_ingredient(phrase: str) -> str:
    if any(herb in phrase for herb in KNOWN_HERBS):
        return "pharmacy"
    if any(word in phrase for word in FOOD_WORDS):
        return "market"
    if any(marker in phrase for marker in HERB_MARKERS):
        return "pharmacy"
    return "unsure"


def build_shopping_list(ingredients: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {"pharmacy": [], "market": [], "unsure": []}
    for phrase in split_ingredients(ingredients):
        groups[classify_ingredient(phrase)].append(phrase)
    return groups


def build_steps(usage: str) -> list[dict]:
    """Split the book's own 【制用法】 text into up to three ordered steps."""
    if not usage:
        return []
    sentences = [s.strip() for s in re.split(r"[。；;]", usage) if s.strip()]
    if len(sentences) < 2:
        return [{"label": "制用法（原书原文）", "text": usage}]

    buckets: dict[str, list[str]] = {"准备": [], "操作": [], "收尾": []}
    for sentence in sentences:
        placed = False
        for label in ("准备", "操作", "收尾"):
            if any(hint in sentence for hint in STEP_HINTS[label]):
                buckets[label].append(sentence)
                placed = True
                break
        if not placed:
            buckets["操作"].append(sentence)

    steps: list[dict] = []
    for label in ("准备", "操作", "收尾"):
        if buckets[label]:
            steps.append({"label": label, "text": "；".join(buckets[label])})
    return steps or [{"label": "制用法（原书原文）", "text": usage}]


def risk_tier(record: dict, serious_note: str | None,
              flags: list[str]) -> dict:
    herbs = scan_herbs(f"{record.get('ingredients', '')} {record.get('usage', '')}")
    level = worst_level(herbs)
    if level == "high":
        colour, reason = "red", "含高毒或管制药材，不得自行配制。"
    elif serious_note:
        colour, reason = "red", serious_note
    elif level == "medium":
        colour, reason = "yellow", "含需炮制或限量药材，须药师确认。"
    elif flags:
        colour, reason = "yellow", "存在需要先咨询医师或药师的情况。"
    elif level == "caution":
        colour, reason = "yellow", "含需注意的常见原料，按提示核对。"
    else:
        colour, reason = "green", "原料为常见食材，仍须核对过敏史。"
    return {"colour": colour, "reason": reason, "herbs": herbs}


def compose(issue: str, records: list[dict], limit: int = 3) -> dict:
    emergency = scan_emergency(issue)
    flags = scan_red_flags(issue)

    if emergency:
        return {
            "mode": "emergency",
            "issue": issue,
            "emergency_terms": emergency,
            "message": "描述中出现需要现场处理的急症信号，本次不生成任何偏方。",
            "next_step": "请尽快到急诊或就近医院就诊；如已出现意识、呼吸或"
                         "大出血问题，直接拨打 120。",
            "results": [],
        }

    payload = run_search(issue, records, limit=limit)
    results = payload["results"]
    if not results:
        return {
            "mode": "no_match",
            "issue": issue,
            "message": "原书目录中没有与该描述直接对应的条目。",
            "available_conditions": payload["available_conditions"],
            "results": [],
        }

    primary = results[0]
    serious_note = scan_serious(primary.get("condition") or "")
    tier = risk_tier(primary, serious_note, flags)

    card = {
        "mode": "remedy",
        "issue": issue,
        "matched_conditions": payload["matched_conditions"],
        "primary": {
            "id": primary["id"],
            "condition": primary["condition"],
            "condition_no": primary["condition_no"],
            "chapter": primary["chapter"],
            "title": primary["title"],
            "name": primary["name"],
            "original_ingredients": primary["ingredients"],
            "original_usage": primary["usage"],
            "original_effect": primary["effect"],
            "effect_label": primary["effect_label"],
            "extra": primary.get("extra", []),
            "shopping_list": build_shopping_list(primary["ingredients"] or ""),
            "steps": build_steps(primary["usage"] or ""),
            "source_refs": primary["source_refs"],
        },
        "alternatives": [
            {
                "id": item["id"],
                "condition": item["condition"],
                "title": item["title"],
                "name": item["name"],
                "original_ingredients": item["ingredients"],
                "original_usage": item["usage"],
                "original_effect": item["effect"],
                "risk_level": item["risk_level"],
                "source_refs": item["source_refs"],
            }
            for item in results[1:]
        ],
        "safety": {
            "tier": tier,
            "red_flags": [
                {"flag": flag, "note": RED_FLAGS[flag]} for flag in flags
            ],
            "serious_note": serious_note,
            "stop_rules": [
                "出现皮疹、呼吸困难、面唇肿胀：立即停用并就医。",
                "出现明显恶心、呕吐、腹痛、腹泻：立即停用。",
                "原有症状加重或出现新症状：立即停用并就医。",
                "连续使用 3 天无改善或不适：停用并线下就诊。",
            ],
        },
        "trial_rhythm": {
            "note": "以下节奏是本 Skill 的保守试用规则，不是原书疗程。",
            "plan": "每次只试一道，先按原书用法试 1 天，观察有无不适；"
                    "耐受良好再连续用至第 3 天；第 3 天反馈后再决定是否续用。",
            "must_not": "不同时试两道，不自行加量，不延长到 7 天以上而不复诊。",
        },
        "followups": [
            f"要不要看「{primary['condition']}」这一节的其他方子？",
            "要不要我把采购清单按菜市场和药店分开列出来？",
            "要不要我把原书这页的原文和页码给你核对？",
        ],
    }
    return card


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", required=True)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--records", default=str(SKILL_ROOT / "assets" / "records.jsonl"))
    args = parser.parse_args()

    records = load_records(Path(args.records))
    card = compose(args.issue, records, args.limit)
    print(json.dumps(card, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
