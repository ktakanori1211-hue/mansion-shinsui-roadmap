"""浸水の時間の再生（①地図・②建物）を確かめる。ブラウザも API も使わない。

- 断面図の重ね絵の座標（web/samples/section_*.json）は、scripts/draw_plans.py の図と同じ値から書き出したもので、
  図の見た目（SVG）は今のままであること。
- 時間の再生の JS に、時刻・分・時間の目安や、API の呼び出しがないこと。
- 「実際の浸水速度の予測ではなく、水が順番に入る仕組みの模式」の一文が画面に出ること。
- 浸かる・止まるはサーバーの scenario から読み、JS で守られるかを計算し直さないこと。
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


class TimelineScriptTest(unittest.TestCase):
    def setUp(self):
        self.section = read("section-anim.js")
        self.map = read("map.js")

    def test_note_is_shown(self):
        self.assertIn("実際の浸水速度の予測ではなく、水が順番に入る仕組みの模式です。", self.section)
        self.assertIn("時刻や速さの予測ではなく、水が広がる順番の模式です。", self.map)

    def test_no_time_estimates(self):
        for text in (self.section, self.map, read("section-anim.css")):
            visible = re.findall(r'"[^"\n]*"|`[^`\n]*`', text)
            for value in visible:
                self.assertIsNone(re.search(r"\d+\s*(分|時間|秒|時)", value), value)

    def test_no_api_calls(self):
        self.assertNotIn("/api", self.section)
        self.assertNotIn("/api", block(self.map, "const PLAY_SECONDS", "function refresh()"))
        self.assertIn('png.replace(/\\.png$/, ".json")', self.section)

    def test_state_comes_from_the_server_scenario(self):
        self.assertIn("App.building.scenarios[`${level}:${measure}`]", self.section)
        self.assertIn("scenario.wet", self.section)
        self.assertIn("scenario.stopped", self.section)
        self.assertIn("App.setWater(now.level)", self.section)
        # 対策の名前で守られるかを決めていない（壁の穴は scenario の wet の hv で決める）。
        self.assertNotIn('measure === "hole"', self.section)
        target = block(read("model3d.js"), "function waterTarget(", "function setColor(")
        self.assertNotIn('=== "hole"', target)
        self.assertIn("!powerRoomReached(measure)", target)

    def test_water_levels_are_only_one_to_three(self):
        phase = block(self.section, "function phase(value)", "function ready()")
        self.assertIn("Math.min(3, Math.floor(value) + 1)", phase)
        self.assertIn("Math.max(1, k - 1)", phase)

    def test_map_slider_repaints_without_refetching(self):
        set_timeline = block(self.map, "function setTimeline(t)", "function playTimeline()")
        self.assertNotIn("readTile", set_timeline)
        self.assertNotIn("playScene", set_timeline)
        self.assertIn("paint(tile, progress)", set_timeline)
        # 途中で読んだタイルはその時点の進み具合で描く。
        self.assertIn("if (sim && sim.layer === this && sim.ready) paint(tile, sim.progress);", self.map)
        # 地図を押して場所を選び直さないよう、再生の枠は押しても地図へ伝えない。
        self.assertIn("L.DomEvent.disableClickPropagation(box);", self.map)
        self.assertIn("if (sim.control) map.removeControl(sim.control);", self.map)

    def test_map_stage_names_do_not_assert_road_flooding(self):
        names = re.search(r"const STAGE_NAMES = \[(.*)\];", self.map).group(1)
        self.assertIn("道路も冠水しうる", names)
        self.assertNotIn("道路が冠水する", self.map)
        self.assertIn("安全という意味ではない", self.map)

    def test_index_loads_the_new_files(self):
        html = read("index.html")
        self.assertIn('<link rel="stylesheet" href="section-anim.css">', html)
        self.assertIn('<script src="section-anim.js"></script>', html)
        self.assertLess(html.index('src="app.js"'), html.index('src="section-anim.js"'))


if __name__ == "__main__":
    unittest.main()
