#!/usr/bin/env python3
"""多症状检索与编排的自检。

    python3 -m unittest tests.test_orchestrate

守住四件事：
1. 多症状命中——两个症状在原书都有小节时，必须同时命中（分段求解）。
2. 单症状不回归——普通查询的命中结果与分模块改动前完全一致。
3. 诚实降级——第二个症状原书没有小节时，只给有根据的那个，不硬凑。
4. 冲突检测三类齐全，且食材辅料重复不算冲突。
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from improve import compose  # noqa: E402
from orchestrate import detect_conflicts, orchestrate_multi  # noqa: E402
from search import (  # noqa: E402
    load_records, resolve_conditions, resolve_conditions_multi,
    split_symptoms,
)

RECORDS = load_records(SKILL_ROOT / "assets" / "records.jsonl")
CONDITIONS = sorted({r["condition"] for r in RECORDS if r["condition"]})


class TestSymptomSplitting(unittest.TestCase):
    """症状切分。"""

    def test_connector_splits(self) -> None:
        self.assertEqual(split_symptoms("感冒还嗓子疼"), ["感冒", "嗓子疼"])
        self.assertEqual(split_symptoms("便秘又口臭"), ["便秘", "口臭"])

    def test_descriptive_query_not_split(self) -> None:
        """描述句（带逗号但无连接词）不切分——它讲的是一个症状。"""
        self.assertEqual(split_symptoms("最近老咳嗽，痰多"),
                         ["最近老咳嗽，痰多"])
        self.assertEqual(split_symptoms("我老婆月经来的时候疼得厉害"),
                         ["我老婆月经来的时候疼得厉害"])

    def test_connector_words(self) -> None:
        self.assertEqual(split_symptoms("胃痛同时拉肚子"), ["胃痛", "拉肚子"])
        self.assertEqual(split_symptoms("胃痛另外还拉肚子"), ["胃痛", "拉肚子"])

    def test_stacked_connectors_collapse(self) -> None:
        """「咳嗽另外还有痰」是单症状带描述，不是两个症状。"""
        self.assertEqual(split_symptoms("咳嗽另外还有痰"), ["咳嗽"])


class TestMultiResolution(unittest.TestCase):
    """多症状命中。"""

    def test_both_symptoms_resolve(self) -> None:
        cases = [
            ("感冒还嗓子疼", ["感冒", "急性咽喉炎、咽喉肿痛"]),
            ("胃痛还拉肚子", ["胃痛", "腹泻"]),
            ("头痛还失眠", ["头痛", "神经衰弱"]),
            ("便秘还痔疮", ["便秘", "痔疮"]),
            ("咳嗽还呕吐", ["咳嗽", "呕吐"]),
        ]
        for query, expected in cases:
            self.assertEqual(resolve_conditions_multi(query, CONDITIONS),
                             expected, query)

    def test_missing_section_does_not_invent(self) -> None:
        """原书没有成人发热小节——只给有根据的咳嗽，不硬凑。"""
        self.assertEqual(resolve_conditions_multi("咳嗽还发烧",
                                                  CONDITIONS), ["咳嗽"])

    def test_same_section_merges(self) -> None:
        """脱发与白发在原书同属「乌须美发」——合并成一个是正确的。"""
        result = resolve_conditions_multi("脱发还白发", CONDITIONS)
        self.assertEqual(result, ["乌须美发"])

    def test_single_symptom_unchanged(self) -> None:
        """单症状查询行为与分模块改动前完全一致。"""
        queries = ["最近老咳嗽，痰是白的，怕冷", "我老婆月经来的时候疼得厉害",
                   "三天没上厕所了", "晚上翻来覆去睡不着", "孩子咳嗽老不好",
                   "被开水烫了", "血压有点高"]
        for query in queries:
            self.assertEqual(resolve_conditions_multi(query, CONDITIONS),
                             resolve_conditions(query, CONDITIONS), query)


class TestConflictDetection(unittest.TestCase):
    """三类冲突。"""

    def _record(self, **kwargs) -> dict:
        base = {"id": "T1", "title": "测试方", "ingredients": "",
                "usage": "", "effect": "", "condition": "测试"}
        base.update(kwargs)
        return base

    def test_duplicate_herbs_conflict(self) -> None:
        a = self._record(ingredients="当归 10 克，川芎 6 克，白芍 9 克")
        b = self._record(ingredients="当归 10 克，川芎 6 克，熟地 12 克")
        kinds = [c["kind"] for c in detect_conflicts(a, b)]
        self.assertIn("duplicate_herbs", kinds)

    def test_food_auxiliary_overlap_not_conflict(self) -> None:
        """两方都放白糖/粳米是药膳常态，不算用药冲突。"""
        a = self._record(ingredients="当归 10 克，白糖适量")
        b = self._record(ingredients="黄芪 15 克，白糖适量，粳米 100 克")
        kinds = [c["kind"] for c in detect_conflicts(a, b)]
        self.assertNotIn("duplicate_herbs", kinds)

    def test_alcohol_stacking_conflict(self) -> None:
        a = self._record(ingredients="当归 10 克", usage="黄酒送服。")
        b = self._record(ingredients="黄芪 15 克", usage="黄酒送服。")
        kinds = [c["kind"] for c in detect_conflicts(a, b)]
        self.assertIn("alcohol_stacking", kinds)

    def test_thermal_clash_conflict(self) -> None:
        a = self._record(effect="辛温解表，祛风散寒。")
        b = self._record(effect="清热解毒，凉血。")
        kinds = [c["kind"] for c in detect_conflicts(a, b)]
        self.assertIn("thermal_clash", kinds)

    def test_same_direction_no_thermal_clash(self) -> None:
        a = self._record(effect="辛温解表，祛风散寒。")
        b = self._record(effect="发表解毒，驱风散寒。")
        kinds = [c["kind"] for c in detect_conflicts(a, b)]
        self.assertNotIn("thermal_clash", kinds)

    def test_conflict_carries_action(self) -> None:
        a = self._record(ingredients="当归 10 克，川芎 6 克")
        b = self._record(ingredients="当归 10 克，川芎 6 克")
        for conflict in detect_conflicts(a, b):
            self.assertIn("action", conflict)


class TestOrchestration(unittest.TestCase):
    """编排卡片。"""

    def test_sections_grouped_by_condition(self) -> None:
        card = orchestrate_multi("感冒还嗓子疼", RECORDS,
                                 ["感冒", "急性咽喉炎、咽喉肿痛"])
        self.assertEqual(len(card["sections"]), 2)
        for section in card["sections"]:
            self.assertTrue(section["formulas"])
            self.assertIn("condition", section)

    def test_high_trust_formulas_first(self) -> None:
        card = orchestrate_multi("感冒还嗓子疼", RECORDS,
                                 ["感冒", "急性咽喉炎、咽喉肿痛"])
        for section in card["sections"]:
            scores = [f["trust_score"] for f in section["formulas"]]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_trial_rule_present(self) -> None:
        card = orchestrate_multi("感冒还嗓子疼", RECORDS,
                                 ["感冒", "急性咽喉炎、咽喉肿痛"])
        self.assertIn("试 1 天", card["trial_rule"]["note"])
        self.assertIn("不同时试多道", card["trial_rule"]["must_not"])

    def test_empty_condition_skipped(self) -> None:
        card = orchestrate_multi("测试", RECORDS, ["不存在的病症"])
        self.assertEqual(card["sections"], [])


class TestComposeMultiMode(unittest.TestCase):
    """compose 的 multi 模式端到端。"""

    def test_multi_mode_shape(self) -> None:
        card = compose("感冒还嗓子疼", RECORDS, 3, {})
        self.assertEqual(card["mode"], "multi")
        self.assertEqual(card["matched_conditions"],
                         ["感冒", "急性咽喉炎、咽喉肿痛"])
        self.assertIn("sections", card)
        self.assertIn("conflicts", card)
        self.assertIn("trial_rule", card)

    def test_safety_layers_present_in_multi(self) -> None:
        """多症状不豁免安全层：档案闸门与儿科闸门都要在。"""
        card = compose("感冒还嗓子疼", RECORDS, 3, {})
        self.assertIn("profile", card)
        self.assertIn("pediatric_gate", card)
        for section in card["sections"]:
            for formula in section["formulas"]:
                self.assertIn("interactions", formula)
                self.assertIn("blocked", formula)

    def test_profile_gate_blocks_formula(self) -> None:
        profile = {"conditions": ["高血压"], "medications": [],
                   "allergies": [], "special": [], "diet": []}
        card = compose("感冒还嗓子疼", RECORDS, 3, profile)
        blocked = [f for s in card["sections"] for f in s["formulas"]
                   if f["blocked"]]
        for formula in blocked:
            self.assertTrue(formula["interactions"])

    def test_child_query_in_multi_gets_gate(self) -> None:
        """孩子+多症状：儿科闸门仍然在线。"""
        card = compose("孩子感冒还嗓子疼", RECORDS, 3, {})
        self.assertIn("pediatric_gate", card)

    def test_single_symptom_mode_unchanged(self) -> None:
        card = compose("最近老咳嗽，痰多", RECORDS, 3, {})
        self.assertEqual(card["mode"], "remedy")


if __name__ == "__main__":
    unittest.main()
