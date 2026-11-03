"""画面の側で足した機能（F-038〜F-043 のうち ui の行）が、JS と HTML に入っているかを確かめる。

ブラウザも API も使わない。ファイルの中の文と関数の有無だけを見る。
"""

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class ChatRouteTest(unittest.TestCase):
    """F-038：送る前に、Anthropic の API を通るかを出す。"""

    def test_route_line_sits_under_fixed_text(self):
        html = read("index.html")
        fixed = html.index('class="chat-fixed"')
        route = html.index('id="chat-route"')
        self.assertLess(fixed, route)
        self.assertLess(route, html.index('id="chat-log"'))

    def test_fixed_text_is_unchanged(self):
        self.assertIn(
            "本シートは公開データと入力情報から作成したもので、現地の判定や安全を保証するものではない。浸水中は電気室・借室（東京電力の変圧器の部屋）・ポンプ室・EVピットに立ち入らず、復電の可否は電気主任技術者が判断する。予報ではありません。",
            read("index.html"),
        )

    def test_both_texts_switch_on_status(self):
        app = read("app.js")
        self.assertIn("送った質問と、この画面の住所・答え・判定は Anthropic の API を通ります。図面と書類の中身は送りません。", app)
        self.assertIn("AI を通さず、説明カードで答えます", app)
        body = app[app.index("function renderClaudeStatus"):]
        self.assertIn("renderChatRoute(status)", body[: body.index("}")])


class PlanDirectionTest(unittest.TestCase):
    """F-039：平面図の下に direction_line を一行で出す。"""

    def test_plan_shows_direction_line_with_caveat(self):
        plan = read("plan.js")
        self.assertIn("function renderDirection", plan)
        self.assertIn("direction_line", plan)
        self.assertIn("向きは答えと地図の目安で、測ったものではありません", plan)
        self.assertIn('shownKind !== "plan"', plan)
        self.assertIn('id="plan-direction"', read("index.html"))

    def test_refresh_redraws_direction(self):
        self.assertIn("PlanPanel.renderDirection()", read("app.js"))


class RaisedPanelTest(unittest.TestCase):
    """F-040：盤を付け替えたときの札と、元の位置の破線の箱。"""

    def test_labels(self):
        model = read("model3d.js")
        self.assertIn("ポンプのスイッチ盤（付け替え後）\\n付け替える高さは見積りと現地調査で決める", model)
        self.assertIn('"付け替える前の盤"', model)
        self.assertIn("ghostPanel", model)
        self.assertIn("edges(ghostPanel, 0x4f6d8f, true)", model)

    def test_height_input_is_shown_as_entered_without_threshold(self):
        model = read("model3d.js")
        self.assertIn("function panelHeightNote", model)
        self.assertIn("入力値：床から", model)
        # 高さから浸かる・浸からないを決める比べ方を持たない。
        body = model[model.index("function panelHeightNote"):]
        body = body[: body.index("\n}\n")]
        self.assertNotRegex(body, r"[<>]=?\s*\d")

    def test_raised_label_survives_focus_change(self):
        model = read("model3d.js")
        self.assertIn("function refreshDetails", model)
        self.assertIn("raisedNow", model)
        self.assertNotIn("item.object.visible = item.detailOf === key;", model)


class RoomTagTest(unittest.TestCase):
    """F-041：主な部屋の破線の箱と、札の1行目（三分類＋確かめる人）。"""

    def test_main_rooms_dashed_until_confirmed(self):
        model = read("model3d.js")
        self.assertIn('const MAIN_ROOMS = ["elec", "tr", "pump", "panel_room", "tank", "gen"]', model)
        self.assertIn("main && !sample.confirmedRooms.includes(room.key)", model)

    def test_absent_rooms_are_hidden_not_removed(self):
        model = read("model3d.js")
        self.assertIn("absent:${key}", model)
        self.assertIn("mesh.visible = false", model)

    def test_tag_reads_server_verdict_and_shared_who_labels(self):
        model = read("model3d.js")
        self.assertIn('const ROOM_ROWS = { elec: "power", panel_room: "power", pump: "water", tr: "tr", tank: "tank", gen: "gen" }', model)
        self.assertIn("window.App?.building?.equipment", model)
        self.assertIn("window.WHO_LABELS", model)
        self.assertIn("window.WHO_LABELS = WHO_LABELS", read("plan.js"))
        self.assertIn("updateTags()", model)
        self.assertIn("window.Model3D?.updateTags?.()", read("app.js"))

    def test_no_new_numbers_in_new_labels(self):
        model = read("model3d.js")
        for name in ("RAISED_PANEL_NOTE", "BEFORE_RAISE_NAME"):
            line = next(row for row in model.splitlines() if row.startswith(f"const {name}"))
            self.assertIsNone(re.search(r"\d", line.split("=", 1)[1]), line)


class ReportLinkTest(unittest.TestCase):
    """F-043：書類の語と項目の結びつきを外す操作と、書類で埋まった質問の扱い。"""

    def test_toggle_and_restore(self):
        app = read("app.js")
        self.assertIn("この結びつきは違う", app)
        self.assertIn("function applyDoc", app)
        self.assertIn("function linkFindings", app)
        self.assertIn("doc.before", app)
        self.assertIn('!rejected.has("rooms_floor")', app)

    def test_filled_questions_greyed_and_moved_down(self):
        app = read("app.js")
        self.assertIn("書類で読みました（", app)
        self.assertIn("input.disabled = true", app)
        self.assertIn("書類で読んだ項目", app)
        for key in ("tr", "hv", "rooms_floor", "panel_foot", "feed"):
            self.assertRegex(app, rf"\n    {key}: {{ name:")

    def test_toggle_does_not_read_again(self):
        app = read("app.js")
        body = app[app.index("async function applyDoc"):]
        body = body[: body.index("\n  }\n")]
        self.assertNotIn("/api/report", body)


if __name__ == "__main__":
    unittest.main()
