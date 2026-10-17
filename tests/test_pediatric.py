#!/usr/bin/env python3
"""儿童剂量安全层的自检。

    python3 -m unittest tests.test_pediatric

守住三件事：
1. 儿童语境识别——孩子/宝宝/婴儿等标记与「3 岁」年龄表述都要认出来。
2. 跨节拦截——命中成人小节必须触发闸门；命中儿科小节必须静默。
3. 儿科口语映射——家长常见说法必须路由到儿科小节（v1.4 补齐），
   且 test_retrieval 的 25 条回归不受影响。
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from improve import compose  # noqa: E402
from pediatric import (  # noqa: E402
    detect_child_context, pediatric_gate, pediatric_sections_for,
)
from search import load_records  # noqa: E402

RECORDS = load_records(SKILL_ROOT / "assets" / "records.jsonl")


def find_record(condition: str) -> dict:
    return next(r for r in RECORDS if r["condition"] == condition)


class TestChildContextDetection(unittest.TestCase):
    """儿童语境识别。"""

    def test_child_markers(self) -> None:
        for query in ("孩子咳嗽", "小孩发烧", "宝宝拉肚子", "婴儿湿疹",
                      "3岁孩子便秘", "闺女嗓子疼", "两个月大的宝宝腹泻"):
            self.assertTrue(detect_child_context(query), query)

    def test_age_expression(self) -> None:
        self.assertTrue(detect_child_context("患者 5 岁，咳嗽"))

    def test_adult_queries_not_flagged(self) -> None:
        for query in ("嗓子疼", "我咳嗽", "高血压怎么吃", "老年人失眠"):
            self.assertFalse(detect_child_context(query), query)


class TestGateBehavior(unittest.TestCase):
    """闸门触发与静默。"""

    def test_adult_section_triggers_gate(self) -> None:
        gate = pediatric_gate("孩子嗓子疼", find_record("急性咽喉炎、咽喉肿痛"),
                              RECORDS)
        self.assertIsNotNone(gate)
        self.assertTrue(gate["adult_section"])
        self.assertIn("不能直接套用", gate["message"])

    def test_pediatric_section_silent(self) -> None:
        gate = pediatric_gate("孩子咳嗽", find_record("小儿咳喘"), RECORDS)
        self.assertIsNone(gate)

    def test_adult_query_silent(self) -> None:
        gate = pediatric_gate("嗓子疼", find_record("急性咽喉炎、咽喉肿痛"),
                              RECORDS)
        self.assertIsNone(gate)

    def test_pediatric_sections_suggested_by_symptom_family(self) -> None:
        # 「孩子咳嗽」命中成人「咳嗽」小节时，应指路「小儿咳喘」
        sections = pediatric_sections_for("孩子咳嗽老不好", RECORDS)
        self.assertIn("小儿咳喘", sections)

    def test_no_matching_pediatric_section(self) -> None:
        # 原书儿科没有「咽喉」小节，候选为空，next_step 引导就医
        gate = pediatric_gate("孩子嗓子疼", find_record("急性咽喉炎、咽喉肿痛"),
                              RECORDS)
        self.assertEqual(gate["pediatric_sections"], [])
        self.assertIn("就医", gate["next_step"])


class TestComposeIntegration(unittest.TestCase):
    """端到端：compose 输出的闸门字段。"""

    def test_child_query_pediatric_section_no_gate(self) -> None:
        card = compose("孩子咳嗽老不好", RECORDS, 3, {})
        self.assertEqual(card["mode"], "remedy")
        self.assertEqual(card["primary"]["chapter"], "第五章 小儿科疾病")
        self.assertIsNone(card["pediatric_gate"])

    def test_child_query_adult_section_has_gate(self) -> None:
        card = compose("孩子嗓子疼", RECORDS, 3, {})
        self.assertEqual(card["mode"], "remedy")
        gate = card["pediatric_gate"]
        self.assertIsNotNone(gate)
        self.assertTrue(gate["is_child"])
        self.assertEqual(gate["matched_section"],
                         card["primary"]["condition"])

    def test_adult_query_no_gate_field(self) -> None:
        card = compose("嗓子疼", RECORDS, 3, {})
        self.assertIsNone(card["pediatric_gate"])

    def test_formula_still_present_with_gate(self) -> None:
        """闸门警告但不扣方——方照给，剂量警示在前。"""
        card = compose("孩子嗓子疼", RECORDS, 3, {})
        self.assertTrue(card["primary"]["title"])


class TestPediatricRouting(unittest.TestCase):
    """v1.4 补齐的儿科口语映射：家长说法必须路由到儿科小节。"""

    PEDIATRIC_CHAPTER = "第五章 小儿科疾病"

    def test_common_parent_phrasings_route_to_pediatrics(self) -> None:
        cases = {
            "孩子咳嗽老不好": "小儿咳喘",
            "小孩咳嗽有痰": "小儿咳喘",
            "宝宝拉肚子": "小儿泄泻",
            "小孩发烧": "小儿发热",
            "孩子受惊": "小儿惊风",
            "孩子夜里哭": "小儿夜啼",
            "孩子不爱吃饭": "小儿厌食和异食癖",
            "孩子夜里尿床": "小儿遗尿",
        }
        for query, expected in cases.items():
            card = compose(query, RECORDS, 3, {})
            self.assertEqual(card["mode"], "remedy", query)
            self.assertEqual(card["primary"]["condition"], expected, query)
            self.assertEqual(card["primary"]["chapter"],
                             self.PEDIATRIC_CHAPTER, query)

    def test_child_constipation_has_gate(self) -> None:
        """原书儿科无便秘小节，成人节命中 → 闸门触发。"""
        card = compose("孩子便秘", RECORDS, 3, {})
        self.assertEqual(card["mode"], "remedy")
        self.assertIsNotNone(card["pediatric_gate"])


if __name__ == "__main__":
    unittest.main()
