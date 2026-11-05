"""画面（web/index.html・start.js、2026-11-05 一本化）の検査。API は呼ばない。

画面は1本で、3D の模型を持たないこと。固定の免責をそのまま出すこと。
絵は構内平面図だけで、部屋の色はサーバーの判定のまま塗ること。
画面3の答え（図面で確かめた印）で、今の判定の色が変わること。
紙（依頼メモ・理事会A4表裏・費用と補助）に、前の A4 の固定の文が言い換えずに入ること。
"""

import re
import threading
import unittest
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
        strings = "".join(re.findall(r'"[^"\n]*"', js))
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
        self.assertIn("statements: S.statements,", js)


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
