#!/usr/bin/env python3
"""证型抽取与归一化：把原书的「X型」表述变成可检索的证型簇。

    from patterns import extract_patterns, build_pattern_index

原书在【效用】里常用「适用于X型」「症见……」描述每一道方针对的证型。
这是 v2.0 辨证收敛问诊的数据基础：先按证型把一节里的方归簇，再把每簇的
「症见」记述转成判别问题。

三个处理阶段：

1. **前缀剥离**：「用于气滞血瘀型」→「气滞血瘀型」。原书的前缀有
   「用于」「适用于」「主治」「宜于」「辨证」等，是句式不是证型名。
2. **OCR 归一**：原书是扫描件，「察湿攪滞型」实为「寒湿凝滞型」，
   「偏手气灣型」实为「偏于气滞型」。映射表只收实测出现的噪声。
3. **同义归并**：只合并最有把握的同义表述（肾阳不足 = 肾阳虚），
   不同侧重的表述（血瘀 vs 气滞血瘀 vs 瘀血停滞）**不强行合并**——
   原书写法不同，可能就是侧重点不同。

安全边界：证型是**原书的分类记述**，不是诊断。抽取模块不做任何
「用户属于某证型」的判断，只做文本归类。
"""

from __future__ import annotations

import re
from collections import defaultdict

# 【效用】里的显式证型表述：数字中文 + 2-6 字核心 + 「型」。
TYPE_RE = re.compile(r"[\u4e00-\u9fff]{2,6}型")

# 证型前缀：句式成分，不是证型名的一部分。
PREFIX_RE = re.compile(
    r"^(?:以及|并及|用于|适用于|主治|宜于|辨证|用于治疗|适用|针对|多见于|"
    r"常见于)+"
)

# 修饰前缀：原书常用「偏于X型」表示倾向，归一时保留核心。
HEDGE_RE = re.compile(r"^(?:偏于|偏|属于|属|以|乃)+")

# 贪心中文匹配会把前导连接字吃进证型名（「X型与肾阳不足型」→「与肾阳不足」）。
LEADING_CONNECTIVE_RE = re.compile(r"^(?:与|和|及|或|兼|有|又|并)+")

# 实测 OCR 噪声映射（扫描件特有，逐条核对过原书上下文）。
# 键保留原始错字形式——本步骤先于繁简归一步骤执行。
OCR_FIXES: dict[str, str] = {
    "察湿攪滞": "寒湿凝滞",   # 原书作「寒湿凝滞型」
    "手气灣": "气滞",         # 原书作「偏于气滞」
    "手气帶": "气滞",         # 同上，OCR 另一处错法
    "痡": "痛",               # 胀痡 → 胀痛
}

# 扫描件繁简混排：实测证型表述里出现的繁体字（虛×3、虧×2 等），
# 先归一为简体再走后续归并，否则「气血虛弱」与「气血虚弱」会分成两簇。
TRADITIONAL_TO_SIMPLIFIED = {
    "虛": "虚", "虧": "亏", "滯": "滞", "帶": "带", "風": "风",
    "濕": "湿", "氣": "气", "陰": "阴", "陽": "阳", "腎": "肾",
    "濁": "浊", "兩": "两", "蘊": "蕴", "結": "结",
}

# 有把握的同义归并（左右同义或原书交替使用）。
SYNONYM_GROUPS: list[tuple[str, ...]] = [
    ("肾阳不足", "肾阳虚", "肾阳虚衰", "命门火衰"),
    ("肾阴亏虚", "肾阴虚", "肾阴亏损", "肾阴不足"),
    ("瘀血停滞", "血瘀", "瘀血内阻"),
    ("气血虚弱", "气血两虚", "气血不足"),
    ("脾肾亏虚", "脾肾两虚", "脾肾虚弱"),
    ("心神不宁", "心神不安", "心神不交"),
    ("湿热下注", "下焦湿热", "湿热下注"),
    ("气滞血瘀", "气血瘀滞", "气滞血瘀"),
]


def normalize_pattern(text: str) -> str:
    """把一段证型表述归一成规范证型名。

    先提取「X型」的核心段（贪婪正则会把「用于」这类句式前缀吃进来），
    再剥前缀、做 OCR 归一与同义归并。
    """
    match = re.search(r"([\u4e00-\u9fff]{2,6})型", text)
    if not match:
        return ""
    name = match.group(1)
    name = PREFIX_RE.sub("", name)
    name = LEADING_CONNECTIVE_RE.sub("", name)
    name = HEDGE_RE.sub("", name)
    # 句内连证型（「气滞型和血瘀型」被贪心匹配成一段）：截到首个连接词。
    # 证型名本身不会含和/与/及/或，截断是安全的。
    head = re.split(r"[和与及或]", name, maxsplit=1)[0]
    if len(head) >= 2:
        name = head
    # 截断后可能残留「型」字（捕获组把型字本身也吃进了核心段）
    if "型" in name:
        name = name.split("型", 1)[0]
    # ① OCR 错字修复（原始错字键，先于繁简归一）
    for wrong, right in OCR_FIXES.items():
        if wrong and wrong in name:
            name = name.replace(wrong, right)
    # ② 繁简混排归一（同一节里「气血虛弱」与「气血虚弱」并存）
    name = "".join(TRADITIONAL_TO_SIMPLIFIED.get(ch, ch) for ch in name)
    name = name.strip("，,、；;。 ")
    for group in SYNONYM_GROUPS:
        if name in group:
            return group[0]
    return name


def extract_patterns(record: dict) -> set[str]:
    """从一条记录抽归一化证型集合（空集 = 原书未写证型）。"""
    text = record.get("effect") or ""
    patterns: set[str] = set()
    for match in TYPE_RE.findall(text):
        name = normalize_pattern(match)
        if len(name) >= 2:
            patterns.add(name)
    return patterns


def clue_text(record: dict) -> str:
    """记录里「症见……」的原文片段，用作判别性问题的素材。"""
    text = record.get("effect") or ""
    match = re.search(r"症见([^。；]{4,60})", text)
    return match.group(1).strip() if match else ""


def build_pattern_index(records: list[dict]) -> dict[str, dict]:
    """病症 → 证型簇索引。

    每个证型簇包含：方列表、该簇的判别性描述（取自簇内第一道高分方
    的「症见」原文）。没有证型表述的病症不出现在索引里——它们走普通
    检索路径，不会被伪装成「可以辨证」。
    """
    by_condition: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record.get("condition"):
            by_condition[record["condition"]].append(record)

    index: dict[str, dict] = {}
    for condition, items in by_condition.items():
        clusters: dict[str, list[dict]] = defaultdict(list)
        for record in items:
            for pattern in extract_patterns(record):
                clusters[pattern].append(record)
        if len(clusters) < 2:
            continue  # 不足两种证型：无法收敛，不进问诊路径
        # 簇内按完整度排序（v1.3 的分层复用）
        for pattern in clusters:
            clusters[pattern].sort(
                key=lambda r: (-_trust(r), r.get("pdf_page") or 0,
                               r.get("formula_no") or 0))
        index[condition] = {
            "condition": condition,
            "pattern_count": len(clusters),
            "clusters": {
                pattern: {
                    "formula_count": len(items),
                    "formulas": [
                        {"id": r["id"], "title": r["title"],
                         "ingredients": r["ingredients"],
                         "usage": r["usage"], "effect": r["effect"],
                         "trust_score": _trust(r)}
                        for r in items[:2]
                    ],
                    "clue": clue_text(items[0]),
                }
                for pattern, items in clusters.items()
            },
        }
    return index


def _trust(record: dict) -> int:
    from trust import trust_score
    return trust_score(record)
