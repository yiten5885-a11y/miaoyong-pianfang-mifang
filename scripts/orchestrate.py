#!/usr/bin/env python3
"""多症状编排：用户一次提两个症状时，各给方案并说清叠加风险。

    from orchestrate import orchestrate_multi

单症状查询走原有 `improve.compose` 路径。当查询显式点名多个症状
（「感冒还嗓子疼」）且都命中原书小节时，本模块负责：

1. **按病症分组检索**：每个命中病症各取记载最全的前几道方，
   而不是把所有方混在一起排。
2. **冲突检测**（纯文本检索做不到的部分）：
   - 重复药材：两道方共用 ≥2 味药材（食材辅料排除）；
   - 酒精叠加：两道方都用酒送服；
   - 寒热相冲：一道性温、一道性凉。
3. **不静默丢方**：冲突的方照列，冲突点随方说明。
4. **试用秩序**：一次只试一道的纪律写进卡片。

保守原则：冲突检测建立在 `herbs.parse_ingredients` 的清洗结果上；
识别不出的按「无冲突」处理并在结果里注明数据限制。
"""

from __future__ import annotations

import re

from herbs import parse_ingredients
from trust import trust_score

# 出现在制用法里的酒类辅料。原书几乎都把送服用酒写在【制用法】而非
# 【药方】里（「黄酒送服」），所以酒精检测必须覆盖 usage。
ALCOHOL_HERBS = frozenset({"黄酒", "白酒", "米酒", "酒"})
# 食材辅料：出现重复不算用药冲突（炖一锅粥放两次糖不是事故）。
FOOD_AUXILIARIES = frozenset({
    "白糖", "红糖", "冰糖", "蜂蜜", "葱白", "生姜", "大蒜", "粳米",
    "糯米", "大米", "鸡蛋", "香油", "精盐", "食盐", "大枣", "红枣",
    "核桃", "芝麻", "花生", "淀粉",
})

# 寒热方向用词组而非单字：单字「寒」会把「散寒」（温性方）误判为寒性，
# 单字「热」会把「清热」（凉性方）误判为热性。
# 「解毒」不在表内——「发表解毒」常见于辛温解表剂的自述（原书神仙粥
# 「发表解毒,驱风散寒」实际是温性方），单看这两个字无法判断方向。
# 词表按真实语料覆盖度校准：温性词以 散寒/温中/温热 为主，凉性词以
# 清热/凉血/滋阴/清肺 为主。
HOT_WORDS = ("辛温", "温经", "温中", "祛寒", "散寒", "驱寒", "温热",
             "补阳", "助阳", "回阳", "辛热", "热性")
COLD_WORDS = ("清热", "清热解毒", "凉血", "滋阴", "清解", "微寒", "性凉",
              "生津", "润燥", "退热", "泻火", "清肺", "清火", "降火",
              "性寒")

# 冲突判定的最小共用药材数：单味共用很常见（甘草），≥2 才算值得提醒。
DUPLICATE_THRESHOLD = 2


def _formula_text(record: dict) -> str:
    return f"{record.get('ingredients') or ''} {record.get('usage') or ''}"


def _drinks_alcohol(record: dict) -> bool:
    """制用法或原料里出现酒类辅料即认为用酒（原书写在制用法里）。"""
    text = f"{record.get('ingredients') or ''} {record.get('usage') or ''}"
    return any(word in text for word in ALCOHOL_HERBS)


def _is_cooling(record: dict) -> bool:
    text = (record.get("effect") or "") + (record.get("usage") or "")
    return any(word in text for word in COLD_WORDS)


def _is_warming(record: dict) -> bool:
    text = (record.get("effect") or "") + (record.get("usage") or "")
    return any(word in text for word in HOT_WORDS)


def detect_conflicts(a: dict, b: dict) -> list[dict]:
    """两道方之间的冲突点。返回空列表表示未检出冲突。"""
    conflicts: list[dict] = []

    herbs_a = set(parse_ingredients(a))
    herbs_b = set(parse_ingredients(b))
    overlap = {h for h in (herbs_a & herbs_b)
               if h not in FOOD_AUXILIARIES}
    if len(overlap) >= DUPLICATE_THRESHOLD:
        conflicts.append({
            "kind": "duplicate_herbs",
            "herbs": sorted(overlap),
            "reason": "两道方都含有" + "、".join(sorted(overlap)) +
                      "，同时服用等于这几味药的用量翻倍。",
            "action": "错开日期服用，或选其中一道。",
        })

    if _drinks_alcohol(a) and _drinks_alcohol(b):
        conflicts.append({
            "kind": "alcohol_stacking",
            "reason": "两道方都建议用酒送服，酒精辅料会叠加。",
            "action": "不要同日叠加；用酒送服当天不喝第二道。",
        })

    if (_is_warming(a) and _is_cooling(b)) or \
            (_is_cooling(a) and _is_warming(b)):
        conflicts.append({
            "kind": "thermal_clash",
            "reason": "一道偏温性、一道偏凉性，方向相反，同用可能相互抵消。",
            "action": "优先处理更急的那个症状，另一个先通过饮食或就医。",
        })

    return conflicts


def section_top(records: list[dict], condition: str,
                per_limit: int = 2) -> list[dict]:
    """一个病症小节内，按来源可信度优先取前几道。"""
    pool = [r for r in records if r.get("condition") == condition]
    pool.sort(key=lambda r: (-trust_score(r),
                             r.get("pdf_page") or 0,
                             r.get("formula_no") or 0))
    return pool[:per_limit]


def orchestrate_multi(query: str, records: list[dict],
                      conditions: list[str],
                      per_limit: int = 2) -> dict:
    """为多个命中病症各配方案，并做两两冲突检测。"""
    sections = []
    for condition in conditions:
        top = section_top(records, condition, per_limit)
        if not top:
            continue
        sections.append({
            "condition": condition,
            "formulas": [
                {
                    "id": r["id"],
                    "chapter": r.get("chapter", ""),
                    "condition": r.get("condition", ""),
                    "title": r["title"],
                    "ingredients": r["ingredients"],
                    "usage": r["usage"],
                    "effect": r["effect"],
                    "trust_score": trust_score(r),
                    "herbs": parse_ingredients(r),
                }
                for r in top
            ],
        })

    # 两两冲突（每节的第一道为代表方——那是用户先会看的那道）
    conflicts = []
    representatives = [s["formulas"][0] for s in sections if s["formulas"]]
    for i in range(len(representatives)):
        for j in range(i + 1, len(representatives)):
            found = detect_conflicts(
                _record_of(representatives[i], records),
                _record_of(representatives[j], records),
            )
            for item in found:
                conflicts.append({
                    "between": [
                        representatives[i]["title"],
                        representatives[j]["title"],
                    ],
                    **item,
                })

    return {
        "query": query,
        "sections": sections,
        "conflicts": conflicts,
        "trial_rule": {
            "note": "每次只试一道；第一道试 1 天看反应，耐受再续到第 3 天，"
                    "第 3 天反馈后再定，不要同时上两道。",
            "must_not": "不自行加量，不同时试多道，症状加重立即停用。",
        },
        "data_limit": "冲突检测基于原书原料文本的机械比对，"
                      "原书未写禁忌不等于没有禁忌。",
    }


def _record_of(formula: dict, records: list[dict]) -> dict:
    return next((r for r in records if r["id"] == formula["id"]), formula)
