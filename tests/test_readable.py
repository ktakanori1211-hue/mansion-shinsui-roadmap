"""当事者が読めるように直した所（2026-11-04）の検査。ブラウザも API も使わない。

地形分類の7桁の番号の名前と、見本の図面（寸法線・部屋の色・断面図の基準・ピンの範囲）を確かめる。
2026-11-05 の一本化で、前の画面（3D・A4 のタブ・地図）の文字を読む検査は外し、新しい画面の検査は tests/test_start.py に移した。
"""

import re
import unittest
from pathlib import Path

from app import judge, location, samples, state
from scripts import draw_plans
from scripts.cad import Sheet, dxf

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def block(text: str, start: str, end: str) -> str:
    head = text.index(start)
    return text[head: text.index(end, head)]


class LandformNameTest(unittest.TestCase):
    def test_seven_digit_codes_have_names(self):
        # 国土地理院の style.js の表と同じ名前。番号だけを画面に出さない。
        self.assertEqual(location.LANDFORM_NAMES["3030201"], "後背低地・湿地")
        self.assertEqual(location.LANDFORM_NAMES["5010301"], "旧水部")
        self.assertEqual(location.LANDFORM_NAMES["4010201"], "盛土地・埋立地")
        self.assertEqual(location.LANDFORM_NAMES["10904"], "旧水部")

    def test_seven_digit_water_codes_are_not_clear(self):
        for code in ("3030201", "5010301", "4010201", "2010301"):
            self.assertIn(code, judge.WATER_LANDFORM_CODES, code)
            self.assertFalse(judge._landform_clean([{"status": "found", "codes": [code], "names": [location.LANDFORM_NAMES[code]]}]), code)

class DrawingTest(unittest.TestCase):
    def test_plan_picture_has_no_dimension_lines_but_cad_keeps_them(self):
        # 部屋を横切る長い通り芯の線は DXF だけ。通り芯の丸と寸法の数は、竣工図らしく絵にも出す（2026-11-07 本人の指示）。
        for sample in samples.SAMPLES.values():
            sheet = draw_plans.plan_sheet(sample)
            drawn = {item["layer"] for item in sheet.items if not item.get("cad_only")}
            self.assertNotIn("通り芯", drawn, sample["id"])
            numbers = [item["s"] for item in sheet.items if not item.get("cad_only") and item["t"] == "text" and re.fullmatch(r"[\d,]+", item.get("s", ""))]
            self.assertIn(f"{sample['plan_size'][0]:,}", numbers, sample["id"])
            self.assertIn("部屋の色", drawn, sample["id"])
            svg = draw_plans.svg(sheet)
            self.assertNotIn("#c0392b", svg, sample["id"])
            cad = dxf([sheet]).decode("cp932", "replace").split("ENTITIES", 1)[1]
            self.assertIn("通り芯\n", cad, sample["id"])
            self.assertIn("6,000", cad) if sample["id"] == "a" else None

    def test_room_names_are_twice_as_large(self):
        sheet = draw_plans.plan_sheet(samples.SAMPLES["a"])
        sizes = {item["s"]: item["size"] for item in sheet.items if item["t"] == "text"}
        self.assertGreaterEqual(sizes["電気室"], 26)
        self.assertGreaterEqual(sizes["給水ポンプ室"], 20)

    def test_room_colors_stay_out_of_cad(self):
        sheet = draw_plans.plan_sheet(samples.SAMPLES["a"])
        text = dxf([sheet]).decode("cp932", "replace")
        self.assertNotIn("部屋の色\n", text.split("ENTITIES", 1)[1])

    def test_section_anchors_do_not_move(self):
        # 断面図の重ね絵の基準の座標（section_*.json）は、図の見た目を変えても同じ。
        for sid in ("a", "b", "c"):
            saved = (WEB / "samples" / f"section_{sid}.json").read_text(encoding="utf-8")
            self.assertEqual(draw_plans.section_anchors_json(samples.SAMPLES[sid]).strip(), saved.strip(), sid)

    def test_plan_focus_keeps_every_pin_inside(self):
        for sample in samples.SAMPLES.values():
            x0, y0, x1, y1 = samples.plan_focus(sample)
            for pin in samples.client_view(sample)["pins"]:
                self.assertTrue(x0 <= pin["px"] <= x1 and y0 <= pin["py"] <= y1, (sample["id"], pin["key"]))


if __name__ == "__main__":
    unittest.main()
