#!/usr/bin/env python3
"""信任分（来源可信度分层）的自检。

    python3 -m unittest tests.test_trust

守住三件事：
1. 分布稳定——5 档区分度存在，不会退化成「所有记录同分」。
2. 打分只读原书转录——不因为哪个字段好看就加分，纯字段完整度驱动。
3. 用户可读输出不暴露内部字段名与分数数字。
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from search import load_records  # noqa: E402
from trust import (  # noqa: E402
    has_dose, has_pattern, section_trust_overview, trust_detail, trust_label,
    trust_score,
)

RECORDS = load_records(SKILL_ROOT / "assets" / "records.jsonl")


def make_record(**kwargs) -> dict:
    """按默认完整字段造一条记录，逐项覆盖测试用。"""
    base = {
        "title_present": True,
        "ingredients": "核桃仁 30 克，粳米 100 克",
        "usage": "共煮成粥，每日 2 次。",
        "effect": "治风寒感冒，症见恶寒无汗。",
    }
    base.update(kwargs)
    return base


class TestScoreDimensions(unittest.TestCase):
    """每个维度单独验证加减分。"""

    def test_full_record_scores_five(self) -> None:
        self.assertEqual(trust_score(make_record()), 5)

    def test_missing_title_costs_one(self) -> None:
        self.assertEqual(trust_score(make_record(title_present=False)), 4)

    def test_missing_pattern_costs_two(self) -> None:
        self.assertEqual(
            trust_score(make_record(effect="止咳平喘。治咳嗽。")), 3)

    def test_missing_dose_costs_one(self) -> None:
        self.assertEqual(
            trust_score(make_record(ingredients="核桃仁，粳米")), 4)

    def test_missing_usage_costs_one(self) -> None:
        self.assertEqual(trust_score(make_record(usage="")), 4)

    def test_effect_only_scores_zero(self) -> None:
        record = {"title_present": False, "ingredients": "", "usage": "",
                  "effect": "降气止咳。"}
        self.assertEqual(trust_score(record), 0)

    def test_title_only_scores_one(self) -> None:
        record = {"title_present": True, "ingredients": "", "usage": "",
                  "effect": "降气止咳。"}
        self.assertEqual(trust_score(record), 1)

    def test_empty_record_scores_zero(self) -> None:
        self.assertEqual(trust_score({}), 0)


class TestDimensionDetection(unittest.TestCase):
    """证型与剂量的识别边界。"""

    def test_pattern_via_explicit_type(self) -> None:
        self.assertTrue(has_pattern(make_record(effect="治风寒型感冒。")))

    def test_pattern_via_syndrome_word(self) -> None:
        self.assertTrue(has_pattern(make_record(effect="症见恶寒无汗。")))

    def test_plain_effect_is_not_pattern(self) -> None:
        self.assertFalse(has_pattern(make_record(effect="治感冒发热。")))

    def test_dose_with_gram(self) -> None:
        self.assertTrue(has_dose(make_record(ingredients="核桃仁 30 克")))

    def test_dose_with_piece(self) -> None:
        self.assertTrue(has_dose(make_record(ingredients="大枣 3 枚")))

    def test_no_number_is_not_dose(self) -> None:
        self.assertFalse(has_dose(make_record(ingredients="核桃仁适量")))
        self.assertFalse(has_dose(make_record(ingredients="粳米一把")))


class TestUserFacingPayload(unittest.TestCase):
    """回答层契约：可读、不暴露内部实现。"""

    def test_detail_exposes_only_readable_fields(self) -> None:
        detail = trust_detail(make_record())
        self.assertIn("label", detail)
        self.assertIn("note", detail)
        self.assertIn("_score", detail)  # 内部排序用，渲染层不展示

    def test_label_has_no_score_number(self) -> None:
        for score in range(6):
            label = trust_label(score)
            self.assertNotIn(str(score), label)

    def test_labels_are_stable_per_score(self) -> None:
        self.assertEqual(trust_label(5), "原书对这一条记得最全")
        self.assertEqual(trust_label(1), "原书仅一句话，缺方名")
        self.assertEqual(trust_label(0), trust_label(1))


class TestDistribution(unittest.TestCase):
    """真实数据上的分布稳定性。

    阈值来自 2026-10-16 实测：{1:16, 2:620, 3:1155, 4:104, 5:500}。
    若某档整体漂移，说明打分维度或数据发生了变化，需要人工复核。
    """

    def test_five_levels_all_present(self) -> None:
        counts = {score: 0 for score in range(6)}
        for record in RECORDS:
            counts[trust_score(record)] += 1
        for score in range(1, 6):
            self.assertGreater(counts[score], 0,
                               f"得分 {score} 档无记录，分层失效")
        self.assertGreater(counts[5], 100, "高分记录过少")
        self.assertLess(counts[5] / len(RECORDS), 0.4, "高分记录过多")
        self.assertGreater(counts[3] / len(RECORDS), 0.2,
                           "中间档记录过少，区分度不足")

    def test_distribution_within_tolerance(self) -> None:
        counts = {score: 0 for score in range(6)}
        for record in RECORDS:
            counts[trust_score(record)] += 1
        expected = {1: 16, 2: 620, 3: 1155, 4: 104, 5: 500}
        for score, want in expected.items():
            got = counts[score]
            self.assertAlmostEqual(got / want, 1.0, delta=0.25,
                                   msg=f"得分 {score} 档漂移: {got} vs {want}")


class TestSectionOverview(unittest.TestCase):
    """小节概况：供回答说「这一节 8 道方里 2 道写得最全」。"""

    def test_overview_counts_full_records(self) -> None:
        overview = section_trust_overview([make_record(),
                                           make_record(title_present=False,
                                                       effect="治感冒。")])
        self.assertEqual(overview["total"], 2)
        self.assertEqual(overview["full"], 1)

    def test_overview_handles_empty(self) -> None:
        self.assertEqual(section_trust_overview([])["total"], 0)

    def test_real_section_overview(self) -> None:
        cold = [r for r in RECORDS if r["condition"] == "感冒"]
        overview = section_trust_overview(cold)
        self.assertEqual(overview["total"], len(cold))
        self.assertGreater(overview["full"], 0)


if __name__ == "__main__":
    unittest.main()
