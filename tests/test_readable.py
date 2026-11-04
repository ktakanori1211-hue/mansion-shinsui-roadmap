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
        strip = block(section, "bar.strip.replaceChildren(", "renderLife(bar, now);")
        self.assertIn('document.createElement("button")', strip)
        self.assertIn("setStory(", strip)


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
        # 安全の一文はページ下の免責と二重にせず、3D で危ない部屋を選んだときだけ 3D の下に強調して出す。
        self.assertNotIn("disclaimer-line", render)
        self.assertIn('getElementById("model-safety").textContent = App.disclaimerText()', render)
        focus = block(panels, "function highlightFocus", "return { renderControls")
        self.assertIn("safety.hidden = !shown", focus)
        self.assertIn('document.getElementById("pin-card").hidden', focus)
        self.assertIn('id="model-safety" hidden', read("index.html"))
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


class LowIssuesTest(unittest.TestCase):
    """優先度：低の課題（#6 #15 #16 #25 #34）と、3D の補助の札の一行化。2026-11-04。"""

    def test_low_items(self):
        html = read("index.html")
        app = read("app.js")
        self.assertIn('class="primary banner-next" data-go="3"', html)
        self.assertNotIn("最初の手は数万〜十数万円", html)
        self.assertIn("色がない所も、安全という意味ではありません。", app)
        self.assertIn('fold("くわしく", detailItems({ ...row', app)
        self.assertIn('<details class="card" id="share-card">', html)

    def test_detail_labels_in_3d_are_one_line(self):
        model = read("model3d.js")
        self.assertIn('node.title = rest.join(" ")', model)


class SimulationCardTest(unittest.TestCase):
    """②の作り直し（2026-11-04）：断面図を主役にした一枚のカード、図面のビューアー、水位の物語、3D の色。"""

    def test_one_card_with_section_first(self):
        html = read("index.html")
        card = block(html, '<section class="card sim-card" id="plan-card"', "</section>")
        for part in ('id="sim-viewer"', 'id="plan-stage"', 'id="model-view"', 'data-zoom="in"', 'data-zoom="full"', 'id="measure-controls"'):
            self.assertIn(part, card)
        self.assertNotIn('class="stage2-grid"', html)
        plan = read("plan.js")
        self.assertIn('named("断面で見る（水の入り道）", "section"), named("3Dで見る", "model")', plan)
        self.assertIn('let shownKind = "section";', plan)

    def test_viewer_zooms_pans_and_goes_fullscreen(self):
        plan = read("plan.js")
        for part in ("function zoomAt", "function clampView", '"wheel"', "pointermove", "requestFullscreen", "fullscreenchange", "ZOOM_MAX = 8"):
            self.assertIn(part, plan)
        # 見本の図は SVG で出して、拡大しても字がにじまないようにする。
        self.assertIn('path.replace(/\\.png$/, ".svg")', plan)
        self.assertIn("scale: 3", plan)
        self.assertIn("scale(calc(1 / var(--zoom, 1)))", read("ui-more.css"))

    def test_section_is_cropped_to_its_drawing(self):
        for sid in ("a", "b", "c"):
            anchors = draw_plans.section_anchors(samples.SAMPLES[sid])
            x0, y0, x1, y1 = anchors["focus"]
            self.assertTrue(0 <= x0 < x1 <= anchors["width"] and 0 <= y0 < y1 <= anchors["height"], sid)
            for room in anchors["rooms"]:
                self.assertTrue(x0 <= room["x0"] and room["x1"] <= x1, (sid, room["name"]))
        self.assertIn('new CustomEvent("section-anchors"', read("section-anim.js"))

    def test_one_story_bar_with_outcomes(self):
        section = read("section-anim.js")
        init = block(section, "function init()", "init();")
        self.assertEqual(init.count("makeBar("), 1)
        # 水位の①②③ではなく、住民が過ごす時間の順（サーバーの五段の表の列と同じ名前）で見せる。
        for name in ("大雨が近づいたとき", "水が来た当日", "水が引いた翌朝", "数日〜1週間", "約2か月〜本復旧"):
            self.assertIn(f'name: "{name}"', section)
            self.assertIn(name, read("panels.js"))
        self.assertIn("外は乾いても、地下に水", section)
        self.assertIn("{ idx, out: 0, inn: 3, t: 3, level: 3 }", section)
        self.assertIn('row.label === "人がすること"', section)
        self.assertIn("setFlow(flow, inside)", read("model3d.js"))

    def test_3d_rooms_follow_drawing_colors(self):
        model = read("model3d.js")
        self.assertIn("power: 0xf2b97a", model)
        self.assertIn("waterRoom: 0x8fc2ea", model)
        self.assertIn("const levels = Math.min(sample.floors - 1, 3);", model)


class StageThreeNextStepsTest(unittest.TestCase):
    """③の作り直し（2026-11-04）：このあと、あなたがすること、紙は縮めて並べる、印刷で白紙を出さない。"""

    def test_next_steps_lead_the_page(self):
        html = read("index.html")
        stage = block(html, '<section class="stage" data-stage="3"', '<section class="stage" data-stage="materials"')
        self.assertLess(stage.index('id="next-steps"'), stage.index('id="cost-tiers"'))
        for word in ('data-step="board"', 'data-step="memo"', 'data-step="answers"', "理事会で、表裏1枚を配る", "管理会社に、依頼メモを渡す", "返ってきた答えを、②の質問に入れる"):
            self.assertIn(word, stage)
        # 紙の置き場は .card にしない（印刷で .card を隠す決まりがあるため）。
        self.assertIn('<div class="sheet-area" id="sheet-area">', stage)
        self.assertIn('<details class="card other-docs" id="exits-card">', stage)

    def test_sheets_start_small_and_print_without_blank_pages(self):
        css = read("ui-more.css")
        self.assertIn(".sheets:not(.is-large) .sheet { zoom: .62; }", css)
        self.assertIn('.sheets[data-show="board"] #sheet-back,', css)
        self.assertIn('sheets.classList.toggle("is-large")', read("app.js"))


class GlanceTest(unittest.TestCase):
    """②の一番上「うちのマンションで起きること」（2026-11-04）：電気を知らない人に一目で伝える。"""

    def setUp(self):
        self.js = read("glance.js")

    def test_placed_first_and_loaded(self):
        html = read("index.html")
        self.assertLess(html.index('id="glance"'), html.index('id="top-banner"'))
        self.assertLess(html.index('src="app.js"'), html.index('src="glance.js"'))
        self.assertIn("window.Glance?.render();", read("app.js"))

    def test_no_electrical_jargon_in_the_words_people_read(self):
        visible = "".join(re.findall(r'"[^"\n]*"|`[^`\n]*`', self.js))
        for word in ("受電", "借室", "キュービクル", "盤", "高圧", "変圧器", "主任技術者"):
            self.assertNotIn(word, visible, word)
        for word in ("電気の機械", "水を送るポンプ", "あなたの暮らしでは", "住んでいる階"):
            self.assertIn(word, self.js)

    def test_states_and_days_come_from_the_server(self):
        self.assertIn("App.building?.scenarios?.[`3:${App.measure}`]", self.js)
        self.assertIn("/ほかの建物の例/", self.js)
        # 新しい日数を書かない（住んでいる階は本人の数をそのまま使う）。
        days = re.findall(r"\d+\s*(日|か月|年)", "".join(re.findall(r'"[^"\n]*"', self.js)))
        self.assertEqual(days, [])


class BoardOneSheetTest(unittest.TestCase):
    """②は「理事会で、最初に見る1枚」だけを見せ、ほかは「くわしく見る」に畳む（2026-11-04）。"""

    def test_three_places_to_look_and_the_rest_folded(self):
        js = read("glance.js")
        for part in ("理事会で、最初に見る1枚", "あなたの暮らしでは", "次の理事会で決めること", "管理会社に、3つの確認を頼む", "管理会社への依頼メモを印刷"):
            self.assertIn(part, js)
        html = read("index.html")
        more = block(html, '<details class="stage2-more" id="stage2-more" hidden>', '<div class="stage-next">')
        for part in ('id="top-banner"', 'id="plan-card"', 'id="step-building"', 'id="step-result"', 'id="model-lower"'):
            self.assertIn(part, more)
        self.assertNotIn('id="glance"', more)

    def test_board_asks_are_in_plain_words(self):
        js = read("glance.js")
        asks = block(js, "const PLAIN_ASK = {", "};")
        for word in ("盤", "受電", "借室", "主任技術者"):
            self.assertNotIn(word, asks)
        self.assertIn("PLAIN_ASK[item.key] || item.what", js)
