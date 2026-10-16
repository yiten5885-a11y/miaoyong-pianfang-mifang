#!/usr/bin/env python3
"""药材名清洗的自检。

    python3 -m unittest tests.test_herbs

守住三件事：
1. 「各」尾缀必须剥掉——这是全书系统性 OCR 现象，不剥则约 50 个高频
   药名会被当成独立药材，共现与冲突统计全部失真。
2. 真实辅料必须保留——白糖、黄酒、蜂蜜、葱白不是噪声，是药膳方
   的真实组成部分，删掉就是破坏原方。
3. 不可判定的名字必须丢弃——单字「姜」到底是生姜、干姜还是炮姜，
   不猜。
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from herbs import (  # noqa: E402
    clean_herb_name, ingredient_counter, noise_report, parse_ingredients,
)
from search import load_records  # noqa: E402

RECORDS = load_records(SKILL_ROOT / "assets" / "records.jsonl")


def make_record(ingredients: str) -> dict:
    return {"ingredients": ingredients, "usage": "", "effect": ""}


class TestGeSuffixStripping(unittest.TestCase):
    """「各」尾缀：原书等分标记被 OCR 粘进药名。"""

    def test_ge_suffix_is_stripped(self) -> None:
        self.assertEqual(clean_herb_name("甘草各"), "甘草")
        self.assertEqual(clean_herb_name("当归各"), "当归")
        self.assertEqual(clean_herb_name("蜂蜜各"), "蜂蜜")

    def test_ge_suffix_with_dose(self) -> None:
        self.assertEqual(clean_herb_name("甘草各 6 克"), "甘草")
        self.assertEqual(clean_herb_name("白糖各适量"), "白糖")

    def test_single_char_ge_is_dropped(self) -> None:
        # 「地各」剥完是「地」，无法判断，丢弃而不是猜
        self.assertIsNone(clean_herb_name("地各"))

    def test_real_herb_survives_ge_strip(self) -> None:
        self.assertEqual(clean_herb_name("香油各适量"), "香油")


class TestNoiseRemoval(unittest.TestCase):
    """纯泛称剔除；真实辅料保留。"""

    def test_generic_terms_are_dropped(self) -> None:
        for noise in ("调料", "味精", "湿淀粉", "作料", "配料", "佐料"):
            self.assertIsNone(clean_herb_name(noise), noise)

    def test_generic_term_with_dose_is_dropped(self) -> None:
        self.assertIsNone(clean_herb_name("调料适量"))

    def test_real_auxiliary_ingredients_survive(self) -> None:
        """白糖、黄酒、蜂蜜是药膳方的真实辅料，不是噪声。"""
        for keep in ("白糖", "红糖", "冰糖", "蜂蜜", "黄酒", "米酒",
                     "白酒", "葱白", "生姜", "大蒜", "粳米", "糯米",
                     "鸡蛋", "香油", "精盐"):
            self.assertIsNotNone(clean_herb_name(keep), keep)

    def test_single_char_ambiguous_names_dropped(self) -> None:
        # 单字「姜」「盐」「醋」无法判定品种，按宁缺毋滥丢弃
        self.assertIsNone(clean_herb_name("姜"))
        self.assertIsNone(clean_herb_name("盐"))

    def test_two_char_but_known_kept(self) -> None:
        self.assertEqual(clean_herb_name("当归"), "当归")


class TestDoseAndPrefixStripping(unittest.TestCase):
    """剂量与制法前缀的剥离。"""

    def test_dose_stripped(self) -> None:
        self.assertEqual(clean_herb_name("核桃仁 30 克"), "核桃仁")
        self.assertEqual(clean_herb_name("大枣 3 枚"), "大枣")

    def test_prefix_stripped(self) -> None:
        self.assertEqual(clean_herb_name("鲜芦根"), "芦根")
        self.assertEqual(clean_herb_name("炙甘草"), "甘草")

    def test_paren_note_stripped(self) -> None:
        self.assertEqual(clean_herb_name("当归（后下）"), "当归")

    def test_prefix_that_is_part_of_name_is_kept(self) -> None:
        """生/熟/干是药名组成部分，不是制法前缀，不能剥。"""
        self.assertEqual(clean_herb_name("生大黄"), "生大黄")
        self.assertEqual(clean_herb_name("熟地"), "熟地")
        self.assertEqual(clean_herb_name("生姜"), "生姜")

    def test_action_prefix_is_stripped(self) -> None:
        """炙/炒/煅/鲜是明确的加工标记，归并到正名。"""
        self.assertEqual(clean_herb_name("炙甘草"), "甘草")
        self.assertEqual(clean_herb_name("炒麦芽"), "麦芽")
        self.assertEqual(clean_herb_name("鲜芦根"), "芦根")


class TestParseIngredients(unittest.TestCase):
    """整条原料串的解析。"""

    def test_splits_on_punctuation(self) -> None:
        ings = parse_ingredients(make_record("当归 10 克，黄芪 15 克、白芍 12 克"))
        self.assertEqual(ings, ["当归", "黄芪", "白芍"])

    def test_deduplicates(self) -> None:
        ings = parse_ingredients(make_record("甘草各 6 克，甘草 3 克"))
        self.assertEqual(ings, ["甘草"])

    def test_ge_and_normal_forms_merge(self) -> None:
        """关键回归：剥「各」前后必须归并到同一个药材名。"""
        ings = parse_ingredients(make_record("生姜 10 克，甘草各 6 克，当归 9 克"))
        self.assertEqual(ings, ["生姜", "甘草", "当归"])

    def test_noise_does_not_appear(self) -> None:
        ings = parse_ingredients(make_record("当归 10 克，调料适量，味精少许"))
        self.assertNotIn("调料", ings)
        self.assertNotIn("味精", ings)
        self.assertIn("当归", ings)

    def test_empty_input(self) -> None:
        self.assertEqual(parse_ingredients(make_record("")), [])


class TestCorpusEffect(unittest.TestCase):
    """真实数据上的清洗效果。"""

    def test_ge_stripping_happened_at_scale(self) -> None:
        report = noise_report(RECORDS)
        self.assertGreater(report["ge_stripped"], 100,
                           "「各」尾缀清洗未生效")

    def test_clean_names_shrink_but_stay_large(self) -> None:
        report = noise_report(RECORDS)
        self.assertLess(report["clean_names"], report["raw_names"])
        self.assertGreater(report["clean_names"], 600)

    def test_high_frequency_ingredients_are_real(self) -> None:
        counter = ingredient_counter(RECORDS)
        top = [name for name, _ in sorted(counter.items(),
                                          key=lambda kv: -kv[1])[:12]]
        for noise in ("调料", "味精", "作料"):
            self.assertNotIn(noise, top)
        for real in ("当归", "甘草", "黄芪", "大枣"):
            self.assertIn(real, top)

    def test_no_digit_in_clean_names(self) -> None:
        counter = ingredient_counter(RECORDS)
        self.assertFalse([n for n in counter if any(ch.isdigit() for ch in n)])


if __name__ == "__main__":
    unittest.main()
