"""画面と紙が読むサーバーのデータの形の検査。API は呼ばない。

2026-11-05 の一本化で、前の A4（panels.js・sim.js）の文字を読む検査は外した。
紙の文と並びの検査は tests/test_start.py に移した。
"""

import pathlib
import re
import unittest

from app import building, samples

ROOT = pathlib.Path(__file__).resolve().parent.parent
START = (ROOT / "web" / "start.js").read_text(encoding="utf-8")
RISK_ROW = [{"key": "flood", "verdict": "risk", "label": "洪水", "value": "0.5m〜3m"}]


def payload(sample_id, answers=None, confirmed=None):
    sample = samples.apply_answers(sample_id, answers) if answers else samples.SAMPLES[sample_id]
    return building.building_payload(sample, confirmed or [], RISK_ROW)


class PayloadShapeTest(unittest.TestCase):
    """画面が読むサーバーのデータの形。"""

    def test_keys_the_sheet_reads(self):
        for sample_id in "abc":
            data = payload(sample_id)
            self.assertIsInstance(data["top_line"].get("a4_notes"), list)
            # 大雨の一行は、サーバーの文のまま紙の表に出す（画面に文を写さない）。
            self.assertTrue(data["rain"]["third"])
            self.assertIn("rain?.third", START)
            self.assertIsInstance(data["rain"]["extra"], list)
            self.assertTrue(data["rain"]["set_of_three"])
            self.assertIn("note", data["chain"])
            for section in data["memos"]:
                self.assertIsInstance(section["index"], dict)
                for item in section["items"]:
                    self.assertTrue(item["no"].startswith(section["label"]))
                    self.assertIsInstance(item["sources"], list)
            for row in data["equipment"]:
                if row.get("memo_section"):
                    self.assertIn("memo_no", row)
            hole = next(m for m in data["measures"] if m["key"] == "hole")
            self.assertTrue(hole["owner"])
            self.assertIn("非硬化", hole["note"])
            tags = [row.get("tags") for row in data["scenarios"]["3:plate"]["table"] if row.get("tags")]
            self.assertTrue(tags)

    def test_conditional_data(self):
        valve = payload("c", {"tank": "yes", "tank_valve": "yes"})["rain_tank_valve"]
        self.assertTrue(valve["show"])
        self.assertNotRegex(valve["text"], r"\d")
        self.assertFalse(payload("a")["rain_tank_valve"]["show"])
        scale = payload("a", {"scale": "mid"})
        self.assertTrue(scale["scale"]["shown"])
        self.assertTrue(any("この規模で重点" in (row.get("badges") or []) for row in scale["equipment"]))
        self.assertFalse(payload("a")["scale"]["shown"])
        heights = payload("a", {"heights": {"panel_bottom": {"cm": 30, "source": "drawing"}}})["heights"]
        self.assertEqual(heights[0]["text"], "入力値：床から 30cm（竣工図）")

    def test_renewal_tier_only_where_shown(self):
        keys = lambda d: [m["key"] for m in d["measures"] if m["tier"] == "更新と一緒"]
        self.assertNotIn("gen_move", keys(payload("c")))  # 2026-11-06 本人の指示でメインの画面から外した
        self.assertEqual(keys(payload("b")), [])


if __name__ == "__main__":
    unittest.main()
