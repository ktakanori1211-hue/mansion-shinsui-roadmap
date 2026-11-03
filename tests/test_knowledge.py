"""「調べたこと」の資料（web/knowledge.json）と要件定義（docs/REQUIREMENTS.md）の検査。

ノートのフォルダは読まない。公開側のファイルだけで、形、数字の出どころ、出してはいけない語を確かめる。
"""

import json
import pathlib
import re
import unittest

from app import guard

ROOT = pathlib.Path(__file__).resolve().parent.parent
KNOWLEDGE = json.loads((ROOT / "web" / "knowledge.json").read_text(encoding="utf-8"))
ALLOWLIST = json.loads((ROOT / "tests" / "facts_allowlist.json").read_text(encoding="utf-8"))

AREAS = {"why", "what", "market", "how", "hantei", "facts"}
LABELS = {"事実", "仮説", "決定", "機能", "注意"}
STATUSES = ["structure", "in_app", "app_content", "app_feature", "spec_only", "excluded"]
FEATURE_STATES = {"実装済み", "今回追加", "未実装", "未実装（後の決定で置き換え）", "未実装（Claude API が要る）", "資料として入れた（機能は作らない）"}

# 公開側に出さない語。実在の特定（本人の現場・勤め先・区名）と、使わないと決めた言い方。
BANNED = ["HEXSTRATA", "東国分", "美浜", "キムさん", "2-22", "世界初", "唯一", "泉区", "千葉市中央区", "stationforest", "mihama"]
# 住民も読む本文に出さない値（ノートの決まり）。「電気主任技術者の方へ」の折りたたみと要件定義には残す。
BANNED_ON_SCREEN = ["MΩ", "1,000万", "水トリー"]

# 出典の数字ではなく、この道具の設計の値・日付・番号として書いたもの。
DESIGN_VALUES = {
    "1枚", "1棟", "1名", "1回", "1行", "1つ", "1社", "3分", "4行", "20問", "1週間", "1か月", "3か月", "2時間",
    # 判定表の仮の目安（ピンの標高から −0.3m など。検証前と本文に書いてある）
    "0.3m",
    # 判定表4章の処置の費用の桁の目安。裏取りした相場ではなく、見積りに置き換えると本文に書いてある（app/assistant.py の桁と同じ）
    "150万円", "200万円", "300万円",
}


def entry_numbers(text):
    return guard.numbers_with_units(text)


class KnowledgeShapeTest(unittest.TestCase):
    def test_entries_have_the_fields_the_screen_reads(self):
        ids = set()
        for entry in KNOWLEDGE["entries"]:
            self.assertIn(entry["area"], AREAS, entry["id"])
            self.assertIn(entry["label"], LABELS, entry["id"])
            self.assertTrue(entry["title"] and entry["body"], entry["id"])
            self.assertTrue(entry["note_ids"], entry["id"])
            self.assertNotIn(entry["id"], ids)
            ids.add(entry["id"])

    def test_every_area_has_entries(self):
        self.assertEqual({entry["area"] for entry in KNOWLEDGE["entries"]}, AREAS)

    def test_coverage_adds_up(self):
        for area, counts in KNOWLEDGE["coverage"].items():
            self.assertEqual(sum(counts[key] for key in STATUSES), counts["total"], area)

    def test_feature_states_are_known(self):
        for feature in KNOWLEDGE["features"]:
            self.assertIn(feature["state"], FEATURE_STATES, feature["title"])
            self.assertTrue(feature["note_ids"], feature["title"])
            if feature["state"] != "実装済み" and feature["state"] != "今回追加":
                self.assertTrue(feature.get("reason"), feature["title"])

    def test_requirements_file_matches_the_screen(self):
        # 画面の全文は、主任技術者向けの行だけを省いた同じ文。項目番号はすべて残る。
        text = (ROOT / "docs" / "REQUIREMENTS.md").read_text(encoding="utf-8")
        screen = KNOWLEDGE["requirements"]
        self.assertEqual(text.count("\n"), screen.count("\n"))
        self.assertEqual(set(re.findall(r"［[^］]*］", text)), set(re.findall(r"［[^］]*］", screen)))
        self.assertNotIn("1,000万", text)


class KnowledgeWordsTest(unittest.TestCase):
    def public_texts(self):
        paths = [ROOT / "web" / "knowledge.json", ROOT / "tests" / "facts_allowlist.json"]
        paths += list((ROOT / "docs").glob("*.md")) + list(ROOT.glob("*.md"))
        paths += [p for p in (ROOT / "web").glob("*.js")] + [ROOT / "web" / "index.html"]
        return {p: p.read_text(encoding="utf-8") for p in paths}

    def test_banned_words_are_absent(self):
        for path, text in self.public_texts().items():
            for word in BANNED:
                self.assertNotIn(word, text, f"{path.name}: {word}")

    def test_engineer_block_keeps_what_the_body_leaves_out(self):
        engineer = json.dumps(KNOWLEDGE["engineer"], ensure_ascii=False)
        self.assertIn("MΩ", engineer)
        self.assertIn("水トリー", engineer)
        self.assertNotIn("1,000万", engineer)

    def test_screen_does_not_show_values_kept_for_engineers(self):
        screen = json.dumps(KNOWLEDGE["entries"], ensure_ascii=False) + json.dumps(KNOWLEDGE["features"], ensure_ascii=False)
        screen += KNOWLEDGE["requirements"]
        for word in BANNED_ON_SCREEN:
            self.assertNotIn(word, screen)


class KnowledgeNumbersTest(unittest.TestCase):
    def test_numbers_come_from_checked_facts(self):
        allowed = set()
        for item in ALLOWLIST:
            allowed.update(entry_numbers(item["value"]))
            allowed.update(guard.numbers_in(item["value"]))
        missing = {}
        for entry in KNOWLEDGE["entries"] + KNOWLEDGE["engineer"]["entries"]:
            for number in entry_numbers(entry["body"]):
                if number in allowed or number in DESIGN_VALUES:
                    continue
                missing.setdefault(number, entry["id"])
        self.assertEqual(missing, {})


if __name__ == "__main__":
    unittest.main()
