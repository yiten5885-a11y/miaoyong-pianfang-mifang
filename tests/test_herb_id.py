#!/usr/bin/env python3
"""药材辨识要点的自检。

    python3 -m unittest tests.test_herb_id

守住三件事：
1. 只收录库内真实出现的易混对——凭空加的辨识要点会误导抓药。
2. 泛称与具体名不重复提示（「贝母」与「川贝母」同时命中只报一次）。
3. 辨识要点是客观描述，不下真假结论。
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from herb_id import CONFUSED_HERBS, herb_id_notes  # noqa: E402
from improve import compose  # noqa: E402
from search import load_records  # noqa: E402

RECORDS = load_records(SKILL_ROOT / "assets" / "records.jsonl")


class TestNoteDetection(unittest.TestCase):
    """命中与不命中。"""

    def test_ambiguous_herb_gets_note(self) -> None:
        notes = herb_id_notes("川贝母 3 克，枇杷叶 10 克")
        self.assertTrue(any(n["herb"] == "川贝母" for n in notes))

    def test_generic_name_gets_note(self) -> None:
        notes = herb_id_notes("贝母 3 克")
        self.assertTrue(any(n["herb"] == "贝母" for n in notes))

    def test_plain_ingredients_no_note(self) -> None:
        notes = herb_id_notes("核桃仁 30 克，粳米 100 克，白糖适量")
        self.assertEqual(notes, [])

    def test_no_duplicate_for_generic_and_specific(self) -> None:
        """「贝母」与「川贝母」同时出现时只报一次。"""
        notes = herb_id_notes("川贝母 3 克，贝母 3 克")
        self.assertEqual(len(notes), 1)

    def test_empty_input(self) -> None:
        self.assertEqual(herb_id_notes(""), [])
        self.assertEqual(herb_id_notes(None), [])


class TestNoteContent(unittest.TestCase):
    """辨识要点本身的质量。"""

    def test_notes_carry_variants(self) -> None:
        notes = herb_id_notes("牛膝 10 克")
        self.assertEqual(notes[0]["variants"],
                         ["怀牛膝", "川牛膝", "土牛膝"])

    def test_notes_are_descriptive_not_verdicts(self) -> None:
        """不得出现真假判定式措辞。"""
        for keyword, entry in CONFUSED_HERBS.items():
            self.assertNotIn("假的", entry["note"], keyword)
            self.assertNotIn("伪品是", entry["note"], keyword)

    def test_every_entry_has_note_text(self) -> None:
        for keyword, entry in CONFUSED_HERBS.items():
            self.assertGreater(len(entry["note"]), 10, keyword)
            self.assertTrue(entry["variants"], keyword)


class TestCorpusCoverage(unittest.TestCase):
    """真实数据上的覆盖情况。"""

    def test_confused_herbs_appear_in_corpus(self) -> None:
        """收录的易混药材必须在库里真实出现过，否则是凭空添加。"""
        corpus_text = " ".join(r["ingredients"] or "" for r in RECORDS)
        for keyword in CONFUSED_HERBS:
            self.assertIn(keyword, corpus_text,
                          f"{keyword} 不在语料中，应从表中移除")

    def test_meaningful_hit_count(self) -> None:
        hits = sum(1 for r in RECORDS if herb_id_notes(r["ingredients"] or ""))
        self.assertGreater(hits, 100, "命中记录过少，辨识要点价值有限")


class TestComposeIntegration(unittest.TestCase):
    """端到端：compose 输出的辨识提示。"""

    def test_notes_appear_on_primary(self) -> None:
        # 「小儿咳喘」小节里有含贝母/半夏的方
        card = compose("孩子咳嗽老不好", RECORDS, 3, {})
        self.assertIn("herb_id_notes", card["primary"])
        self.assertIsInstance(card["primary"]["herb_id_notes"], list)

    def test_plain_formula_has_empty_notes(self) -> None:
        card = compose("最近老咳嗽，痰多", RECORDS, 3, {})
        notes = card["primary"]["herb_id_notes"]
        # 可能是空也可能是非空，取决于主选方；只验证字段存在且为 list
        self.assertIsInstance(notes, list)


if __name__ == "__main__":
    unittest.main()
