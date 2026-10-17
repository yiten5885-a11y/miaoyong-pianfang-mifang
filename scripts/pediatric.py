#!/usr/bin/env python3
"""儿童剂量安全层：成人方不能直接套给儿童。

    from pediatric import detect_child_context, pediatric_gate

原书把小儿方单独放在第五章（小儿发热、小儿咳喘、小儿泄泻、小儿惊风等
15 个小节），成人章节的剂量是给成人写的。实测：15 条家长口语查询中
8 条命中成人节（「孩子咳嗽老不好」→ 成人「咳嗽」小节），而成人小节的
制用法里没有任何儿童剂量说明。

本模块做两件事，都**不自动换算剂量**——按成人方折算儿童用量是伤害
发生的地方，原书写多少就展示多少，只加边界提示：

1. 识别查询里的儿童语境（孩子、宝宝、婴儿、几岁……）。
2. 命中成人小节时输出闸门信息：明确告知这是成人方、原书儿科在
   第五章、给出同症状族的儿科小节候选。用户仍能看到这道方作为
   资料参考，但剂量警示出现在回答最前面。

命中儿科小节时闸门静默（儿科小节自己的制用法已含儿童剂量说明，
实测覆盖率 89%）。
"""

from __future__ import annotations

# 儿童语境标记。与 search.py 的 CHILD_MARKERS 保持一致（儿科加权用）。
CHILD_MARKERS = (
    "孩子", "小孩", "宝宝", "婴儿", "儿童", "幼儿", "闺女", "儿子",
    "女儿", "小朋友", "新生儿", "娃", "孙子", "孙女",
)

# 明确的年龄表述（「3 岁」「两岁半」「月龄」），是更强的儿童信号。
AGE_RE = __import__("re").compile(
    r"\d+\s*岁|[一二两三四五六七八九十]+\s*岁|月龄|个月大|周龄"
)

PEDIATRIC_CHAPTER = "第五章 小儿科疾病"

# 症状族 → 儿科小节。用于跨节命中时给用户指路。
SYMPTOM_FAMILY_TO_PEDIATRIC = {
    "咳嗽": "小儿咳喘",
    "咳喘": "小儿咳喘",
    "喘": "小儿咳喘",
    "发烧": "小儿发热",
    "发热": "小儿发热",
    "感冒": "小儿感冒",
    "伤风": "小儿感冒",
    "拉肚子": "小儿泄泻",
    "腹泻": "小儿泄泻",
    "痢疾": "小儿痢疾",
    "呕吐": "小儿呕吐和吐乳",
    "遗尿": "小儿遗尿",
    "尿床": "小儿遗尿",
    "夜啼": "小儿夜啼",
    "哭闹": "小儿夜啼",
    "厌食": "小儿厌食和异食癖",
    "积食": "小儿疳积",
    "疳积": "小儿疳积",
    "惊风": "小儿惊风",
    "抽搐": "小儿惊风",
    "多动": "小儿多动症",
    "汗": "小儿汗证",
    "流涎": "小儿流涎",
    "脱肛": "小儿脱肛",
}


def detect_child_context(query: str) -> bool:
    """查询是否指向儿童。任一儿童标记或明确年龄表述都算。"""
    if any(marker in query for marker in CHILD_MARKERS):
        return True
    return bool(AGE_RE.search(query))


def pediatric_sections_for(query: str, records: list[dict]) -> list[str]:
    """按症状族找原书第五章里可能对应的小节（只列真实存在的）。"""
    available = {
        r.get("condition") for r in records
        if r.get("chapter") == PEDIATRIC_CHAPTER and r.get("condition")
    }
    hits: list[str] = []
    for keyword, section in SYMPTOM_FAMILY_TO_PEDIATRIC.items():
        if keyword in query and section in available and section not in hits:
            hits.append(section)
    return hits


def pediatric_gate(query: str, primary: dict,
                   records: list[dict]) -> dict | None:
    """儿童语境 + 成人小节命中时的闸门载荷；否则返回 None。

    返回 None 的两种情况：查询与儿童无关；或命中本来就是儿科小节。
    """
    if not detect_child_context(query):
        return None
    if primary.get("chapter") == PEDIATRIC_CHAPTER:
        return None

    suggestions = pediatric_sections_for(query, records)
    if suggestions:
        next_step = ("原书把小儿方放在第五章。你可以先看这几个小节："
                     + "、".join(suggestions)
                     + "。没有合适的或症状较重，带孩子就医，"
                     "不要按成人剂量自行折算。")
    else:
        next_step = ("原书儿科小节里没有与这个症状直接对应的内容，"
                     "带孩子就医，不要按成人剂量自行折算。")
    return {
        "is_child": True,
        "adult_section": True,
        "matched_section": primary.get("condition"),
        "message": "这道方出自原书成人章节，剂量是给成人写的，"
                   "不能直接套用到孩子身上。",
        "pediatric_chapter": "第五章 小儿科疾病",
        "pediatric_sections": suggestions,
        "next_step": next_step,
    }
