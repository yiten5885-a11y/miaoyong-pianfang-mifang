#!/usr/bin/env python3
"""Tests for the personal interaction gate (S3).

    python3 -m unittest discover -s tests -p 'test_*.py'

The profile path is redirected to a temporary file for every test so the
developer's own profile is never read or written.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import profile as profile_mod  # noqa: E402
from interactions import (  # noqa: E402
    INTERACTION_RULES, detect_route, evaluate, normalize_drugs, unknown_drugs,
    worst_level,
)
from improve import compose, display_title  # noqa: E402
from search import load_records  # noqa: E402


class ProfileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "profile.json"
        self._prev = os.environ.get(profile_mod.ENV_VAR)
        os.environ[profile_mod.ENV_VAR] = str(self.path)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop(profile_mod.ENV_VAR, None)
        else:
            os.environ[profile_mod.ENV_VAR] = self._prev
        self._tmp.cleanup()


class TestProfileStorage(ProfileTestCase):
    def test_absent_profile_is_empty_and_inert(self) -> None:
        profile = profile_mod.load_profile()
        self.assertTrue(profile_mod.is_empty(profile))
        self.assertEqual(profile["conditions"], [])
        self.assertIn("未建立", profile_mod.describe(profile))

    def test_save_and_reload_roundtrip(self) -> None:
        profile_mod.update_profile({
            "conditions": ["高血压", "2型糖尿病"],
            "medications": ["氨氯地平", "二甲双胍"],
            "allergies": ["蜂蜜"],
        })
        reloaded = profile_mod.load_profile()
        self.assertEqual(reloaded["conditions"], ["高血压", "2型糖尿病"])
        self.assertEqual(reloaded["allergies"], ["蜂蜜"])
        self.assertIn("antihypertensive", reloaded["_drug_classes"])
        self.assertIn("antidiabetic", reloaded["_drug_classes"])

    def test_derived_fields_are_not_persisted(self) -> None:
        profile_mod.update_profile({"conditions": ["高血压"]})
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("_drug_classes", raw)

    def test_add_and_remove_modes(self) -> None:
        profile_mod.update_profile({"conditions": ["高血压"]})
        profile_mod.update_profile({"conditions": ["糖尿病"]}, mode="add")
        self.assertEqual(profile_mod.load_profile()["conditions"],
                         ["高血压", "糖尿病"])
        profile_mod.update_profile({"conditions": ["高血压"]}, mode="remove")
        self.assertEqual(profile_mod.load_profile()["conditions"], ["糖尿病"])

    def test_comma_and_enumeration_separators(self) -> None:
        profile = profile_mod.update_profile({"conditions": "高血压、糖尿病, 脂肪肝"})
        self.assertEqual(profile["conditions"], ["高血压", "糖尿病", "脂肪肝"])

    def test_clear_removes_the_file(self) -> None:
        profile_mod.update_profile({"conditions": ["高血压"]})
        self.assertTrue(profile_mod.clear_profile())
        self.assertFalse(profile_mod.clear_profile())
        self.assertTrue(profile_mod.is_empty(profile_mod.load_profile()))

    def test_file_permissions_are_owner_only(self) -> None:
        profile_mod.update_profile({"conditions": ["高血压"]})
        mode = self.path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, oct(mode))

    def test_unknown_medication_is_surfaced_not_guessed(self) -> None:
        profile = profile_mod.update_profile({"medications": ["某种新药"]})
        self.assertEqual(profile["_unknown_drugs"], ["某种新药"])
        self.assertEqual(profile["_drug_classes"], [])


class TestDrugLexicon(unittest.TestCase):
    def test_brand_and_generic_both_map(self) -> None:
        self.assertIn("antihypertensive", normalize_drugs(["氨氯地平"]))
        self.assertIn("antihypertensive", normalize_drugs(["降压药"]))

    def test_unknown_returns_empty(self) -> None:
        self.assertEqual(normalize_drugs(["完全不认识的药"]), [])
        self.assertEqual(unknown_drugs(["完全不认识的药"]), ["完全不认识的药"])

    def test_rule_table_is_well_formed(self) -> None:
        for rule in INTERACTION_RULES:
            self.assertIn(rule["level"], ("block", "warn"), rule["id"])
            self.assertTrue(rule["herbs"], rule["id"])
            self.assertTrue(rule["triggers"], rule["id"])
            self.assertTrue(rule["reason"], rule["id"])
            self.assertTrue(rule["action"], rule["id"])


class TestRouteDetection(unittest.TestCase):
    def test_external_is_detected(self) -> None:
        self.assertEqual(detect_route("把麻黄研碎，放膏药上，貼肺俞穴。"), "external")
        self.assertEqual(detect_route("捣烂外敷患处。"), "external")

    def test_internal_is_detected(self) -> None:
        self.assertEqual(detect_route("水煎服。每日1剂。"), "internal")

    def test_ambiguous_is_unknown(self) -> None:
        self.assertEqual(detect_route(""), "unknown")


class TestInteractionEngine(unittest.TestCase):
    def test_mahuang_blocks_for_hypertension(self) -> None:
        hits = evaluate("麻黄10克，甘草6克。", {"conditions": ["高血压"]})
        self.assertEqual(worst_level(hits), "block")
        self.assertIn("mahuang-htn", [h["id"] for h in hits])

    def test_no_profile_means_no_hits(self) -> None:
        self.assertEqual(evaluate("麻黄10克。", {}), [])
        self.assertEqual(evaluate("麻黄10克。", {"conditions": []}), [])

    def test_herb_alone_does_not_fire(self) -> None:
        """麻黄 without a matching trigger must stay silent."""
        hits = evaluate("麻黄10克。", {"conditions": ["糖尿病"]})
        self.assertEqual(hits, [])

    def test_trigger_alone_does_not_fire(self) -> None:
        hits = evaluate("白菜100克。", {"conditions": ["高血压"]})
        self.assertEqual(hits, [])

    def test_external_route_downgrades_block_to_warn(self) -> None:
        text = "麻黄3克，膏药1张。把麻黄研碎，放膏药上，貼肺俞穴。"
        hits = evaluate(text, {"conditions": ["高血压"]},
                        usage_text="把麻黄研碎，放膏药上，貼肺俞穴。")
        self.assertEqual(worst_level(hits), "warn")
        self.assertEqual(hits[0]["route"], "external")
        self.assertTrue(hits[0]["note"])

    def test_anticoagulant_plus_huoxue_blocks(self) -> None:
        hits = evaluate("丹参15克，当归10克。",
                        {"medications": ["华法林"]})
        self.assertEqual(worst_level(hits), "block")

    def test_alcohol_with_metronidazole_blocks(self) -> None:
        hits = evaluate("黄酒50毫升。", {"medications": ["甲硝唑"]})
        self.assertEqual(worst_level(hits), "block")
        self.assertIn("alcohol-disulfiram", [h["id"] for h in hits])

    def test_pregnancy_blocks_huoxue(self) -> None:
        hits = evaluate("红花6克，桃仁9克。", {"special": ["孕期"]})
        self.assertEqual(worst_level(hits), "block")

    def test_longest_name_wins(self) -> None:
        """麻黄根 is a different herb and must not trigger the 麻黄 rules."""
        hits = evaluate("麻黄根15克。", {"conditions": ["高血压"]})
        self.assertEqual(hits, [])

    def test_hits_are_sorted_block_first(self) -> None:
        hits = evaluate("麻黄6克，甘草6克。",
                        {"conditions": ["高血压"], "medications": ["华法林"]})
        self.assertEqual(hits[0]["level"], "block")


class TestComposeGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_records(ROOT / "assets" / "records.jsonl")

    def test_display_title_falls_back_for_unnamed(self) -> None:
        record = {"title": "", "condition": "坐骨神经痛", "formula_no": 3}
        self.assertIn("第3方", display_title(record))
        self.assertIn("原书未列方名", display_title(record))

    def test_display_title_keeps_the_book_name(self) -> None:
        record = {"title": "神仙粥治风寒感冒", "condition": "感冒", "formula_no": 1}
        self.assertEqual(display_title(record), "神仙粥治风寒感冒")

    def test_empty_profile_leaves_card_ungated(self) -> None:
        empty = {"conditions": [], "medications": [], "allergies": [],
                 "special": [], "diet": []}
        card = compose("咳嗽", self.records, 5, empty)
        self.assertEqual(card["mode"], "remedy")
        self.assertFalse(card["profile_gate"]["switched"])
        self.assertEqual(card["profile_gate"]["primary_interactions"], [])

    def test_gate_switches_away_from_a_blocked_formula(self) -> None:
        card = compose("坐骨神经痛", self.records, 6,
                       {"conditions": ["高血压"], "medications": [],
                        "allergies": [], "special": [], "diet": []})
        self.assertEqual(card["mode"], "remedy")
        gate = card["profile_gate"]
        self.assertTrue(gate["switched"])
        self.assertTrue(gate["blocked"])
        self.assertNotIn("麻黄",
                         card["primary"]["original_ingredients"] or "")

    def test_allergy_blocks_regardless_of_route(self) -> None:
        card = compose("咳嗽", self.records, 20,
                       {"conditions": [], "medications": [],
                        "allergies": ["麻黄"], "special": [], "diet": []})
        self.assertEqual(card["mode"], "remedy")
        self.assertTrue(card["profile_gate"]["blocked"])

    def test_emergency_still_short_circuits_with_profile(self) -> None:
        card = compose("突然胸痛呼吸困难", self.records, 3,
                       {"conditions": ["高血压"], "medications": [],
                        "allergies": [], "special": [], "diet": []})
        self.assertEqual(card["mode"], "emergency")

    def test_card_carries_the_profile_summary(self) -> None:
        card = compose("咳嗽", self.records, 3,
                       {"conditions": ["高血压"], "medications": ["氨氯地平"],
                        "allergies": [], "special": [], "diet": []})
        self.assertIn("profile", card)
        self.assertFalse(card["profile"]["is_empty"])
        self.assertIn("antihypertensive", card["profile"]["drug_classes"])

    def test_warn_keeps_the_formula_but_marks_it_yellow(self) -> None:
        card = compose("咳嗽", self.records, 20,
                       {"conditions": ["高血压"], "medications": [],
                        "allergies": [], "special": [], "diet": []})
        warned = [a for a in card["alternatives"] if a["interactions"]]
        for alt in warned:
            self.assertEqual(alt["interactions"][0]["level"], "warn")
        if warned:
            self.assertIn(card["safety"]["tier"]["colour"], ("green", "yellow"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
