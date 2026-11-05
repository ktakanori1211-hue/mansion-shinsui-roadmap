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


class StoryTest(unittest.TestCase):
    """画面2の3段（2026-11-05）：断面の切り絵・暮らしが止まるまで・平面図。住民に何がまずいかを伝える。"""

    def test_three_parts_in_order(self):
        js = read("start.js")
        two = block(js, "function screenTwo()", "\n}\n")
        parts = ["どう浸水するか", "暮らしが止まるまで", "どこを確かめるか"]
        self.assertEqual([two.index(p) for p in parts], sorted(two.index(p) for p in parts))
        self.assertIn("cutaway(S.play)", two)
        self.assertIn("timeline()", two)

    def test_cutaway_reads_the_server(self):
        # 止まるかはサーバーの scenario、部屋の色は判定のまま。切り絵で新しい判定を作らない。
        js = read("start.js")
        cut = block(js, "function cutaway(", "\n}\n")
        self.assertIn('serviceState(level, "homes")', cut)
        self.assertIn('serviceState(level, "ev") === "stopped"', cut)
        self.assertIn("row(rowKey) ? row(rowKey).verdict", cut)
        self.assertNotIn('"risk"', cut)

    def test_timeline_facts_come_from_the_server_table(self):
        js = read("start.js")
        facts = block(js, "function phaseFacts(", "\n}\n")
        self.assertIn('S.building?.scenarios?.["3:plate"]?.table', facts)
        line = block(js, "function timeline()", "\n}\n")
        # 「この建物の日数ではありません」の一行（サーバーの notes）を出す。
        self.assertIn("notes[0]", line)
        self.assertIn('<details class="phase-more">', line)
        # 段の名前と文に、日数などの新しい数字を書かない（数字はサーバーの表の文だけ）。
        phases = re.sub(r'name: "[^"]*"', "", block(js, "const PHASES = [", "];"))
        self.assertIsNone(re.search(r"\d+\s*(日|週|か月|年)", phases))

    def test_server_table_has_the_example_and_note(self):
        body = payload({}, [])
        scenario = body["scenarios"]["3:plate"]
        self.assertTrue(scenario["notes"])
        others = next(item for item in scenario["table"] if item["key"] == "others")
        self.assertIn("ほかの建物の例", others["cells"][3])
        self.assertEqual(len(others["cells"]), 5)


class DepthOnBuildingTest(unittest.TestCase):
    """浸水の深さを建物の階に置き換える（2026-11-05）。深さは立地の行の値のまま、階は「1階を約3m」とした目安。"""

    def test_depth_comes_from_the_place_rows(self):
        js = read("start.js")
        deepest = block(js, "function deepestHazard()", "\n}\n")
        self.assertIn("S.place?.location?.rows", deepest)
        self.assertIn("parseBand(item.value)", deepest)
        self.assertIn("${depthCard()}", block(js, "function screenOne()", "\n}\n"))
        self.assertIn("deepestHazard()", block(js, "function cutaway(", "\n}\n"))

    def test_floors_are_said_to_be_an_assumption(self):
        js = read("start.js")
        self.assertIn('const STORY_NOTE = "1階を約3mとした目安です。実際の階の高さは建物で違います。";', js)
        self.assertIn("lines.push(STORY_NOTE);", block(js, "function depthConditions(band)", "\n}\n"))
        # 国の手引きの区分の言い方（床上浸水など）は、原文を確かめるまで使わない。
        for word in ("床上浸水", "床下浸水", "2階浸水"):
            self.assertNotIn(word, js)

    def test_card_states_its_conditions(self):
        # 本人の指摘（2026-11-05）：どの雨の想定か・どこの値か・帯のどちらの端か・1階の床の高さを札に添える。
        js = read("start.js")
        conds = block(js, "function depthConditions(band)", "\n}\n")
        # どの想定かは、札の一行目（leadWords）と、想定を並べる表で言う。
        self.assertIn("SCENARIO_WORDS[layer.key]", block(js, "function leadWords(band)", "\n}\n"))
        self.assertIn("${scenarioTable()}", block(js, "function depthCard()", "\n}\n"))
        self.assertIn("町丁の代表点の値で、建物の位置の値ではありません", conds)
        self.assertIn("の深い方（${band.high}m）で描いています", conds)
        self.assertIn("1階の床が地面より高い建物では、その分浅くなります", conds)
        self.assertIn("STORY_NOTE", conds)
        self.assertIn("depthConditions(band)", block(js, "function depthCard()", "\n}\n"))
        # 地図と札は同じ層を使う。
        self.assertIn("hazardLayer(deepestHazard())", block(js, "function drawMap()", "\n}\n"))

    def test_no_color_is_not_called_safe(self):
        js = read("start.js")
        self.assertIn("浸水しないという意味ではありません", block(js, "function depthCard()", "\n}\n"))

    def test_bands_the_server_returns_are_parsed(self):
        # サーバーの深さの帯の書き方（〜0.5m、0.5m〜3m、3m〜5m、20m〜）を読めるか、正規表現を同じ形で確かめる。
        js = read("start.js")
        pattern = re.search(r"String\(value \|\| \"\"\)\.match\(/(.+)/\);", js).group(1)
        for text, low, high in (("〜0.5m", None, "0.5"), ("0.5m〜3m", "0.5", "3"), ("3m〜5m", "3", "5"), ("20m〜", "20", None)):
            m = re.match(pattern, text)
            self.assertIsNotNone(m, text)
            self.assertEqual((m.group(1), m.group(2)), (low, high), text)
        self.assertIsNone(re.match(pattern, "データなし"))


class HonestShapeTest(unittest.TestCase):
    """本人の指摘（2026-11-05）：「11階建て」「地下の電気室」はどこから？ 3〜5mは本当？"""

    def test_scenarios_are_listed_side_by_side(self):
        # 一番深い想定だけを見せず、同じ場所のほかの想定（計画規模など）を並べる。値はサーバーの reading.hazards のまま。
        js = read("start.js")
        rows = block(js, "function scenarioRows()", "\n}\n")
        self.assertIn("S.place?.location?.reading?.hazards", rows)
        self.assertIn('"この点に色なし"', rows)
        words = js_object(js, "SCENARIO_WORDS")
        self.assertEqual(words["flood_max"], "想定しうる最大の大雨")
        self.assertEqual(words["flood_planned"], "川の整備の目標の大雨")
        # 想定の言葉に、確率や年数の数字を書かない。
        self.assertIsNone(re.search(r"\d", "".join(words.values())))

    def test_own_building_floors_are_not_borrowed(self):
        js = read("start.js")
        cut = block(js, "function cutaway(", "\n}\n")
        self.assertIn("sample.custom ? Number(sample.answers?.floors) || 0 : sample.floors", cut)
        self.assertIn('"階数は未確認"', cut)
        self.assertIn("見本の形を借りた絵", cut)
        self.assertIn("（見本の形）", block(js, "function plan(", "\n}\n"))

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

    def test_map_arrows_only_from_higher_points(self):
        js = read("start.js")
        draw = block(js, "function drawMap()", "\n}\n")
        self.assertIn("(reading.high_directions || []).includes(p.label)", draw)
        self.assertNotIn("reading.basin)", draw)
        legend = block(js, "function mapLegend()", "\n}\n")
        self.assertIn("海面からの高さ", legend)
        self.assertIn("reading.hazard_legend", legend)


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

    def test_server_marks_the_pin_as_the_building(self):
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
        self.assertIn("${inlandNote()}", block(js, "function depthCard()", "\n}\n"))

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

    def test_screen_shows_the_server_value_only(self):
        js = read("start.js")
        line = block(js, "function durationLine()", "\n}\n")
        self.assertIn("reading.durations", line)
        self.assertIn("reading.duration_note", line)
        self.assertIsNone(re.search(r"\d+\s*(時間|日|週)", "".join(re.findall(r'"[^"\n]*"', line))))


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
