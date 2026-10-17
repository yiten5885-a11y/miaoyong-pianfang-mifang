#!/usr/bin/env python3
"""辨证收敛问诊：命中病症后，先按原书分类型再给方。

    python3 scripts/inquire.py --issue "痛经"
    python3 scripts/inquire.py --issue "痛经" --answer "小腹发冷，按之更痛，经血黑有块"

交互模型
--------
原书不少小节把方剂按证型分写（「适用于气滞血瘀型」「症见……」）。
对这些小节，直接给「排名第一的方」等于让用户在 4 类里瞎猜。本模块做两轮：

- **第一轮（mode = inquire）**：列出原书自己写下的证型分类与每类的
  「症见」记述，让用户挑更接近的一类。
- **第二轮（--answer，mode = inquire_result）**：把用户的描述与每簇的
  症见记述做字符重叠匹配，收敛到最接近的簇，给出该簇的方。

收敛不出结果时（不匹配或跨簇打平）**不硬给**：不匹配就明说无法归类，
跨簇打平就把两类都摆出来让用户再挑。

安全边界（红线）
----------------
1. **不问诊**。问题来自原书「症见」原文，不自拟辨证标准，不问书上
   没有的维度（舌苔脉象用户答不上来也不追问）。
2. **不诊断**。输出只说「你的描述与原书某型的记述更接近」，
   绝不说「你是某型」「你这是某证」。
3. **不承诺疗效**。方照原书呈现，疗效口径与 remedy 模式一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from improve import compose  # noqa: E402
from patterns import build_pattern_index  # noqa: E402
from search import load_records, resolve_conditions_multi  # noqa: E402


# 低于该重叠分数的簇视为不匹配。
MIN_CLUSTER_SCORE = 2.0
# 最高分与次高分差值不足该比例视为「跨簇打平」。
AMBIGUITY_RATIO = 0.6


def _bigrams(text: str) -> set[str]:
    cleaned = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    if len(cleaned) < 2:
        return set(cleaned)
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def _score_answer(answer: str, clusters: dict) -> dict[str, float]:
    """用户回答与每个证型簇的症见记述的重叠得分。"""
    answer_grams = _bigrams(answer)
    if not answer_grams:
        return {}
    scores: dict[str, float] = {}
    for pattern, cluster in clusters.items():
        clue_grams = _bigrams(cluster.get("clue") or "")
        if not clue_grams:
            continue
        overlap = len(answer_grams & clue_grams)
        # 证型名本身也参与匹配（「气滞」两字出现在回答里是强信号）
        name_grams = _bigrams(pattern)
        overlap += len(answer_grams & name_grams) * 2
        scores[pattern] = float(overlap)
    return scores


def inquire(issue: str, records: list[dict]) -> dict:
    """第一轮：命中病症有证型分类时，给出判别性问题。"""
    card = compose(issue, records, 3, {})
    if card["mode"] != "remedy":
        return card  # 急症 / no_match / multi 等按原路径，不加问诊层

    condition = card["primary"]["condition"]
    index = build_pattern_index(records)
    entry = index.get(condition)
    if not entry:
        # 原书未按证型分述——照常给方，不伪装成可以辨证
        card["mode"] = "remedy"
        card["inquiry"] = None
        card["inquiry_note"] = "原书这一节没有按证型分述，直接给出本节方剂。"
        return card

    options = []
    for pattern, cluster in entry["clusters"].items():
        options.append({
            "pattern": pattern,
            "clue": cluster["clue"] or f"原书将该类记为「{pattern}」，未附症见描述。",
            "formula_count": cluster["formula_count"],
        })
    # 有症见描述的优先，其次按方数
    options.sort(key=lambda o: (bool(o["clue"].startswith("原书将该类")),
                                -o["formula_count"]))

    return {
        "mode": "inquire",
        "issue": issue,
        "matched_conditions": [condition],
        "question": "原书把这一节按几种情况分开写。你的情况更接近下面哪一类？"
                    "下面是原书记述的原文。",
        "options": options,
        "data_note": "这些分类是原书的记述，不是诊断；拿不准就选最接近的，"
                     "或直接说「拿不准」。",
        "inquiry_note": "这是原书自己的分类记述，不是对你的诊断。",
    }


def converge(issue: str, answer: str, records: list[dict]) -> dict:
    """第二轮：据用户回答收敛到证型簇。"""
    card = compose(issue, records, 3, {})
    if card["mode"] != "remedy":
        return card

    condition = card["primary"]["condition"]
    index = build_pattern_index(records)
    entry = index.get(condition)
    if not entry:
        return card

    scores = _score_answer(answer, entry["clusters"])
    if not scores or max(scores.values()) < MIN_CLUSTER_SCORE:
        # 描述与任何一簇都对不上：不硬归类
        card["mode"] = "remedy"
        card["inquiry"] = {
            "converged": False,
            "reason": "你的描述与原书各类型的记述都对不太上。",
        }
        card["inquiry_note"] = "无法按原书分类归类，下面是本节全部方剂。" \
                               "症状持续或加重请就医。"
        return card

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    if len(ranked) > 1 and ranked[1][1] >= best_score * AMBIGUITY_RATIO \
            and best_score - ranked[1][1] < 2.0:
        # 跨簇打平：两类都给出，不替用户决定
        tied = [best, ranked[1][0]]
        clusters = {p: entry["clusters"][p] for p in tied}
        card["mode"] = "inquire_ambiguous"
        card["inquiry"] = {
            "converged": False,
            "ambiguous": tied,
            "reason": "你的描述同时接近两类，我不替你定。",
        }
        card["tied_clusters"] = [
            {
                "pattern": p,
                "clue": c["clue"],
                "formulas": c["formulas"],
            }
            for p, c in clusters.items()
        ]
        card["inquiry_note"] = "两类都列给你，按更接近的挑，或就医确认。"
        return card

    cluster = entry["clusters"][best]
    primary = cluster["formulas"][0]
    card["mode"] = "inquire_result"
    card["inquiry"] = {
        "converged": True,
        "pattern": best,
        "matched_clue": cluster["clue"],
        "reason": f"你的描述与原书「{best}」的记述更接近。",
    }
    card["inquiry_note"] = "分类归自原书记述，不是诊断。这一类的方如下。"
    card["primary"] = {
        "id": primary["id"],
        "condition": condition,
        "title": primary["title"],
        "original_ingredients": primary["ingredients"],
        "original_usage": primary["usage"],
        "original_effect": primary["effect"],
        "trust": {"_score": primary["trust_score"]},
        "pattern": best,
    }
    alternatives = cluster["formulas"][1:]
    card["alternatives"] = [
        {
            "id": item["id"],
            "condition": condition,
            "title": item["title"],
            "original_ingredients": item["ingredients"],
            "original_usage": item["usage"],
            "original_effect": item["effect"],
            "trust": {"_score": item["trust_score"]},
            "pattern": best,
        }
        for item in alternatives
    ]
    return card


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", required=True)
    parser.add_argument("--answer", default=None,
                        help="用户对判别性问题的回答（省略时出问题）")
    parser.add_argument("--records",
                        default=str(SKILL_ROOT / "assets" / "records.jsonl"))
    args = parser.parse_args()

    records = load_records(Path(args.records))
    if args.answer:
        card = converge(args.issue, args.answer, records)
    else:
        card = inquire(args.issue, records)
    print(json.dumps(card, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
