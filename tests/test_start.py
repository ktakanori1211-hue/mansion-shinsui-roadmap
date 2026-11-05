"""画面（web/index.html・start.js、2026-11-05 一本化）の検査。API は呼ばない。

画面は1本で、3D の模型を持たないこと。固定の免責をそのまま出すこと。
絵は構内平面図だけで、部屋の色はサーバーの判定のまま塗ること。
画面3の答え（図面で確かめた印）で、今の判定の色が変わること。
紙（依頼メモ・理事会A4表裏・費用と補助）に、前の A4 の固定の文が言い換えずに入ること。
"""

import re
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import assistant, building, guard, samples, server

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
RISKY_PLACE = [{"key": "record", "label": "市の浸水の記録", "verdict": "risk"}]


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def block(text: str, start: str, end: str) -> str:
    head = text.index(start)
    return text[head: text.index(end, head)]


def payload(answers: dict, confirmed: list, rows=None, sample_id="a") -> dict:
    sample = samples.apply_answers(sample_id, answers, "千葉市 幸町2丁目")
    return building.building_payload(sample, confirmed, RISKY_PLACE if rows is None else rows, False, {}, [], [], [], False)


def verdicts(body: dict) -> dict:
    return {row["key"]: row["verdict"] for row in body["equipment"]}


def js_object(js: str, name: str) -> dict:
    """const NAME = { key: "..." } の key と値。"""
    body = block(js, f"const {name} = {{", "};")
    return dict(re.findall(r'(\w+): "([^"]*)"', body))


class OnePageTest(unittest.TestCase):
    def serve(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(WEB)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_root_and_old_entry_serve_the_same_page(self):
        base = self.serve()
        for path in ("/", "/index.html", "/start.html"):
            with urllib.request.urlopen(base + path) as response:
                self.assertIn('<script src="start.js"></script>', response.read().decode("utf-8"), path)

    def test_no_second_page_and_no_3d(self):
        # 「かんたん版」と「くわしい版」の二重をやめた。3D の模型（Three.js）は画面から外した。
        names = {path.name for path in WEB.iterdir() if path.is_file()}
        self.assertEqual(names, {"index.html", "start.js", "start.css", "sources.html", "sources.css", "materials.js", "materials.json"})
        for name in names - {"materials.json"}:
            text = read(name)
            for word in ("three@", "three/", "THREE.", "importmap", "model3d", "くわしい版", "かんたん版"):
                self.assertNotIn(word, text, f"{name}: {word}")

    def test_sources_are_one_small_link(self):
        html = read("index.html")
        self.assertIn('<a class="sources-link" href="/sources.html">根拠と資料</a>', html)
        page = read("sources.html")
        self.assertIn('id="materials-body"', page)
        self.assertIn("Materials.load();", page)

    def test_map_library_is_pinned(self):
        html = read("index.html")
        self.assertIn('leaflet@1.9.4/dist/leaflet.js"\n          integrity="sha256-', html)
        self.assertIn('leaflet@1.9.4/dist/leaflet.css"\n        integrity="sha256-', html)


class FixedTextTest(unittest.TestCase):
    def test_disclaimer_is_verbatim_and_not_folded(self):
        html = read("index.html")
        self.assertIn(guard.DISCLAIMER_1, html)
        footer = html[html.index('<footer class="fixed-note">'): html.index("</footer>")]
        self.assertNotIn("<details", footer)

    def test_every_sheet_prints_the_disclaimer(self):
        js = read("start.js")
        self.assertIn("disclaimer_1_no_engineer", js)
        self.assertGreaterEqual(js.count('class="print-fixed"'), 3)
        for name in ("function a4Front", "function a4Back"):
            self.assertIn("disclaimer()", block(js, name, "\n}\n"), name)
        printing = block(js, "function printSheet", "\n}\n")
        self.assertIn("${fixed}", printing)

    def test_sheet_lines_are_the_approved_words(self):
        # 前の A4 の裏の固定の文と、対象の範囲・区域の外の一行。言い換えない。
        js = read("start.js")
        source = (ROOT / "app" / "assistant.py").read_text(encoding="utf-8")
        for line in ("浸水実績は自治体の公表データを独自に集計・加工したもので、自治体の公式証明ではない", "本シートは予報ではなく、現時点の静的な整理である", "費用は桁の目安で、保安法人・工事業者の見積りに置き換えること"):
            self.assertIn(f'"{line}"', js)
            self.assertIn(line, source)
        self.assertIn("区域に入る都道府県の一覧は、まだ確かめていません。", js)
        self.assertIn("...SHEET_FIXED, ...SCOPE_LINES", js)

    def test_play_is_called_a_model_not_a_forecast(self):
        js = read("start.js")
        self.assertIn('"実際の浸水速度の予測ではなく、水が順番に入る仕組みの模式です。"', js)
        self.assertIn('stopped: "止まる想定"', js)
        # 時刻や速さの目安を書かない。
        # 段の名前（数日〜1週間、約2か月〜本復旧）は前の時間の再生と同じ、サーバーの五段の表の列の名前なので除く。
        strings = "".join(re.findall(r'"[^"\n]*"', re.sub(r'name: "[^"]*"', "", js)))
        self.assertEqual(re.findall(r"\d+\s*(分|時間|秒|日|か月)", strings), [])

    def test_sheet_address_is_town_level(self):
        js = read("start.js")
        self.assertIn("function townLabel(label)", js)
        # 住所をそのまま出すのは画面1の「選んだ場所」の1か所だけ。紙と画面2〜4は町丁まで。
        self.assertEqual(js.count("esc(S.place.site.label)"), 1)
        self.assertIn("townLabel(S.place.site.label)", block(js, "function where()", "\n}\n"))


class ChatTest(unittest.TestCase):
    """質問する（チャット）。2026-11-05 の一本化で一度外し、本人の決定で小さな入口として戻した。"""

    def test_fixed_text_sits_above_the_route_and_log(self):
        html = read("index.html")
        chat = block(html, '<aside class="chat" id="chat"', "</aside>")
        self.assertIn(f'<p class="chat-fixed">{guard.DISCLAIMER_1}。予報ではありません。</p>', chat)
        self.assertLess(chat.index('class="chat-fixed"'), chat.index('id="chat-route"'))
        self.assertLess(chat.index('id="chat-route"'), chat.index('id="chat-log"'))
        # 押したときだけ開く。
        self.assertIn('aria-label="質問する" hidden>', chat)

    def test_route_is_said_before_sending(self):
        # F-038：送る前に、Anthropic の API を通るかを出す。表示を替えるだけで API は呼ばない。
        js = read("start.js")
        self.assertIn("送った質問と、この画面の住所・答え・判定は Anthropic の API を通ります。図面と書類の中身は送りません。", js)
        self.assertIn("AI を通さず、説明カードで答えます", js)
        self.assertIn("renderChatRoute();", block(js, "function renderKey()", "\n}\n"))

    def test_every_answer_says_where_it_came_from(self):
        js = read("start.js")
        names = js_object(js, "SOURCE_NAMES")
        self.assertEqual(names["fixed"], "固定の文（AIを通していません）")
        self.assertEqual(names["fallback"], "説明カード（AIを通していません）")

    def test_screen_does_not_block_questions(self):
        # 原則4：遮断はサーバーの固定の文だけ。画面の側で質問を塞がない。
        js = read("start.js")
        submit = block(js, 'document.getElementById("chat-form").addEventListener("submit"', "\n});\n")
        self.assertIn('postJSON("/api/chat"', submit)
        self.assertNotRegex(submit, r"立入|入らない|危ない|includes\(")

    def test_context_is_town_level(self):
        js = read("start.js")
        context = block(js, "function chatContext()", "\n}\n")
        self.assertIn("site: townLabel(S.place.site.label)", context)
        self.assertNotIn("site: S.place.site.label", context)

    def test_actions_are_the_server_kinds(self):
        js = read("start.js")
        actions = block(js, "async function applyAction", "\n}\n")
        for kind in ("focus", "water", "measure", "statement"):
            self.assertIn(f'action.type === "{kind}"', actions)
        self.assertIn("statements: [...S.statements, ...obsStatements()],", js)


class ColorMeaningTest(unittest.TestCase):
    def test_unconfirmed_is_not_called_danger(self):
        js = read("start.js")
        self.assertIn("未確認（危険という意味ではありません）", js)
        self.assertIn('unconfirmed: { mark: "？", word: "未確認" }', js)

    def test_screen_reads_only_server_verdicts(self):
        # 色はサーバーの equipment の verdict だけから決める。画面で risk を作らない。
        js = read("start.js")
        self.assertIn("(S.building?.equipment || []).find((item) => item.key === key)", js)
        self.assertIsNone(re.search(r'(?<![=!\w])=\s*"risk"', js))
        self.assertNotIn('"risk" :', js)
        # 平面図の部屋の色も、判定の行の verdict のまま。
        self.assertIn("const v = rowKey && row(rowKey) ? row(rowKey).verdict : null;", js)

    def test_room_rows_match_the_server(self):
        js = read("start.js")
        rows = js_object(js, "KIND_ROWS")
        for kind, key in building._UPPER_ROWS.items():
            self.assertEqual(rows[kind], key, kind)
        for kind, key in building._ABSENT_ROWS.items():
            if kind in rows:
                self.assertEqual(rows[kind], key, kind)


class AnswerLoopTest(unittest.TestCase):
    """画面3の答えが送る語は、今の判定の決まりの語のまま。"""

    def test_tokens_match_the_judge(self):
        js = read("start.js")
        for kind in ("pump", "elec", "panel_room", "tr"):
            self.assertIn(kind, building._UPPER_ROWS)
        self.assertIn("pump", building._ABSENT_ROWS)
        self.assertIn("[`upper:${kind}`]", js)
        self.assertIn("[`absent:${kind}`]", js)

    def test_answers_alone_never_turn_red(self):
        body = payload({"rooms_floor": "basement", "basement": "yes"}, [])
        for key in ("water", "power", "tr"):
            self.assertNotEqual(verdicts(body)[key], "risk", key)

    def test_drawing_answers_change_colors(self):
        base = {"rooms_floor": "basement", "basement": "yes"}
        self.assertEqual(verdicts(payload(base, ["elec"]))["power"], "risk")
        self.assertEqual(verdicts(payload(base, ["upper:elec"]))["power"], "clear")
        self.assertEqual(verdicts(payload(base, ["upper:tr"]))["tr"], "clear")
        self.assertEqual(verdicts(payload(base, ["upper:pump"]))["water"], "clear")

    def test_red_needs_a_risky_place(self):
        body = payload({"rooms_floor": "basement", "basement": "yes"}, ["elec"], rows=[{"key": "record", "verdict": "unconfirmed"}])
        self.assertEqual(verdicts(body)["power"], "unconfirmed")

    def test_asks_shrink_when_answered(self):
        base = {"rooms_floor": "basement", "basement": "yes"}
        before = [step["key"] for step in payload(base, [])["top_line"]["steps"]]
        after = [step["key"] for step in payload(base, ["upper:pump", "upper:tr"])["top_line"]["steps"]]
        self.assertIn("water", before)
        self.assertNotIn("water", after)
        self.assertNotIn("tr", after)

    def test_samples_keep_their_own_answers(self):
        # 画面1で部屋の階を聞かない。見本は見本の答えのまま送り、自分の建物は画面3で分かった階だけ送る。
        js = read("start.js")
        answers = block(js, "function answers()", "\n}\n")
        self.assertIn("if (S.sampleId) return { ...S.extra };", answers)
        self.assertNotIn("data-rooms", js)

    def test_own_building_needs_the_floor_and_the_engineer(self):
        # 見本でない建物は、図面の階（地下）と主任技術者の名前が分かるまで②の色は変わらない。
        stuck = payload({"rooms_floor": "unknown"}, ["elec", "tr"], sample_id=None)
        self.assertEqual(verdicts(stuck)["power"], "unconfirmed")
        moved = payload({"rooms_floor": "basement", "basement": "yes", "hv": "yes", "tr": "yes"}, ["elec", "tr"], sample_id=None)
        self.assertEqual(verdicts(moved)["power"], "risk")
        self.assertEqual(verdicts(moved)["tr"], "risk")
        js = read("start.js")
        self.assertIn('data-hv="yes"', js)
        self.assertIn('S.extra.tr = choice === "absent" ? "no" : "yes";', js)
        self.assertIn('basement: "地下", ground: "1階"', js)

    def test_every_ask_has_plain_words(self):
        js = read("start.js")
        asks = js_object(js, "PLAIN_ASK")
        for key in building._STEP_WHAT:
            self.assertIn(key, asks)
        for word in ("盤", "受電", "借室", "主任技術者"):
            self.assertNotIn(word, "".join(asks.values()), word)


class PlanTest(unittest.TestCase):
    """絵は構内平面図だけ。見本の部屋の位置から描き、ピンは残りの確認だけに立てる。"""

    def test_every_sample_has_a_machine_floor(self):
        for sid, sample in samples.SAMPLES.items():
            view = samples.client_view(sample)
            machine = next(v for v in view["views"] if any(r["key"] in ("pump", "elec", "tr", "panel_room") for r in v["rooms"]))
            keys = {room["key"] for room in machine["rooms"]}
            self.assertIn("pump", keys, sid)
            self.assertIn("tr", keys, sid)
            self.assertTrue(keys & {"elec", "panel_room"}, sid)
            for room in machine["rooms"]:
                self.assertGreaterEqual(room["x"], 0)
                self.assertLessEqual(round(room["x"] + room["w"], 6), 1)
                self.assertLessEqual(round(room["y"] + room["h"], 6), 1)
            # 水の入り道の印（壁の穴か坂の下の扉）と、道路がある。
            marks = [m["kind"] for v in view["views"] for m in v.get("marks", [])]
            self.assertTrue({"conduit_hole", "door_low"} & set(marks), sid)
            self.assertIn("road", marks, sid)

    def test_plan_is_drawn_from_the_sample_rooms(self):
        js = read("start.js")
        self.assertIn("S.building.sample", block(js, "function plan(", "\n}\n"))
        self.assertIn("sample.views", js)
        # 前の簡易な3つの箱の絵は使わない。
        self.assertNotIn("function picture(", js)

    def test_pins_are_only_the_open_steps(self):
        js = read("start.js")
        self.assertIn("plan({ pins: pinsOf(steps()), small: true })", js)
        self.assertIn("plan({ pins: pinsOf(list) })", js)
        anchors = block(js, "function pinAnchors", "\n}\n")
        for key in ("water", "power", "tr", "entry", "ev", "park"):
            self.assertIn(f"anchors.{key}", anchors)

    def test_borrowed_shape_is_said(self):
        js = read("start.js")
        self.assertIn('"図は見本の形を借りた説明用です。あなたの建物の図面ではありません。"', js)
        self.assertGreaterEqual(js.count("b.sample.custom ? `<p class=\"hint\">${BORROWED}</p>`"), 3)

    def test_place_map_reads_the_server(self):
        # 地図は凹みを一番に見る（原則3）。高さと層は、サーバーの reading のまま。
        js = read("start.js")
        terrain = block(js, "function terrainLine", "\n}\n")
        self.assertIn("reading.basin", terrain)
        self.assertIn("周りより低い凹み", terrain)
        self.assertIn("reading.hazards", js)
        self.assertIn("reading.elevation?.points", js)


class HonestShapeTest(unittest.TestCase):
    """本人の指摘（2026-11-05）：「11階建て」「地下の電気室」はどこから？ 3〜5mは本当？"""

    def test_own_building_floors_are_not_borrowed(self):
        js = read("start.js")
        self.assertIn("（見本の形）", block(js, "function plan(", "\n}\n"))
        self.assertIn("BORROWED", block(js, "function screenTwo()", "\n}\n"))
    def test_own_building_answers_are_sent(self):
        js = read("start.js")
        own = block(js, "function ownQuestions()", "\n}\n")
        self.assertIn('id="own-floors"', own)
        self.assertIn("data-own", own)
        self.assertIn("分からない", own)
        sent = block(js, "function answers()", "\n}\n")
        self.assertIn("S.own.basement", sent)
        self.assertIn("floors: built", sent)
        # サーバーは、答えた階数と地下の有無を形に使う（地下なしなら地下のない見本の形）。
        no_basement = samples.apply_answers(None, {"basement": "no", "floors": 7}, "東京都")
        self.assertEqual(no_basement["floors"], 7)
        self.assertEqual(no_basement["archetype"], "ground")
        self.assertEqual(samples.client_view(no_basement)["answers"]["floors"], 7)


class NoDrawingTest(unittest.TestCase):
    """本人の指摘（2026-11-05）：図面がない人も使えるように。地図の矢印は数字と食い違わないように。"""

    def test_no_drawing_path_does_not_change_colors(self):
        js = read("start.js")
        three = block(js, "function screenThree()", "\n}\n")
        self.assertIn("${drawingQuestion()}", three)
        self.assertIn("hasDrawing() ? cards + readCard() : observeCards()", three)
        self.assertIn("管理会社に頼む紙を作る", three)
        # 見て答えたことは、確かめた印（confirmed）にせず、聞き取り（statements）として送る。
        observe = block(js, "async function setObservation(", "\n}\n")
        self.assertNotIn("S.choices", observe)
        self.assertIn("S.obs[key]", observe)
        self.assertIn("色は、図面で確かめるまで変えません", block(js, "function observeCards()", "\n}\n"))

    def test_observations_reach_the_memo_but_not_the_verdict(self):
        # サーバーは、聞き取りを依頼メモに「竣工図で確かめます（未確認）」として載せ、判定は変えない。
        base = payload({"rooms_floor": "unknown"}, [], sample_id=None)
        heard = building.building_payload(samples.apply_answers(None, {"rooms_floor": "unknown"}, "千葉市 幸町2丁目"), [], RISKY_PLACE, False, {}, [], ["住民が見たこと：地下へ降りるスロープか階段がある"], [], False)
        self.assertEqual(verdicts(base), verdicts(heard))
        items = [item for section in heard["memos"] for item in section["items"] if item["from"] == "聞き取り"]
        self.assertEqual(len(items), 1)
        self.assertIn("未確認", items[0]["text"])
        self.assertIn('item.from === "聞き取り"', read("start.js"))



class BuildingPinTest(unittest.TestCase):
    """建物の位置を地図で選ぶ（2026-11-05）。町丁の代表点ではなく、押した点の値で読み直す。"""

    def test_pin_reads_again_as_the_building_point(self):
        js = read("start.js")
        move = block(js, "async function movePin(lat, lng)", "\n}\n")
        self.assertIn('pin: "1"', move)
        self.assertIn("S.place.site.label", move)
        self.assertIn("if (S.busy || !S.place) return;", move)
        # 見本（架空の建物）は動かさない。
        self.assertIn("if (!S.sampleId) {\n    map.on(\"click\"", js)

    def test_server_rejects_a_pin_outside_japan(self):
        base = OnePageTest.serve(self)
        query = urllib.parse.urlencode({"address": "見本", "longitude": "123", "latitude": "-5", "pin": "1"})
        try:
            urllib.request.urlopen(f"{base}/api/location?{query}")
            self.fail("国外の点を受けた")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 422)

    def test_address_is_not_logged(self):
        source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        self.assertIn("share|search|reverse|location", source)

    def test_risky_headline_names_the_item(self):
        js = read("start.js")
        self.assertIn("${PLACE_SHORT[item.key] || item.label}：", block(js, "function placeHeadline()", "\n}\n"))


class InlandTest(unittest.TestCase):
    """内水の案内と、この辺りの浸水の経験（2026-11-05）。国の地図にない内水の手がかりを、判定を変えずに依頼メモへ。"""

    def test_inland_gap_points_to_the_city_maps(self):
        js = read("start.js")
        note = block(js, "function inlandNote()", "\n}\n")
        self.assertIn("item.key === \"inland\"", note)
        self.assertIn("${WAGAMACHI}", note)
        self.assertIn('const WAGAMACHI = "https://disaportal.gsi.go.jp/hazardmap/";', js)
        self.assertIn("${inlandNote()}", block(js, "function screenOne()", "\n}\n"))

    def test_experience_goes_to_the_city_not_the_drawing(self):
        js = read("start.js")
        line = block(js, "function experienceLine()", "\n}\n")
        self.assertIn("市区町村（下水道の担当）", line)
        self.assertNotIn("竣工図", line)
        # 経験は判定にも、確かめた印にも、サーバーの聞き取りにも入れない。
        self.assertNotIn("expStatements", js)
        self.assertIn("${S.sampleId ? \"\" : experienceQuestion()}", js)


class DurationTest(unittest.TestCase):
    """水が引くまでの時間（浸水継続時間、2026-11-05）。凡例画像の色をそのまま読み、完全に一致したときだけ区分を返す。"""

    class Image:
        def __init__(self, rgb):
            self.width = self.height = 256
            self.rgb = rgb

        def rgba(self, x, y):
            return (*self.rgb, 255) if (x, y) == (10, 10) else (0, 0, 0, 0)

    def test_legend_is_read_exactly(self):
        from app import location

        self.assertEqual(location.DURATION_LAYERS[0][2], "01_flood_l2_keizoku_data")
        self.assertEqual(location.DURATION_LEGEND[(250, 245, 0)], "1日〜3日未満")
        self.assertEqual(location.nearest_legend(self.Image((255, 153, 0)), 12, 10, legend=location.DURATION_LEGEND), "3日〜1週間未満")
        # 洪水の深さの凡例と取り違えない。
        self.assertIsNone(location.nearest_legend(self.Image((255, 153, 0)), 12, 10))
        self.assertIn("4週間以上", location.DURATION_NOTE)



class BuildingFactsTest(unittest.TestCase):
    """マンション名から階数と地下を探す（2026-11-05）。API は呼ばず、Claude の答えを差し替えて確かめる。"""

    def answer(self, data):
        import json
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "調べました。" + json.dumps(data, ensure_ascii=False)}]}

    def run_with(self, data, available=True):
        from unittest import mock
        from app import claude, search

        with mock.patch.object(claude, "available", return_value=available), mock.patch.object(claude, "create", return_value=self.answer(data)) as create:
            return search.building_facts("みどりハイツ", "千葉県千葉市美浜区"), create

    def test_only_matched_pages_with_a_source_are_used(self):
        good = {"building": "みどりハイツ", "floors_above": 11, "floors_below": 1, "source_url": "https://example.com/a", "source_title": "物件の案内", "quote": "地上11階地下1階", "matched": True}
        result, create = self.run_with(good)
        self.assertEqual(result["found"]["floors_above"], 11)
        self.assertEqual(result["found"]["floors_below"], 1)
        self.assertEqual(create.call_count, 1)
        for bad in ({**good, "matched": False}, {**good, "source_url": ""}, {**good, "floors_above": 300, "floors_below": None}):
            result, _ = self.run_with(bad)
            self.assertIsNone(result["found"], bad)

    def test_no_key_means_no_search_and_no_guess(self):
        result, create = self.run_with({}, available=False)
        self.assertIsNone(result["found"])
        self.assertEqual(create.call_count, 0)
        self.assertIn("API キー", result["message"])

    def test_screen_uses_the_value_only_when_pressed(self):
        js = read("start.js")
        self.assertIn('postJSON("/api/building-facts"', block(js, "async function findFacts()", "\n}\n"))
        use = block(js, "function useFacts()", "\n}\n")
        self.assertIn("S.own.floors = String(f.floors_above)", use)
        # 地下が書かれていなければ（null）、地下の答えは変えない。
        self.assertIn("f.floors_below !== null", use)
        box = block(js, "function factsBox()", "\n}\n")
        self.assertIn("Anthropic の API に送り", box)
        self.assertIn("出典", box)
        self.assertIn("townLabel(S.place?.site?.label", block(js, "async function findFacts()", "\n}\n"))


class SendTest(unittest.TestCase):
    """文で送る（2026-11-05）。リンクは手元のサーバーでしか開けないので、要点の文を共有の画面かコピーで渡す。"""

    def test_summary_carries_the_fixed_text_and_town_address(self):
        js = read("start.js")
        text = block(js, "function summaryText()", "\n}\n")
        self.assertIn("where()", text)
        self.assertIn("disclaimer()", text)
        self.assertIn("EVAC_LINE", text)
        self.assertIn("COST_FIXED", text)
        self.assertIn("見本の形を借りた説明です", text)
        self.assertNotIn("site.label", text)
        self.assertIn("experienceLine()", text)
    def test_nothing_is_sent_to_the_server(self):
        js = read("start.js")
        send = block(js, "async function sendSummary()", "\n}\n")
        self.assertIn("navigator.share", send)
        self.assertIn("copyText(text)", send)
        self.assertIn("S.sendText = text", send)
        copy = block(js, "async function copyText(text)", "\n}\n")
        self.assertIn("navigator.clipboard.writeText", copy)
        self.assertIn('document.execCommand("copy")', copy)
        for body in (send, copy):
            self.assertNotIn("fetch", body)
            self.assertNotIn("postJSON", body)


class WhyFirstTest(unittest.TestCase):
    """WHY / WHAT に戻した（2026-11-05 本人の指示）。絵は構内平面図と画面1の地図だけ。主役は足元の水（what-018）と対策（what-019）。"""

    def test_only_the_plan_and_the_map_are_drawn(self):
        js = read("start.js")
        for name in ("function depthPicture(", "function cutaway(", "function profilePicture(", "function depthCard("):
            self.assertNotIn(name, js)
        for text in ("1階を約3mとした目安", "深さの区切りは、国交省", "なぜこの深さ？"):
            self.assertNotIn(text, js)
        self.assertEqual(js.count("<svg class="), 1)  # 平面図だけ（地図は Leaflet）
        one = block(js, "function screenOne()", "\n}\n")
        self.assertIn("${EVAC_LINE}", one)
        self.assertIn("landLine()", one)

    def test_screen_two_leads_with_the_server_top_line(self):
        js = read("start.js")
        two = block(js, "function screenTwo()", "\n}\n")
        self.assertIn("${esc(b.top_line.lead)}", two)
        self.assertIn("plan({ level: S.play })", two)
        self.assertIn("${measureChips()}", two)
        self.assertEqual(two.count("plan("), 1)

    def test_water_positions_follow_the_server_scenario(self):
        js = read("start.js")
        self.assertIn("S.building?.scenarios?.[`${level}:${S.measure}`]", js)
        drawn = block(js, "function plan(", "\n}\n")
        self.assertIn("scenario(level)?.wet", drawn)
        body = payload({}, [])
        keys = {key for scenario in body["scenarios"].values() for key in scenario["wet"]}
        mapped = set(re.findall(r"(\w+): \[", block(js, "const WET_ROOMS = {", "};")))
        self.assertLessEqual(keys - {"drain", "park"}, mapped)

    def test_measures_and_fixed_lines_are_the_servers(self):
        js = read("start.js")
        chips = block(js, "function measureChips()", "\n}\n")
        self.assertIn("b.model_measures", chips)
        for key in ("b.fixed.hole", "b.fixed.raise", "b.fixed.tr_box"):
            self.assertIn(key, chips)
        body = payload({}, [])
        for measure in body["model_measures"]:
            for level in (1, 2, 3):
                self.assertIn(f"{level}:{measure['key']}", body["scenarios"])
        self.assertIn("壁の穴を塞いだのは、この図の入り道一つだけです", body["fixed"]["hole"])


class PlanFileTest(unittest.TestCase):
    """図面のファイル（2026-11-05）。何百MB・何GBの全部込みの竣工図は、ブラウザで読み込む前に止める。"""

    def test_size_matches_the_server(self):
        js = read("start.js")
        self.assertIn("const MAX_FILE_BYTES = 32 * 1024 * 1024;", js)
        # サーバーの上限は、32MB を base64 にした大きさ（4/3倍）を受けられる。
        self.assertGreaterEqual(server.MAX_BODY_BYTES, 32 * 1024 * 1024 * 4 // 3)

    def test_checked_before_reading(self):
        js = read("start.js")
        reading = block(js, "async function readPlan(file)", "\n}\n")
        self.assertLess(reading.index("fileProblem(file)"), reading.index("new FileReader()"))
        problem = block(js, "function fileProblem(file)", "\n}\n")
        self.assertIn("file.size > MAX_FILE_BYTES", problem)
        self.assertIn("機械のある階の平面図のページだけ", problem)
        self.assertIn("FILE_TYPES.test(file.type)", problem)


class ShrinkPhotoTest(unittest.TestCase):
    """図面の写真を送る前に縮める（2026-11-05）。API は呼ばない。"""

    def test_images_are_shrunk_and_pdf_is_sent_as_is(self):
        js = read("start.js")
        reading = block(js, "async function readPlan(file)", "\n}\n")
        self.assertIn('file.type.startsWith("image/") ? await shrinkImage(file) : null', reading)
        self.assertIn('body.media_type = shrunk ? "image/jpeg" : file.type;', reading)
        # 縮める前に、種類と大きさの確かめ（fileProblem）を通す。
        self.assertLess(reading.index("fileProblem(file)"), reading.index("shrinkImage(file)"))

    def test_shrink_keeps_text_readable_and_falls_back(self):
        js = read("start.js")
        self.assertIn("const SHRINK_EDGE = 2000;", js)
        self.assertIn("const SHRINK_QUALITIES = [0.85, 0.75, 0.65];", js)
        shrink = block(js, "async function shrinkImage(file)", "\n}\n")
        self.assertIn("Math.min(1, SHRINK_EDGE / Math.max(bitmap.width, bitmap.height))", shrink)
        self.assertIn('imageOrientation: "from-image"', shrink)
        self.assertIn('context.fillStyle = "#ffffff"', shrink)
        self.assertIn("return null;", shrink[shrink.index("catch"):])


class NameVariantTest(unittest.TestCase):
    """建物名の表記ゆれ（2026-11-05）。外の地図は呼ばず、比べ方と探し直しの回数を確かめる。"""

    def test_name_key_folds_common_variants(self):
        from app.search import _name_key

        for a, b in (("キャッスル", "キヤツスル"), ("ヴィラ", "ビラ"), ("グリ－ンコ－ト", "グリーンコート"), ("パーク・ハウス", "パークハウス"), ("ﾊﾟｰｸﾊｳｽ", "パークハウス"), ("ハイツ ", "ハイツ")):
            self.assertEqual(_name_key(a), _name_key(b), (a, b))
        self.assertNotEqual(_name_key("パークハウス"), _name_key("パークタワー"))

    def test_spaced_name_splits_at_script_changes(self):
        from app.search import spaced_name

        self.assertEqual(spaced_name("グリーンコート幸町ミッドタワー"), "グリーンコート 幸町 ミッドタワー")
        self.assertEqual(spaced_name("グリ－ンコ－ト幸町"), "グリーンコート 幸町")
        self.assertEqual(spaced_name("グリーンハイツ幸町第2"), "グリーンハイツ 幸町第2")

    def test_osm_is_retried_once_with_the_spaced_name(self):
        from unittest import mock
        from app import search

        calls = []
        places = []

        def fake_osm(query, place="", names=None):
            calls.append(query)
            places.append(place)
            return [] if len(calls) == 1 else [{"label": "見本", "longitude": 139.0, "latitude": 35.0, "source": "OpenStreetMap"}]

        with mock.patch.object(search, "_osm", side_effect=fake_osm), mock.patch.object(search.time, "sleep") as sleep, mock.patch.object(search, "_gsi", return_value=[]):
            result = search.search("グリーンコート幸町ミッドタワー")
        self.assertEqual(calls, ["グリーンコート幸町ミッドタワー", "グリーンコート 幸町 ミッドタワー"])
        sleep.assert_called_once_with(search.OSM_INTERVAL_SECONDS)
        # 探し直しの地名の手がかりは、区切った形から取る（名前の一部が混ざった「幸町ミッド」にしない）。
        self.assertEqual(places[1], "幸町")
        self.assertEqual(result["candidates"][0]["label"], "見本")

    def test_no_retry_when_the_name_is_already_spaced(self):
        from unittest import mock
        from app import claude, search

        calls = []
        with mock.patch.object(search, "_osm", side_effect=lambda q, place="", names=None: calls.append(q) or []), mock.patch.object(search.time, "sleep"), mock.patch.object(search, "_gsi", return_value=[]), mock.patch.object(search, "_place_candidates", return_value=[]), mock.patch.object(claude, "available", return_value=False):
            with self.assertRaises(Exception):
                search.search("グリーンコート 幸町 ミッドタワー")
        self.assertEqual(len(calls), 1)


class SheetTest(unittest.TestCase):
    def test_four_screens_one_button_each(self):
        js = read("start.js")
        for name in ("screenOne", "screenTwo", "screenThree", "screenFour"):
            body = block(js, f"function {name}()", "\n}\n")
            self.assertEqual(body.count('class="primary"'), 1, name)

    def test_four_has_the_three_papers(self):
        js = read("start.js")
        tabs = block(js, "const TABS = [", "];")
        for word in ("依頼メモ", "理事会A4", "費用・補助"):
            self.assertIn(word, tabs)

    def test_costs_and_subsidy_come_from_the_server(self):
        js = read("start.js")
        self.assertIn("S.building?.measures", js)
        self.assertIn("S.building?.subsidies?.[region]", js)
        short = js_object(js, "MEASURE_SHORT")
        for measure in samples.MEASURES:
            self.assertIn(measure["key"], short, measure["key"])
        # 費用の数字を画面に書かない（サーバーの range のまま出す）。
        self.assertIsNone(re.search(r"\d", "".join(short.values()).replace("1階", "")))
        # 補助の印は言い切らない。
        aid = js_object(js, "AID_WORDS")
        self.assertEqual(aid["no"], "対象外になりうる")
        self.assertEqual(aid["with_plate"], "止水板などと併せるときに限る")


if __name__ == "__main__":
    unittest.main()
