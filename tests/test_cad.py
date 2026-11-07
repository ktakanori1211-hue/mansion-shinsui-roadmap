"""web/cad.js（CAD 風の平面図・断面図）を JavaScriptCore で動かして、返す形を確かめる。

ブラウザは使わず、tests/surface.py と同じく osascript -l JavaScript で評価する。
見本 A・B・C の実データ（samples.client_view）を渡し、部屋の箱・印・通り芯・寸法・題が出ることを見る。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import samples

ROOT = Path(__file__).resolve().parent.parent
CAD_JS = ROOT / "web" / "cad.js"

SECTIONS = {
    "a": {"floors": 11, "basement": 1, "rooms": [{"key": k, "label": k} for k in ("elec", "tr", "pump", "water_tank", "ev", "stair", "park")], "panelMount": "壁掛け", "undergroundFeed": True, "hasSlope": True, "pit": True},
    "b": {"floors": 5, "basement": 0, "rooms": [{"key": k, "label": k} for k in ("panel_room", "tr", "pump", "ev", "stair")], "panelMount": "架台の上", "undergroundFeed": False, "hasSlope": False, "pit": False},
    "c": {"floors": 38, "basement": 1, "rooms": [{"key": k, "label": k} for k in ("elec", "tr", "gen", "pump", "tank", "ev", "stair")], "panelMount": "形は未確認", "undergroundFeed": True, "hasSlope": True, "pit": True},
}

RENDER = r"""
var out = { plans: {}, sections: {} };
Object.keys(DATA).forEach(function (id) {
  DATA[id].views.forEach(function (view, i) {
    var r = CAD.plan(DATA[id], i, {}), c = CAD.plan(DATA[id], i, { compact: true });
    out.plans[id + ":" + i] = { w: r.w, h: r.h, svg: r.svg, rooms: r.rooms, marks: r.marks, origin: r.px(0, 0), compactSvg: c.svg, compactH: c.h };
  });
});
Object.keys(SECTIONS).forEach(function (id) {
  var s = CAD.section(SECTIONS[id]);
  out.sections[id] = { w: s.w, h: s.h, svg: s.svg, rooms: s.rooms, levels: s.levels, routes: s.routes, floorsY: s.floorsY };
});
out.esc = CAD.esc('<a href="x">&\'</a>');
JSON.stringify(out);
"""


def run_cad() -> dict:
    data = {k: samples.client_view(samples.SAMPLES[k]) for k in ("a", "b", "c")}
    script = CAD_JS.read_text(encoding="utf-8") + "\nvar DATA = " + json.dumps(data, ensure_ascii=False) + ";\nvar SECTIONS = " + json.dumps(SECTIONS, ensure_ascii=False) + ";\n" + RENDER
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run(["osascript", "-l", "JavaScript", path], capture_output=True, text=True, timeout=60)
    Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-800:])
    return json.loads(result.stdout.strip())


@unittest.skipUnless(shutil.which("osascript"), "JavaScriptCore（osascript）がない")
class CadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = run_cad()

    def test_source_has_no_dom_and_is_plain_script(self):
        src = CAD_JS.read_text(encoding="utf-8")
        self.assertNotRegex(src, r"\bdocument\.")
        self.assertNotRegex(src, r"^\s*(import|export)\b", "ES モジュールにしない")
        self.assertIn("root.CAD = CAD", src)

    def test_esc(self):
        self.assertEqual(self.out["esc"], "&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;")

    def test_plan_rooms_marks_and_cad_elements(self):
        for sample_id in ("a", "b", "c"):
            view_list = samples.SAMPLES[sample_id]["views"]
            for index, view in enumerate(view_list):
                plan = self.out["plans"][f"{sample_id}:{index}"]
                with self.subTest(sample=sample_id, view=view["name"]):
                    self.assertEqual(plan["w"], 700)
                    self.assertGreater(plan["h"], 100)
                    svg = plan["svg"]
                    self.assertNotIn("<svg", svg, "外側の <svg> は呼ぶ側が包む")
                    keys = {room["key"] for room in view["rooms"]}
                    self.assertEqual(set(plan["rooms"]), keys)
                    for key, box in plan["rooms"].items():
                        self.assertTrue(all(isinstance(box[k], (int, float)) for k in ("x", "y", "w", "h")), key)
                        self.assertGreater(box["w"], 0)
                        self.assertGreater(box["h"], 0)
                        self.assertIn(f'data-room="{key}"', svg)
                    self.assertEqual(svg.count('class="cad-room"'), len(view["rooms"]))
                    # 通り芯の丸、2 段の寸法、全体の寸法、題
                    self.assertIn(">X1<", svg)
                    self.assertIn(">Y1<", svg)
                    width = max(room["mm"][2] for room in view["rooms"])
                    total = f"{width:,}"
                    self.assertIn(f">{total}<", svg)
                    self.assertNotIn(f">{total}<", plan["compactSvg"], "小さい画面では寸法の数を省く")
                    self.assertIn(">X1<", plan["compactSvg"])
                    self.assertIn(f"{view['name']}　S=1/100", svg)
                    self.assertEqual(plan["origin"], [74, 72])
                    # 印：図のものは全部、外壁の建具は opening として返す
                    kinds = [mark["kind"] for mark in plan["marks"]]
                    for mark in view["marks"]:
                        self.assertIn(mark["kind"], kinds)
                    openings = [mark for mark in plan["marks"] if mark["kind"] == "opening"]
                    for opening in openings:
                        self.assertIn(opening["side"], ("top", "bottom", "left", "right"))
                        self.assertIn("openingKind", opening)
                        self.assertGreater(opening["w"], 0)

    def test_plan_exterior_openings_only(self):
        # 見本 A の 1 階：車路のシャッター（上辺）と風除室の引き戸（下辺）は外壁、EV の開口は外壁ではない
        plan = self.out["plans"]["a:1"]
        exterior = {(m["room"], m["openingKind"]) for m in plan["marks"] if m["kind"] == "opening"}
        self.assertIn(("slope", "shutter"), exterior)
        self.assertIn(("wind", "sliding"), exterior)
        self.assertNotIn(("ev_1f", "open"), exterior)

    def test_plan_draws_marks_of_each_kind(self):
        a1 = self.out["plans"]["a:1"]["svg"]
        self.assertIn("歩道", a1)
        self.assertIn("前の道路", a1)
        self.assertIn("HH", a1)
        b0 = self.out["plans"]["b:0"]["svg"]
        self.assertIn("電柱", b0)
        self.assertIn("丘の側", b0)
        c1 = self.out["plans"]["c:1"]["svg"]
        self.assertIn("雨水ます", c1)
        self.assertIn("ケーブルを通す壁の穴", self.out["plans"]["a:0"]["svg"])
        self.assertIn("UP ", self.out["plans"]["a:1"]["svg"], "階段に UP と段数")

    def test_section_shapes(self):
        for sample_id, spec in SECTIONS.items():
            section = self.out["sections"][sample_id]
            with self.subTest(sample=sample_id):
                self.assertEqual(section["w"], 700)
                self.assertLessEqual(section["h"], 1.3 * 700)
                keys = {room["key"] for room in spec["rooms"]}
                self.assertTrue(keys <= set(section["rooms"]))
                for key in keys:
                    self.assertIn(f'data-room="{key}"', section["svg"])
                levels = section["levels"]
                self.assertEqual(set(levels), {"1", "2", "3"})
                self.assertLess(levels["3"], levels["2"], "③は②より高い（y が小さい）")
                if spec["basement"]:
                    self.assertLess(levels["1"], levels["3"], "道路は地下の床より高い")
                routes = {route["key"]: route for route in section["routes"]}
                self.assertIn("door", routes)
                self.assertEqual("hole" in routes, spec["undergroundFeed"])
                self.assertEqual("slope" in routes, spec["hasSlope"])
                for route in routes.values():
                    self.assertGreaterEqual(len(route["points"]), 2)
                    self.assertEqual(len(route["block"]), 2)
                labels = [f["label"] for f in section["floorsY"]]
                self.assertEqual(labels[0], "B1FL" if spec["basement"] else "1FL")
                self.assertEqual(labels[-1], "RFL")
                self.assertIn(f"{spec['floors']}FL", labels)
                ys = [f["y"] for f in section["floorsY"]]
                self.assertEqual(ys, sorted(ys, reverse=True), "下の階ほど y が大きい")
                # 機械室の階（2FL から下）は高さの 28% 以上
                y2 = next(f["y"] for f in section["floorsY"] if f["label"] == "2FL")
                self.assertGreaterEqual((section["h"] - y2) / section["h"], 0.28)
                self.assertIn("HH", section["svg"]) if spec["undergroundFeed"] else self.assertNotIn(">HH<", section["svg"])
                self.assertIn(str(spec["panelMount"]), section["svg"])

    def test_section_tower_break(self):
        tower = self.out["sections"]["c"]
        labels = [f["label"] for f in tower["floorsY"]]
        self.assertEqual(labels, ["B1FL", "1FL", "2FL", "3FL", "4FL", "5FL", "6FL", "7FL", "8FL", "36FL", "37FL", "38FL", "RFL"])
        self.assertIn("省略", tower["svg"])
        self.assertNotIn("省略", self.out["sections"]["a"]["svg"])

    def test_section_floor_labels_do_not_pile_up(self):
        # 上の階を縮めても、左の階の名前（Zn の丸と「3FL」）は 18 px 未満で重ならない。必ず出す階は残し、floorsY は全部返す。
        for sample_id in ("a", "b", "c"):
            section = self.out["sections"][sample_id]
            with self.subTest(sample=sample_id):
                labels = re.findall(r'<text x="28" y="([\d.]+)"[^>]*>([^<]*FL)</text>', section["svg"])
                self.assertTrue(labels)
                ys = sorted(float(y) for y, _ in labels)
                gaps = [b - a for a, b in zip(ys, ys[1:])]
                self.assertTrue(all(gap >= 18 for gap in gaps), (sample_id, gaps))
                names = {name for _, name in labels}
                for must in ("1FL", "2FL", "RFL") + (("B1FL",) if SECTIONS[sample_id]["basement"] else ()):
                    self.assertIn(must, names)
                self.assertEqual(section["svg"].count('<circle cx="18"'), len(labels), "丸と名前は同じ階に出す")
                self.assertGreaterEqual(len(section["floorsY"]), len(labels))
        self.assertIn("2,900×", self.out["sections"]["c"]["svg"], "縮めた階の続きは階高をまとめる")

    def test_plan_conduit_label_clears_site_line(self):
        # 引込管路の字は、敷地境界線（建物の下 1,000 mm）に触れず、白い縁取りを持つ
        for key in ("a:1", "c:1"):
            plan = self.out["plans"][key]
            label = re.search(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>引込管路</text>', plan["svg"])
            self.assertIsNotNone(label, key)
            site = next(m for m in plan["marks"] if m["kind"] == "road")["y"]
            self.assertGreater(abs(float(label.group(2)) - site), 5, key)
            self.assertIn('paint-order="stroke"', label.group(0))

    def test_no_real_building_words(self):
        for key, plan in self.out["plans"].items():
            self.assertNotRegex(plan["svg"], r"(株式会社|丁目|[0-9]{3}-[0-9]{4})", key)


if __name__ == "__main__":
    unittest.main()
