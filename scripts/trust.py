#!/usr/bin/env python3
"""来源可信度分层：原书对每一条写得全不全，直接告诉用户。

    from trust import trust_detail

原书 2395 条记录并非等质：有的条目方名、证型、剂量、做法、效用一应俱全，
有的只有一句话。把它们平铺给用户，等于让用户自己在沙子里挑金子。本模块按
**原书自身的字段完整度**给每条打一个 0-5 分的来源完整度，并输出用户可读的
描述。分数只描述「原书写了多少」，**不代表疗效、安全性或任何评价**。

打分维度（全部来自原书转录，不做任何推断补写）：
    有方名           +1
    含证型/辨证语言  +2   原书自己写了「风寒型」「症见……恶寒」这类描述
    含明确剂量       +1   原料里有「10克」「3枚」这类数字
    三字段齐全       +1   原料、制用法、效用三者都有

用户可读分档（不暴露分数与字段名，见 references/answer-design.md）：
    5  原书对这一条记得最全
    4  原书记载较全
    3  原书只记了主要信息
    2  原书记载较少
    ≤1 原书仅一句话，缺方名
"""

from __future__ import annotations

import re

# 原书里出现的显式证型表述（「X型」）与辨证关键词。
PATTERN_RE = re.compile(r"[\u4e00-\u9fff]{2,6}型")
SYNDROME_WORDS = (
    "风寒", "风热", "风湿", "风燥", "湿热", "寒湿", "暑湿", "痰湿", "痰热",
    "阴虚", "阳虚", "气虚", "血虚", "气血两虚", "气滞", "血瘀", "血热",
    "虚寒", "实热", "脾虚", "肾虚", "肝郁", "肺热", "胃寒", "胃热",
    "寒凝", "冲任", "气阴两虚", "阴阳两虚", "心脾两虚", "脾肾阳虚",
    "症见", "脉紧", "脉浮", "脉细", "苔白", "苔黄", "苔腻",
)

# 明确剂量：数字 + 常见计量单位。
DOSE_RE = re.compile(
    r"\d+\s*(?:克|g|G|毫升|ml|ML|两|钱|分|枚|个|片|滴|匙|盅|碗|握|把|段)"
)

# 分档阈值与用户可读描述。
LEVELS = {
    5: ("原书对这一条记得最全",
        "方名、证型、剂量、做法、效用都齐了"),
    4: ("原书记载较全",
        "主要信息齐全，少量细节原书没写"),
    3: ("原书只记了主要信息",
        "缺证型或剂量，功效描述比较简单"),
    2: ("原书记载较少",
        "没有证型与剂量，效用描述很简略"),
    1: ("原书仅一句话，缺方名",
        "原书只留了一句效用，无法核对更多细节"),
    0: ("原书仅一句话，缺方名",
        "原书只留了一句效用，无法核对更多细节"),
}


def has_pattern(record: dict) -> bool:
    """原书是否自己写了证型或辨证描述。"""
    text = record.get("effect") or ""
    return bool(PATTERN_RE.search(text)) or any(
        word in text for word in SYNDROME_WORDS
    )


def has_dose(record: dict) -> bool:
    """原料里是否带明确数字剂量。"""
    return bool(DOSE_RE.search(record.get("ingredients") or ""))


def trust_score(record: dict) -> int:
    """0-5 的来源完整度。描述原书写了多少，不代表任何评价。"""
    score = 0
    if record.get("title_present"):
        score += 1
    if has_pattern(record):
        score += 2
    if has_dose(record):
        score += 1
    if (record.get("ingredients") and record.get("usage")
            and record.get("effect")):
        score += 1
    return score


def trust_label(score: int) -> str:
    """分数的用户可读档位名。"""
    return LEVELS.get(max(score, 0), LEVELS[0])[0]


def trust_note(score: int) -> str:
    """档位的一句展开说明。"""
    return LEVELS.get(max(score, 0), LEVELS[0])[1]


def trust_detail(record: dict) -> dict:
    """给回答层用的完整度载荷。

    只暴露用户可读的字段；`score` 保留在内部键 `_score` 供排序使用，
    渲染层不展示它（见 references/answer-design.md）。
    """
    score = trust_score(record)
    return {
        "_score": score,
        "label": trust_label(score),
        "note": trust_note(score),
    }


def section_trust_overview(records: list[dict]) -> dict:
    """一个病症小节的整体完整度概况。

    让回答能说「这一节 8 道方里 2 道原书写得最全」，
    而不是把 8 道方等质平铺。
    """
    scored = [(trust_score(r), r) for r in records]
    total = len(scored)
    if not total:
        return {"total": 0, "full": 0, "note": ""}
    full = sum(1 for score, _ in scored if score >= 4)
    top = max(score for score, _ in scored)
    if top >= 5:
        note = "这一节里有原书记载最全的方子"
    elif top >= 4:
        note = "这一节的方子记载都比较简"
    elif top >= 2:
        note = "这一节原书大多只记了主要信息"
    else:
        note = "这一节原书记载很少"
    return {"total": total, "full": full, "top_score": top, "note": note}
