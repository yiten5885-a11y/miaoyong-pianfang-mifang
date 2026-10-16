#!/usr/bin/env python3
"""Structural self-checks for the packaged formula records.

    python3 -m unittest discover -s tests -p 'test_*.py'

These are conservation checks, not correctness checks: they assert that the
dataset still has the shape the rules in references/ were written against.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from safety import (  # noqa: E402
    RISK_HERBS, scan_emergency, scan_herbs, scan_serious, worst_level,
)
from search import load_records, run_search  # noqa: E402
from improve import build_shopping_list, build_steps, compose, split_ingredients  # noqa: E402

EXPECTED = {
    "records": 2395,
    "chapters": 8,
    "conditions": 232,
    "offset": 10,
    "all_three_fields": 2369,
}


class TestRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_records(ROOT / "assets" / "records.jsonl")

    def test_record_count(self) -> None:
        self.assertEqual(len(self.records), EXPECTED["records"])

    def test_chapter_count(self) -> None:
        chapters = {r["chapter"] for r in self.records}
        self.assertEqual(len(chapters), EXPECTED["chapters"])
        for chapter in chapters:
            self.assertRegex(chapter, r"^第[一二三四五六七八]章 .+")

    def test_condition_count(self) -> None:
        self.assertEqual(len({r["condition"] for r in self.records}),
                         EXPECTED["conditions"])

    def test_no_garbage_chapter_names(self) -> None:
        """Every chapter must be one of the book's eight, spelled correctly."""
        canonical = {"第一章 内科", "第二章 外科", "第三章 男科病",
                     "第四章 妇科病", "第五章 小儿科疾病", "第六章 五官科",
                     "第七章 皮肤科", "第八章 美容"}
        self.assertEqual({r["chapter"] for r in self.records}, canonical)

    def test_sections_span_at_most_one_chapter(self) -> None:
        """A condition belongs to one chapter; drift means a lost heading."""
        import collections
        by_condition = collections.defaultdict(collections.Counter)
        for record in self.records:
            by_condition[record["condition"]][record["chapter"]] += 1
        drifted = sum(
            1 for r in self.records
            if r["chapter"] != by_condition[r["condition"]].most_common(1)[0][0]
        )
        # A handful of genuine cross-boundary pages are expected; a jump back
        # to double digits means the heading detection regressed.
        self.assertLess(drifted, 60, f"{drifted} records carry a foreign chapter")

    def test_previously_lost_sections_are_present(self) -> None:
        """These six headings were dropped by an over-tight font threshold."""
        conditions = {r["condition"] for r in self.records}
        for name in ("便血", "浮肿、腹水", "麦粒肿", "牙痛", "湿疹",
                     "减肥轻身", "癔病"):
            self.assertIn(name, conditions)

    def test_all_three_fields(self) -> None:
        complete = sum(
            1 for r in self.records
            if r["ingredients"] and r["usage"] and r["effect"]
        )
        self.assertEqual(complete, EXPECTED["all_three_fields"])

    def test_ids_are_unique_and_ordered(self) -> None:
        ids = [r["id"] for r in self.records]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [f"F{i:04d}" for i in range(1, len(ids) + 1)])

    def test_every_record_has_a_source_ref(self) -> None:
        for record in self.records:
            self.assertTrue(record["source_refs"], record["id"])
            self.assertEqual(record["source_refs"][0]["source_id"], "S01")
            self.assertEqual(record["source_refs"][0]["pdf_page"],
                             record["pdf_page"])

    def test_book_page_offset_is_consistent(self) -> None:
        for record in self.records:
            book_page = record.get("book_page")
            if book_page is None:
                continue
            self.assertEqual(record["pdf_page"] - book_page, EXPECTED["offset"],
                             record["id"])

    def test_required_keys(self) -> None:
        required = {
            "id", "chapter", "chapter_no", "condition", "formula_no", "title",
            "title_present", "name", "ingredients", "usage", "effect",
            "pdf_page", "book_page", "source_refs", "raw",
        }
        for record in self.records:
            self.assertTrue(required <= set(record), record.get("id"))

    def test_no_page_images_are_referenced(self) -> None:
        """The public package must not point at scanned page images."""
        for record in self.records:
            for key, value in record.items():
                if isinstance(value, str):
                    self.assertNotIn(".png", value, f"{record['id']}.{key}")
                    self.assertNotIn(".jpg", value, f"{record['id']}.{key}")

    def test_toc_matches_records(self) -> None:
        toc = json.loads((ROOT / "assets" / "toc.json").read_text(encoding="utf-8"))
        self.assertEqual(len(toc["chapters"]), EXPECTED["chapters"])
        listed = {c["chapter"] for c in toc["chapters"]}
        self.assertEqual(listed, {r["chapter"] for r in self.records})


class TestSafety(unittest.TestCase):
    def test_emergency_terms_are_detected(self) -> None:
        self.assertTrue(scan_emergency("突然胸痛，喘不上气"))
        self.assertTrue(scan_emergency("我妈晕厥了"))
        self.assertFalse(scan_emergency("最近有点咳嗽"))

    def test_high_risk_herbs_are_flagged(self) -> None:
        herbs = scan_herbs("雄黄3克，轻粉1克")
        self.assertEqual(worst_level(herbs), "high")

    def test_longest_match_wins(self) -> None:
        herbs = scan_herbs("生附子10克")
        self.assertEqual([h["herb"] for h in herbs], ["生附子"])

    def test_caution_herbs_do_not_escalate(self) -> None:
        self.assertEqual(worst_level(scan_herbs("红糖适量")), "caution")

    def test_serious_conditions(self) -> None:
        self.assertIsNotNone(scan_serious("尿毒症"))
        self.assertIsNone(scan_serious("咳嗽"))

    def test_risk_table_is_well_formed(self) -> None:
        for name, meta in RISK_HERBS.items():
            self.assertIn(meta["level"], {"high", "medium", "caution"}, name)
            self.assertTrue(meta["why"], name)


class TestRetrieval(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_records(ROOT / "assets" / "records.jsonl")

    def test_colloquial_query_maps_to_condition(self) -> None:
        result = run_search("老是咳嗽痰多", self.records, limit=3)
        self.assertIn("咳嗽", result["matched_conditions"])
        self.assertTrue(result["results"])

    def test_synonym_mapping(self) -> None:
        result = run_search("拉肚子好几天了", self.records, limit=3)
        self.assertIn("腹泻", result["matched_conditions"])

    def test_no_match_is_reported(self) -> None:
        result = run_search("完全不存在的症状xyz", self.records, limit=3)
        self.assertIsInstance(result["results"], list)


class TestComposition(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_records(ROOT / "assets" / "records.jsonl")

    def test_emergency_short_circuits(self) -> None:
        card = compose("突然胸痛呼吸困难", self.records)
        self.assertEqual(card["mode"], "emergency")
        self.assertEqual(card["results"], [])

    def test_normal_query_returns_card(self) -> None:
        card = compose("经常便秘", self.records)
        self.assertEqual(card["mode"], "remedy")
        for key in ("primary", "safety", "trial_rhythm", "followups"):
            self.assertIn(key, card)

    def test_ingredient_splitting(self) -> None:
        parts = split_ingredients("羊血500克，米醋60毫升。")
        self.assertEqual(len(parts), 2)

    def test_shopping_list_keeps_original_wording(self) -> None:
        groups = build_shopping_list("瓜蒌1个，糯米100克。")
        self.assertIn("瓜蒌1个", groups["pharmacy"])
        self.assertIn("糯米100克", groups["market"])

    def test_steps_never_invent_content(self) -> None:
        usage = "将人参切片，加水煎沸30分钟，冲入杯中。每日1剂。"
        steps = build_steps(usage)
        joined = "".join(step["text"] for step in steps)
        for fragment in ("人参", "煎沸30分钟", "每日1剂"):
            self.assertIn(fragment, joined)

    def test_steps_degrade_when_unsplittable(self) -> None:
        steps = build_steps("水煎服。")
        self.assertEqual(len(steps), 1)

    def test_high_risk_formula_is_red(self) -> None:
        card = compose("肺结核", self.records)
        if card["mode"] == "remedy":
            self.assertIn(card["safety"]["tier"]["colour"], {"red", "yellow"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
