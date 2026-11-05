"""浸水の時間の再生（①地図・②建物）を確かめる。ブラウザも API も使わない。

- 断面図の重ね絵の座標（web/samples/section_*.json）は、scripts/draw_plans.py の図と同じ値から書き出したもので、
  図の見た目（SVG）は今のままであること。
- 再生の画面（web/start.js）の検査は tests/test_start.py にある（2026-11-05 の一本化で、断面図と地図の再生は外した）。
"""

import json
import re
import unittest
from pathlib import Path

from app import building, samples
from scripts import draw_plans

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def block(text: str, start: str, end: str) -> str:
    head = text.index(start)
    return text[head: text.index(end, head)]


class SectionAnchorsTest(unittest.TestCase):
    def test_drawing_is_unchanged(self):
        for sample in samples.SAMPLES.values():
            committed = (WEB / "samples" / f"section_{sample['id']}.svg").read_text(encoding="utf-8")
            self.assertEqual(draw_plans.svg(draw_plans.section_sheet(sample)), committed, sample["id"])
            dxf = (WEB / "samples" / f"section_{sample['id']}.dxf").read_bytes()
            self.assertEqual(draw_plans.dxf([draw_plans.section_sheet(sample)]), dxf, sample["id"])

    def test_json_matches_a_fresh_export(self):
        for sample in samples.SAMPLES.values():
            on_disk = (WEB / "samples" / f"section_{sample['id']}.json").read_text(encoding="utf-8")
            self.assertEqual(on_disk, draw_plans.section_anchors_json(sample), sample["id"])

    def test_json_has_the_points_the_overlay_uses(self):
        for sample in samples.SAMPLES.values():
            data = json.loads((WEB / "samples" / f"section_{sample['id']}.json").read_text(encoding="utf-8"))
            self.assertEqual((data["width"], data["height"]), (samples.PLAN_WIDTH, samples.PLAN_HEIGHT))
            for key in ("floor_y", "ceiling_y", "levels", "rooms", "outside", "outside_levels", "equipment", "routes", "stage_names"):
                self.assertIn(key, data)
            # 画面の y は下ほど大きい。水の位置③は②より上、②は床より上。
            self.assertLess(data["levels"]["3"], data["levels"]["2"])
            self.assertLess(data["levels"]["2"], data["floor_y"])
            self.assertLess(data["outside_levels"]["3"], data["outside_levels"]["1"])
            self.assertEqual(set(data["stage_names"]), {"1", "2", "3"})
            self.assertTrue({"hv", "panel", "tr"} <= set(data["equipment"]))
            roles = {room["role"] for room in data["rooms"]}
            self.assertTrue({"power", "tr", "floor"} <= roles)

    def test_wall_hole_route_is_guarded_by_the_server_key(self):
        for sid in ("a", "c"):
            data = json.loads((WEB / "samples" / f"section_{sid}.json").read_text(encoding="utf-8"))
            hole = next(route for route in data["routes"] if route["key"] == "hole")
            self.assertEqual(hole["guard"], "hv")
            self.assertIn(hole["block"], hole["points"])
            # スロープの道は対策で止めない。
            slope = next(route for route in data["routes"] if route["key"] == "slope")
            self.assertNotIn("guard", slope)
        b = json.loads((WEB / "samples" / "section_b.json").read_text(encoding="utf-8"))
        self.assertTrue(all("guard" not in route for route in b["routes"]))

    def test_legend_text_of_the_drawing_is_the_same(self):
        for sample in samples.SAMPLES.values():
            data = json.loads((WEB / "samples" / f"section_{sample['id']}.json").read_text(encoding="utf-8"))
            svg = (WEB / "samples" / f"section_{sample['id']}.svg").read_text(encoding="utf-8")
            for name in data["stage_names"].values():
                self.assertIn(name, svg)


class ScenarioFactsTest(unittest.TestCase):
    """重ね絵が頼る scenario の形。壁の穴を塞いでも、水の位置②でエレベーターの底は浸かる。"""

    def test_hole_does_not_stop_the_lowest_floor(self):
        for sid in ("a", "b", "c"):
            table = building.scenarios(samples.get(sid), [])
            for measure in ("plate", "hole", "raise"):
                self.assertIn("ev", table[f"2:{measure}"]["wet"])
            self.assertNotIn("hv", table["3:hole"]["wet"])
            self.assertIn("hv", table["3:plate"]["wet"])
            self.assertNotIn("panel", table["3:raise"]["wet"])
            self.assertEqual(table["1:plate"]["wet"], [])


if __name__ == "__main__":
    unittest.main()
