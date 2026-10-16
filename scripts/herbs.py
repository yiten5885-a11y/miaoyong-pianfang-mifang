#!/usr/bin/env python3
"""药材名清洗：把 OCR 与版式残留从原料串里剥掉，得到干净的药材集合。

    from herbs import parse_ingredients

为什么单独做一层：原书的原料串是给「人」读的版式，混着剂量、制法前缀、
「各」字等分标记，还有 OCR 粘连。直接拿来做药材共现统计或冲突检测，
既会误报（把「甘草各」当成一味独立药材）也会漏报（同名药材出现在两个
略有不同的写法里就匹配不上）。

本模块只做**解析层的清洗**，绝不改动 records.jsonl 的原文转录——原书
怎么写就怎么存，清洗只在取用时发生。

清洗规则（保守优先，宁缺毋滥）：
1. 剥掉药名末尾的「各」：原书「生姜、甘草各 6 克」的「各」是等分标记，
   OCR 把它粘进了前一个药名（「甘草各」）。这是全书系统性现象，
   影响约 50 个高频药名。
2. 剔除纯泛称：调料、味精、湿淀粉、作料、配料、佐料——这些名字不指向
   任何具体药材，留着只会污染统计。
3. 长度不足 2 字的丢弃：「地各」剥完是「地」，无法判断它到底是什么，
   与其猜一个药材名进去，不如明确丢弃（宁可说不知道）。

注意：白糖、红糖、蜂蜜、黄酒、葱白这些**不是**噪声——它们是药膳方
真实的辅料（黄酒送服、蜂蜜调和、葱白发汗都是正经用法），必须保留。
"""

from __future__ import annotations

import re

# 不指向任何具体药材的纯泛称，统计时剔除。
NOISE_WORDS = frozenset({
    "调料", "味精", "湿淀粉", "作料", "配料", "佐料", "调味品",
})

# 原料串里需要剥掉的噪音片段：剂量、句式前缀、等分标记。
# 注意：生/熟/干**不**在前缀表里——「生姜」「干姜」「熟地」「生大黄」
# 都是完整药名，无脑剥会把它们削成单字丢弃。
_PREFIX_RE = re.compile(r"^(?:各|共|用|取|鲜|炒|煅|炙|酒|醋)+")
_DOSE_RE = re.compile(
    r"[\d\.．～~～\-—至到]+\s*(?:克|g|G|毫升|ml|ML|两|钱|分|枚|个|片|滴|"
    r"匙|盅|碗|握|把|段|条|只|朵|粒|张|寸|杯|剂|丸|包|根|斤|适量|少许|"
    r"若干|酌量|等分|各等量).*$"
)
_SUFFIX_RE = re.compile(r"(?:适量|少许|若干|酌量|等分|各等量)$")
# 括号注释（如「（后下）」「（烊化）」）。
_PAREN_RE = re.compile(r"[（(][^)）]*[)）]")


def clean_herb_name(raw: str) -> str | None:
    """把一段原料碎片清洗成药材名；返回 None 表示这不是可用的药材名。

    清洗顺序：剥括号注释 → 剥剂量 → 剥制法前缀 → 剥等分后缀 → 剥「各」尾缀
    → 剔除泛称 → 长度校验。
    """
    name = _PAREN_RE.sub("", raw)
    name = _DOSE_RE.sub("", name)
    name = name.strip(" 　,，、。；;")
    name = _PREFIX_RE.sub("", name).strip()
    name = _SUFFIX_RE.sub("", name).strip()

    # 「各」尾缀：原书「甘草各 6 克」的等分标记被 OCR 粘进了药名。
    # 剥掉后剩单字的（「地各」→「地」）由长度校验丢弃——无法判断是
    # 生地还是熟地，与其猜，不如丢掉。
    if name.endswith("各") and len(name) > 1:
        name = name[:-1].strip()

    if not name or name in NOISE_WORDS:
        return None
    if len(name) < 2:
        return None
    if any(ch.isdigit() for ch in name):
        return None
    return name


def parse_ingredients(record: dict) -> list[str]:
    """从一条记录的原料串里解析出干净的药材名列表（保序去重）。

    不修改记录本身；原文仍以 `record["ingredients"]` 为准。
    """
    text = record.get("ingredients") or ""
    seen: list[str] = []
    for piece in re.split(r"[，,、；;。\n]", text):
        name = clean_herb_name(piece)
        if name and name not in seen:
            seen.append(name)
    return seen


def ingredient_counter(records: list[dict]) -> dict[str, int]:
    """全体记录的药材频次。用于共现分析、冲突检测等统计用途。"""
    from collections import Counter

    counter: Counter[str] = Counter()
    for record in records:
        counter.update(parse_ingredients(record))
    return dict(counter)


def noise_report(records: list[dict]) -> dict:
    """清洗效果报告：清洗前、清洗后、各剔除了什么。

    供维护者核对清洗是否过度或不足（见 references/maintenance.md）。
    """
    from collections import Counter

    raw_counter: Counter[str] = Counter()
    clean_counter: Counter[str] = Counter()
    dropped: Counter[str] = Counter()
    stripped_ge: Counter[str] = Counter()

    for record in records:
        text = record.get("ingredients") or ""
        for piece in re.split(r"[，,、；;。\n]", text):
            raw = piece.strip(" 　,，、。；;")
            if not raw or any(ch.isdigit() for ch in raw):
                continue
            raw_counter[raw] += 1
            name = clean_herb_name(piece)
            if name is None:
                dropped[raw] += 1
            else:
                clean_counter[name] += 1
                if name != raw:
                    stripped_ge[raw] += 1

    return {
        "raw_names": len(raw_counter),
        "clean_names": len(clean_counter),
        "dropped_names": len(dropped),
        "dropped_top": dropped.most_common(15),
        "ge_stripped": len(stripped_ge),
        "ge_stripped_top": stripped_ge.most_common(15),
    }
