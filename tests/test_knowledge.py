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
