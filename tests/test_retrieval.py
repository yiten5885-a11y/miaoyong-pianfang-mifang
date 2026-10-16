#!/usr/bin/env python3
"""Retrieval regression suite — the v1.2 acceptance criteria.

Background
----------
v1.1 scored 5/25 on this set. The cause was not a weak synonym table but a
silent fallback in `run_search`: when no condition matched, it returned the
top-ranked records anyway, so "三天没上厕所了" was answered with a formula for
oedema. The failure mode was *confident wrong answers*, not "I don't know".

The cases below are the realistic phrasings that exposed it. Three of them
(腰酸, 眼睛干涩, 风湿关节疼) describe topics the book genuinely has no section
for — for those, `no_match` is the correct answer and the test asserts that the
skill says so instead of inventing a formula.

Target: >= 22/25 resolved, and every unresolved case returns `no_match`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from improve import compose  # noqa: E402
from search import (  # noqa: E402
    CHILD_MARKERS, SYNONYMS, fuzzy_contains, load_records, resolve_conditions,
    run_search, suggest_conditions,
)

# (utterance, expected condition) — None means the book has no such section.
CASES: list[tuple[str, str | None]] = [
    ("最近老咳嗽，痰是白的，怕冷", "咳嗽"),
    ("嗓子干痒老想咳，没痰", "咳嗽"),
    ("孩子半夜老是哭闹睡不好", "小儿夜啼"),
    ("我老婆月经来的时候疼得厉害", "痛经"),
    ("三天没上厕所了", "便秘"),
    ("一吃凉的就拉肚子", "腹泻"),
    ("晚上翻来覆去睡不着", "神经衰弱"),
    ("血压有点高", "高血压"),
    ("脸上长了好多痘痘", "粉刺"),
    ("头发掉得厉害", "乌须美发"),
    ("最近老是没胃口", "消化不良"),
    ("嘴里老是溃疡", "口腔溃疡"),
    ("脚气很痒", "脚气"),
    ("小孩积食不吃饭", "小儿厌食和异食癖"),
    ("老是打嗝停不下来", "呃逆"),
    ("耳鸣嗡嗡响", "耳鸣、耳聋"),
    ("手指被刀划了个口子", "跌打损伤"),
    ("被开水烫了", "水火烫伤"),
    ("喝酒喝多了头疼", "头痛"),
    ("减肥一直减不下来", "肥胖症"),
    ("白头发越来越多", "乌须美发"),
    ("腋下出汗有味道", "腋下狐臭"),
    # The book has no section for these; refusing is the correct behaviour.
    ("腰酸得直不起来", None),
    ("眼睛干涩看不清", None),
    ("我妈风湿关节疼", None),
]

MIN_RESOLVED = 22


class TestRetrievalRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_records(ROOT / "assets" / "records.jsonl")
        cls.conditions = sorted({r["condition"] for r in cls.records})

    def test_resolution_rate(self) -> None:
        resolved = 0
        misses = []
        for utterance, expected in CASES:
            if expected is None:
                continue
            got = resolve_conditions(utterance, self.conditions)
            if expected in got:
                resolved += 1
            else:
                misses.append((utterance, expected, got))
        self.assertGreaterEqual(
            resolved, MIN_RESOLVED,
            f"只解析出 {resolved}/{sum(1 for _, e in CASES if e)}；"
            f"失败: {misses}")

    def test_expected_condition_is_the_top_choice(self) -> None:
        """The right section must win outright, not merely appear in a tie."""
        wrong = []
        for utterance, expected in CASES:
            if expected is None:
                continue
            got = resolve_conditions(utterance, self.conditions)
            if not got or got[0] != expected:
                wrong.append((utterance, expected, got[:2]))
        self.assertEqual(wrong, [], f"首选病症不对: {wrong}")

    def test_uncovered_topics_refuse_instead_of_guessing(self) -> None:
        for utterance, expected in CASES:
            if expected is not None:
                continue
            card = compose(utterance, self.records, 3, {})
            self.assertEqual(card["mode"], "no_match", utterance)
            self.assertEqual(card["results"], [], utterance)

    def test_no_match_offers_suggestions_not_answers(self) -> None:
        """A refusal may still offer candidates — as questions, never answers."""
        card = compose("我妈风湿关节疼", self.records, 3, {})
        self.assertEqual(card["mode"], "no_match")
        self.assertEqual(card["results"], [])
        self.assertIsInstance(card["suggestions"], list)
        for item in card["suggestions"]:
            self.assertIn("condition", item)

    def test_nonsense_query_is_not_answered(self) -> None:
        card = compose("qqzzxx 完全不存在的症状", self.records, 3, {})
        self.assertEqual(card["mode"], "no_match")
        self.assertEqual(card["results"], [])

    def test_child_context_beats_adult_section(self) -> None:
        """The book separates 小儿夜啼 from 神经衰弱; context must decide."""
        got = resolve_conditions("孩子半夜老是哭闹睡不好", self.conditions)
        self.assertEqual(got, ["小儿夜啼"])
        adult = resolve_conditions("晚上翻来覆去睡不着", self.conditions)
        self.assertEqual(adult, ["神经衰弱"])

    def test_every_synonym_target_exists(self) -> None:
        """A mapping to a condition the book does not have is a silent no-op."""
        available = {r["condition"] for r in self.records}
        dead = {target for target in SYNONYMS.values() if target not in available}
        self.assertEqual(dead, set(), f"死映射: {sorted(dead)}")

    def test_every_condition_is_reachable(self) -> None:
        """No section should be unreachable from any phrase a person would say."""
        available = {r["condition"] for r in self.records}
        covered = set(SYNONYMS.values()) & available
        self.assertEqual(available - covered, set(),
                         f"无法到达的病症: {sorted(available - covered)}")


class TestFuzzyMatching(unittest.TestCase):
    def test_exact_substring_is_full_strength(self) -> None:
        self.assertEqual(fuzzy_contains("溃疡", "嘴里溃疡"), 1.0)

    def test_filler_words_are_tolerated(self) -> None:
        self.assertGreater(fuzzy_contains("嘴里溃疡", "嘴里老是溃疡"), 0.5)

    def test_distant_characters_are_rejected(self) -> None:
        self.assertEqual(fuzzy_contains("月经疼", "月经来的时候疼得厉害"), 0.0)

    def test_short_phrases_require_exact_match(self) -> None:
        self.assertEqual(fuzzy_contains("感冒", "今天的天气很好"), 0.0)


class TestSuggestions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_records(ROOT / "assets" / "records.jsonl")

    def test_suggestions_are_conditions_that_exist(self) -> None:
        available = {r["condition"] for r in self.records}
        for query in ("眼睛干涩看不清", "腰酸得直不起来", "嘴里溃疡"):
            for item in suggest_conditions(query, self.records):
                self.assertIn(item["condition"], available)

    def test_incidental_prose_hit_does_not_produce_a_suggestion(self) -> None:
        """"眼睛干涩看不清" used to be answered with 闭经 from one stray gram."""
        suggested = [s["condition"] for s in
                     suggest_conditions("眼睛干涩看不清", self.records)]
        self.assertNotIn("闭经", suggested)

    def test_no_suggestion_is_acceptable(self) -> None:
        self.assertEqual(suggest_conditions("qqzzxx", self.records), [])


class TestChildMarkers(unittest.TestCase):
    def test_markers_cover_common_wording(self) -> None:
        for word in ("孩子", "小孩", "宝宝", "婴儿", "儿童"):
            self.assertIn(word, CHILD_MARKERS)

    def test_adult_query_is_unaffected(self) -> None:
        conditions = sorted({r["condition"] for r in
                             load_records(ROOT / "assets" / "records.jsonl")})
        self.assertNotIn("小儿夜啼", resolve_conditions("失眠睡不着", conditions))


if __name__ == "__main__":
    unittest.main(verbosity=2)
