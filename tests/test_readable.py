"""当事者が読めるように直した所（2026-11-04）の検査。ブラウザも API も使わない。

地形分類の7桁の番号の名前、3D の札の短さ、水の位置のボタンと再生のバーの一本化、
図面の寸法線と部屋の色、A4 の渡す相手ごとのタブを、文字として確かめる。
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

    def test_unknown_code_is_not_shown_as_a_number(self):
        names = judge._landform_names([{"codes": ["9999999"], "names": [None], "status": "found"}])
        self.assertEqual(names, ["名前の分からない分類"])
        js = read("map.js")
        self.assertNotIn("分類番号 ${code}", js)
        self.assertIn("もとは", js)
        self.assertIn("いまは", js)


class ModelLabelTest(unittest.TestCase):
    def setUp(self):
        self.model = read("model3d.js")

    def test_room_tags_are_short_names_only(self):
        self.assertIn('const SHORT_ROOM_NAMES = { elec: "電気室", tr: "変圧器室", pump: "ポンプ室"', self.model)
        fill = block(self.model, "function fillRoomTag", "const SHORT_ROOM_NAMES")
        # 判定の名前と確かめる人は、文字の札にせず title（指を置いたとき）にだけ入れる。
        self.assertNotIn("textContent = verdictLabel", fill)
        self.assertIn("head.title", fill)
        self.assertNotIn("位置は図面で未確認`;", self.model)
        self.assertIn('label("EV",', self.model)

    def test_water_buttons_and_timeline_are_one_control(self):
        html = read("index.html")
        self.assertRegex(html, r'<div class="control-group" role="radiogroup" aria-label="水の位置" hidden>')
        section = read("section-anim.js")
        strip = block(section, "bar.strip.replaceChildren(", "    const planBar")
        self.assertIn('document.createElement("button")', strip)
        self.assertIn("setTime(level)", strip)


class StopChipTest(unittest.TestCase):
    def test_chips_say_it_is_an_assumption(self):
        panels = read("panels.js")
        chips = block(panels, "function renderStopCount", "function renderSceneContext")
        self.assertIn("この水位まで来たら止まる", chips)
        self.assertIn('stopped: "止まる想定"', chips)
        self.assertNotIn("建物側から分からない", chips)


class DrawingTest(unittest.TestCase):
    def test_plan_picture_has_no_dimension_lines_but_cad_keeps_them(self):
        for sample in samples.SAMPLES.values():
            sheet = draw_plans.plan_sheet(sample)
            drawn = {item["layer"] for item in sheet.items if not item.get("cad_only")}
            self.assertNotIn("通り芯", drawn, sample["id"])
            self.assertNotIn("寸法", {item["layer"] for item in sheet.items if not item.get("cad_only") and item["t"] == "text" and re.fullmatch(r"[\d,]+", item.get("s", ""))})
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


class SheetTabsTest(unittest.TestCase):
    def test_each_sheet_says_who_gets_it(self):
        html = read("index.html")
        for sheet, who in (("sheet-front", "board"), ("sheet-back", "board"), ("sheet-memo", "memo"), ("sheet-engineer-memo", "engineer"), ("sheet-detail", "extra"), ("sheet-basis", "extra")):
            self.assertRegex(html, rf'id="{sheet}" data-for="{who}"')
        for label in ("理事会へ", "管理会社へ", "電気主任技術者へ", "全部まとめて"):
            self.assertIn(label, html)
        self.assertIn('class="sheets" id="sheets" data-show="board"', html)

    def test_print_follows_the_tab(self):
        css = read("ui-more.css")
        # 画面と印刷の両方で、選んだ相手の紙だけを出す（@media で囲まない）。
        self.assertIn('.sheets[data-show="memo"] .sheet:not([data-for="memo"])', css)
        app = read("app.js")
        self.assertIn("を印刷（PDFに保存もできます）", app)

    def test_sheet_address_is_town_level(self):
        app = read("app.js")
        self.assertIn("function townLabel(label)", app)
        panels = read("panels.js")
        self.assertIn("townLabel(App.locationState.site.label)", panels)
        self.assertNotIn("${App.locationState.site.label}", panels)


if __name__ == "__main__":
    unittest.main()


class ChainFixedTextTest(unittest.TestCase):
    def test_chain_fixed_text_is_outside_the_fold(self):
        # 本人の決定（2026-11-04）：停電の連鎖の固定の文は畳まずに出す。
        panels = read("panels.js")
        chain = block(panels, "function renderChain", "function chainFixed")
        self.assertNotIn("fixed.chain", chain)
        fixed = block(panels, "function chainFixed", "function renderTable")
        self.assertIn("App.building.fixed.chain", fixed)
        self.assertIn("App.building.chain.note", fixed)
        render = block(panels, "  function render(scenario) {", "function highlightFocus")
        self.assertIn("...chainFixed()", render)
        self.assertIn("disclaimer-line", render)
        # 下の免責と同じ「予報ではなく」の一文は、ここでは繰り返さない。
        self.assertNotIn("element(\"p\", \"本シートは予報ではなく", render)
        html = read("index.html")
        lower = block(html, '<div class="card" id="model-lower"', "</details>")
        self.assertLess(lower.index('id="model-fixed"'), lower.index("<details"))


class MiddleIssuesTest(unittest.TestCase):
    """優先度：中の課題（#2 #4 #12 #13 #14 #20 #22 #32 #33）の受け口。2026-11-04。"""

    def test_scene_count_says_what_it_counts_and_cards_are_sorted(self):
        scenes = read("scenes.js")
        self.assertIn("この土地に当てはまる水の来方：${hits}つ", scenes)
        self.assertIn("sort((a, b) => b.hits - a.hits || a.index - b.index)", scenes)

    def test_basin_callout_shows_the_difference_and_is_not_a_solid_warning(self):
        js = read("map.js")
        callout = block(js, "function callout(reading)", "function render(container")
        self.assertIn('title.textContent = "周囲より低い凹み（目安）"', callout)
        self.assertNotIn("⚠", callout)
        self.assertIn("point.elevation_m - center", callout)
        self.assertIn(".terrain-callout.callout-basin { background: #fff6ec", read("ui-more.css"))

    def test_rows_that_decide_the_answer_stand_out(self):
        app = read("app.js")
        self.assertIn("答えに効く・先に確かめる", app)
        self.assertIn("(building.top_line.steps || []).map((step) => step.key)", app)

    def test_measure_buttons_show_the_stop_count(self):
        panels = read("panels.js")
        counts = block(panels, "function renderMeasureCounts", "function render(scenario)")
        self.assertIn("App.building.scenarios[`${App.water}:${input.value}`]", counts)
        self.assertIn("止まる${stopped}", counts)
        self.assertIn("対策を選ぶと、止まる数が変わる", read("index.html"))

    def test_terms_have_meanings_with_safe_wording(self):
        app = read("app.js")
        terms = block(app, "const TERMS = {", "};")
        for word in ("借室", "キュービクル", "受電の箱", "架台", "高圧", "制御盤", "主任技術者", "竣工図", "逆止弁", "合流式"):
            self.assertIn(f'"{word}":', terms)
        self.assertIsNone(re.search(r"\d", "".join(re.findall(r": \"([^\"]+)\"", terms))))
        self.assertIn("立入は禁止です", terms)
        self.assertNotIn("あふれやすい", terms)
        self.assertIn('withTerms(LIFE[row.key] || row.label, "p", "row-life")', app)

    def test_cost_tiles_are_plain_and_lead_to_subsidy_and_consult(self):
        app = read("app.js")
        tiles = block(app, "function renderCostTiers", "function sheetTable")
        self.assertIn("決める場：", tiles)
        self.assertIn("お金：", tiles)
        self.assertNotIn('"＊"', tiles)
        html = read("index.html")
        self.assertIn('data-open-cost="sim-card"', html)
        self.assertIn('data-open-cost="consult-card"', html)

    def test_sample_shape_notice_is_visible(self):
        css = read("ui-more.css")
        self.assertIn("#plan-message, #model-fixed-top { display: inline-block;", css)
