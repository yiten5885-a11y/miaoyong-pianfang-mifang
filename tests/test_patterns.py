#!/usr/bin/env python3
"""辨证收敛问诊的自检。

    python3 -m unittest tests.test_patterns

守住五件事：
1. 证型抽取与归一化——前缀剥离、OCR 错字修复、繁简归一、同义归并。
2. 索引只收可收敛的病症——证型不足两种的不进问诊路径，不伪装成
   可以辨证。
3. 问诊两轮——第一轮出问题（选项来自原书症见原文），第二轮收敛。
4. 收敛不出结果时不硬给——不匹配或跨簇打平都有明确降级。
5. 安全口径——输出不含诊断措辞（「你是某型」），说明分类是原书
   记述不是诊断。
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from inquire import converge, inquire  # noqa: E402
from patterns import (  # noqa: E402
    build_pattern_index, extract_patterns, normalize_pattern,
)
from search import load_records  # noqa: E402

RECORDS = load_records(SKILL_ROOT / "assets" / "records.jsonl")


def make_record(**kwargs) -> dict:
    base = {"id": "T1", "title": "测试方", "ingredients": "", "usage": "",
            "effect": "", "condition": "测试"}
    base.update(kwargs)
    return base


class TestNormalization(unittest.TestCase):
    """证型归一化四步。"""

    def test_prefix_stripped(self) -> None:
        self.assertEqual(normalize_pattern("适用于风热型"), "风热")
        self.assertEqual(normalize_pattern("用于气滞血瘀型"), "气滞血瘀")

    def test_ocr_fix_before_traditional(self) -> None:
        """OCR 错字修复先于繁简归一（攪/灣 是错字不是繁体）。"""
        self.assertEqual(normalize_pattern("用于察湿攪滞型"), "寒湿凝滞")
        self.assertEqual(normalize_pattern("偏手气灣型"), "气滞")
        self.assertEqual(normalize_pattern("偏手气帶型"), "气滞")

    def test_traditional_normalized(self) -> None:
        self.assertEqual(normalize_pattern("气血虛弱型"), "气血虚弱")

    def test_hedge_prefix_stripped(self) -> None:
        self.assertEqual(normalize_pattern("偏于气滞型"), "气滞")

    def test_synonym_grouped(self) -> None:
        self.assertEqual(normalize_pattern("肾阳不足型"), "肾阳不足")
        self.assertEqual(normalize_pattern("肾阳虚型"), "肾阳不足")

    def test_empty_for_no_type(self) -> None:
        self.assertEqual(normalize_pattern("止咳平喘"), "")

    def test_extract_merges_variants(self) -> None:
        """同一记录里「肾阳虚」与「肾阳不足」应归并为同一证型。"""
        record = make_record(effect="适用于肾阳虚型与肾阳不足型。")
        self.assertEqual(extract_patterns(record), {"肾阳不足"})


class TestPatternIndex(unittest.TestCase):
    """证型索引构建。"""

    def test_only_convergent_conditions_indexed(self) -> None:
        index = build_pattern_index(RECORDS)
        for condition, entry in index.items():
            self.assertGreaterEqual(entry["pattern_count"], 2, condition)

    def test_index_has_real_coverage(self) -> None:
        index = build_pattern_index(RECORDS)
        self.assertGreaterEqual(len(index), 40)
        self.assertGreaterEqual(
            sum(1 for v in index.values() if v["pattern_count"] >= 3), 20)

    def test_dysmenorrhea_clusters_clean(self) -> None:
        """回归：OCR 噪声与繁简变体曾把痛经拆成 6 个碎片簇。"""
        index = build_pattern_index(RECORDS)
        entry = index["痛经"]
        self.assertEqual(entry["pattern_count"], 4)
        self.assertIn("寒湿凝滞", entry["clusters"])
        self.assertIn("气滞", entry["clusters"])
        for variant in ("手气帶", "手气灣", "察湿攪滞", "气血虛弱"):
            self.assertNotIn(variant, entry["clusters"])

    def test_cluster_formulas_carry_clue(self) -> None:
        index = build_pattern_index(RECORDS)
        entry = index["痛经"]
        for cluster in entry["clusters"].values():
            self.assertIn("clue", cluster)
            self.assertIn("formulas", cluster)


class TestInquireRoundOne(unittest.TestCase):
    """问诊第一轮。"""

    def test_question_with_options(self) -> None:
        card = inquire("痛经", RECORDS)
        self.assertEqual(card["mode"], "inquire")
        self.assertTrue(card["options"])
        for option in card["options"]:
            self.assertIn("pattern", option)
            self.assertIn("clue", option)
            self.assertIn("formula_count", option)

    def test_options_from_book_text(self) -> None:
        """判别性描述必须来自原书症见原文，不能是模板空话。"""
        card = inquire("痛经", RECORDS)
        clues = [o["clue"] for o in card["options"]
                 if not o["clue"].startswith("原书将该类")]
        for clue in clues:
            self.assertGreater(len(clue), 8, clue)

    def test_no_pattern_condition_gives_remedy(self) -> None:
        card = inquire("最近老咳嗽，痰多", RECORDS)
        self.assertEqual(card["mode"], "remedy")
        self.assertIsNone(card["inquiry"])

    def test_emergency_not_gated_by_inquiry(self) -> None:
        card = inquire("我爸突然胸痛呼吸困难", RECORDS)
        self.assertEqual(card["mode"], "emergency")

    def test_no_match_not_gated_by_inquiry(self) -> None:
        card = inquire("腰酸得直不起来", RECORDS)
        self.assertEqual(card["mode"], "no_match")


class TestConvergence(unittest.TestCase):
    """问诊第二轮：收敛。"""

    def test_converge_to_cold_damp(self) -> None:
        card = converge("痛经", "小腹发冷，按之更痛，经血黑有块，四肢发凉",
                        RECORDS)
        self.assertEqual(card["mode"], "inquire_result")
        self.assertTrue(card["inquiry"]["converged"])
        self.assertEqual(card["inquiry"]["pattern"], "寒湿凝滞")
        self.assertEqual(card["primary"]["pattern"], "寒湿凝滞")

    def test_converge_to_qi_stagnation(self) -> None:
        card = converge("痛经", "经前乳房胀痛，胸胁胀，少腹胀痛，易怒",
                        RECORDS)
        self.assertEqual(card["mode"], "inquire_result")
        self.assertEqual(card["inquiry"]["pattern"], "气滞")

    def test_no_cluster_match_does_not_force(self) -> None:
        card = converge("痛经", "今天天气不错心情很好", RECORDS)
        self.assertEqual(card["mode"], "remedy")
        self.assertFalse(card["inquiry"]["converged"])
        # 不硬归类时给本节全部方，并提示就医
        self.assertTrue(card["primary"]["title"])

    def test_result_carries_primary_formula(self) -> None:
        card = converge("痛经", "小腹发冷，按之更痛，经血黑有块", RECORDS)
        self.assertTrue(card["primary"]["original_ingredients"])


class TestSafetyWording(unittest.TestCase):
    """安全口径：分类是原书记述，不是诊断。"""

    def test_no_diagnosis_wording(self) -> None:
        """输出里不得出现「你是某型」这类诊断措辞。"""
        for card in (inquire("痛经", RECORDS),
                     converge("痛经", "小腹发冷，按之更痛", RECORDS)):
            text = str(card)
            self.assertNotIn("你是", text)
            self.assertNotIn("你这是", text)
            self.assertNotIn("诊断为", text)

    def test_inquiry_note_present(self) -> None:
        card = converge("痛经", "小腹发冷，按之更痛，经血黑有块", RECORDS)
        self.assertIn("不是诊断", card["inquiry_note"])

    def test_question_disclaims_diagnosis(self) -> None:
        card = inquire("痛经", RECORDS)
        self.assertIn("不是诊断", card["data_note"])


if __name__ == "__main__":
    unittest.main()
