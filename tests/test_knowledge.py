"""「根拠と資料」（web/materials.json）と公開側のファイルの検査。

ノートのフォルダは読まない。公開側のファイルだけで、数字の出どころ、出してはいけない語、
主任技術者向けの値を住民も読む本文と分けていることを確かめる。
"""

import json
import pathlib
import re
import unittest

from app import guard

ROOT = pathlib.Path(__file__).resolve().parent.parent
MATERIALS = json.loads((ROOT / "web" / "materials.json").read_text(encoding="utf-8"))
ALLOWLIST = json.loads((ROOT / "tests" / "facts_allowlist.json").read_text(encoding="utf-8"))

# 公開側に出さない語。実在の特定（本人の現場・勤め先・区名）と、使わないと決めた言い方。
BANNED = ["HEXSTRATA", "東国分", "美浜", "キムさん", "2-22", "世界初", "唯一", "泉区", "千葉市中央区", "stationforest", "mihama"]
# 住民も読む本文に出さない値（ノートの決まり）。「電気主任技術者の方へ」の折りたたみと要件定義には残す。
BANNED_ON_SCREEN = ["MΩ", "1,000万", "水トリー"]

# 出典の数字ではなく、この道具の設計の値・日付・番号として書いたもの。
DESIGN_VALUES = {"1枚", "1棟", "1名", "1回", "1行", "1つ", "1社", "3分", "4行", "20問", "1週間", "1か月", "3か月", "2時間"}


def body_texts(section):
    """住民・理事・管理員も読む本文（出典名は除く）。"""
    texts = [section.get("title", ""), section.get("lead", "")]
    texts += section.get("body", [])
    texts += [f"{item['value']} {item['text']}" for item in section.get("figures", [])]
    for item in section.get("voices", []):
        texts += [item["who"], item["honne"], item["answer"], item.get("note", "")]
    for item in section.get("steps", []):
        texts += [item["head"], item["text"]]
    for item in section.get("verdicts", []):
        texts += [item["name"], item["short"], item["text"]]
    for item in section.get("parts", []):
        texts += [item["heading"], *item["body"]]
    return texts


def screen_texts():
    texts = [MATERIALS["lead"]]
    for section in MATERIALS["sections"]:
        texts += body_texts(section)
    return texts


def engineer_texts():
    engineer = MATERIALS["engineer"]
    texts = [engineer["summary"], engineer["fixed"]]
    for item in engineer["items"]:
        texts += [item["title"], *item["body"]]
    return texts


class MaterialsWordsTest(unittest.TestCase):
    def public_texts(self):
        paths = [ROOT / "web" / "materials.json", ROOT / "tests" / "facts_allowlist.json"]
        paths += list((ROOT / "docs").glob("*.md")) + list(ROOT.glob("*.md"))
        paths += [p for p in (ROOT / "web").glob("*.js")] + [ROOT / "web" / "index.html"]
        return {p: p.read_text(encoding="utf-8") for p in paths}

    def test_banned_words_are_absent(self):
        for path, text in self.public_texts().items():
            for word in BANNED:
                self.assertNotIn(word, text, f"{path.name}: {word}")

    def test_engineer_block_keeps_what_the_body_leaves_out(self):
        engineer = "\n".join(engineer_texts())
        self.assertIn("MΩ", engineer)
        self.assertIn("水トリー", engineer)
        self.assertNotIn("1,000万", engineer)
        self.assertIn("住民・理事・管理員向けではありません", MATERIALS["engineer"]["summary"])

    def test_screen_does_not_show_values_kept_for_engineers(self):
        screen = "\n".join(screen_texts())
        for word in BANNED_ON_SCREEN:
            self.assertNotIn(word, screen)

    def test_requirements_file_leaves_out_the_maker_amount(self):
        self.assertNotIn("1,000万", (ROOT / "docs" / "REQUIREMENTS.md").read_text(encoding="utf-8"))


class MaterialsWhyWhatTest(unittest.TestCase):
    """今の流れ・住民が失うもの・お金の流れ・行政との接点・既存との違いの節。"""

    NEW_IDS = ["flow", "loss", "market", "gyosei", "hikaku"]

    def sections(self):
        return {section["id"]: section for section in MATERIALS["sections"]}

    def test_new_sections_exist_with_one_face_line(self):
        sections = self.sections()
        for section_id in self.NEW_IDS:
            self.assertIn(section_id, sections)
            section = sections[section_id]
            self.assertTrue(section["lead"])
            self.assertNotIn("\n", section["lead"])
            # 表面は太字の一行と、多くても大きな値一つ。12段階などの詳しい文は折りたたみへ。
            self.assertNotIn("steps", section)
            self.assertLessEqual(len(section.get("figures", [])), 1)
            self.assertTrue(section.get("body") or section.get("parts"))

    def test_new_sections_avoid_banned_claims(self):
        sections = self.sections()
        for section_id in self.NEW_IDS:
            text = "\n".join(body_texts(sections[section_id]))
            for word in ["世界初", "唯一", "日本初", "分からない＝危険", "データが外に出ない", "安心"]:
                self.assertNotIn(word, text, f"{section_id}: {word}")

    def test_absence_claims_carry_the_survey_date(self):
        for text in screen_texts():
            for sentence in re.split(r"(?<=。)", text):
                if "見当たら" in sentence or "見つけられなかった" in sentence:
                    self.assertIn("調べた範囲（10/21 時点）で", sentence)

    def test_flow_covers_twelve_steps_and_says_which_the_tool_takes(self):
        flow = self.sections()["flow"]
        self.assertIn("1〜5と12", flow["lead"])
        for number in range(1, 13):
            self.assertTrue(any(line.startswith(f"{number} ") for line in flow["body"]), number)

    def test_market_states_no_referral_fee_and_undecided_price(self):
        text = "\n".join(body_texts(self.sections()["market"]))
        self.assertIn("紹介料は取りません", text)
        self.assertIn("値段は、まだ決めていません", text)


class MaterialsNumbersTest(unittest.TestCase):
    def test_numbers_come_from_checked_facts(self):
        allowed = set()
        for item in ALLOWLIST:
            allowed.update(guard.numbers_with_units(item["value"]))
            allowed.update(guard.numbers_in(item["value"]))
        missing = {}
        for text in screen_texts() + engineer_texts():
            for number in guard.numbers_with_units(text):
                if number in allowed or number in DESIGN_VALUES:
                    continue
                missing.setdefault(number, text[:40])
        self.assertEqual(missing, {})

    def test_percentages_come_from_checked_facts(self):
        # 単位つきの検査は % を拾わないので、% の値は出典を確かめた値の一覧と文字どおりに突き合わせる。
        allowed = {item["value"] for item in ALLOWLIST}
        missing = set()
        for text in screen_texts() + engineer_texts():
            for value in re.findall(r"\d+(?:\.\d+)?%", text):
                if value not in allowed:
                    missing.add(value)
        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
