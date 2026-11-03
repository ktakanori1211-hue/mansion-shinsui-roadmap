"""残った小さな機能（共有の画面に A4 の新しい欄、F-045 凹みの模式を出さない切り替え、F-049 区域の外の一行）の検査。

ブラウザも API も使わない。JS と HTML を文字として読み、受け渡しの名前がそろっているかと、出してはいけない形がないかを見る。
"""

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def block(text: str, start: str, end: str) -> str:
    head = text.index(start)
    return text[head: text.index(end, head)]


SHARE_FIELDS = ("equipment_notes", "measure_tepco", "mark_note", "set_of_three", "after", "engineer", "scope")


class ShareDataTest(unittest.TestCase):
    def setUp(self):
        self.share = block(read("panels.js"), "function shareData()", "function applyPolish")

    def test_new_fields_are_put_in_share(self):
        for key in SHARE_FIELDS:
            self.assertIn(f"{key}:", self.share, key)
        # 処置の表の「担当」「補助」の列は A4 と同じ式。
        self.assertIn('owner: m.owner || "—"', self.share)
        self.assertIn("mark: SimPanel.markFor(m, region)[0]", self.share)
        self.assertIn("building.rain?.set_of_three", self.share)
        self.assertIn("after: AFTER_LINES", self.share)
        # 主任技術者の欄は描いた A4 から読み、出し分けの条件を二度書かない。
        self.assertIn('"#sheet-engineer > ul > li"', self.share)
        self.assertIn(".reuse-table tbody tr", self.share)

    def test_drawings_and_chat_are_not_shared(self):
        for word in ("PlanPanel", "plan", "chat", "Chat", "drawing"):
            self.assertNotIn(word, self.share, word)

    def test_mark_note_drops_pointer_to_missing_panel(self):
        line = re.search(r'mark_note: "([^"]+)"', self.share).group(1)
        self.assertNotIn("④", line)
        # A4 の補助の一行の前の二文と同じ文字列（承認済みの文を書き換えない）。
        self.assertIn(line, read("panels.js").replace(self.share, ""))


class ViewTest(unittest.TestCase):
    def setUp(self):
        self.view = read("view.html")

    def test_new_sections_are_drawn(self):
        for word in ("担当：", "補助：", "data.set_of_three", "水が引いたあと、管理組合がすること", "電気主任技術者の方へ", "engineer.reuse_rows", "data.scope", "data.equipment_notes", "止水材の使い分け"):
            self.assertIn(word, self.view, word)

    def test_old_links_without_new_fields_do_not_break(self):
        # 前に発行したリンクの中身には新しい欄が無い。forEach を undefined に呼ばない。
        for guard in ("data.after?.length", "(data.scope || [])", "(data.equipment_notes || [])", "(item.badges || [])", "if (data.set_of_three)", "if (data.mark_note)", "item.owner !== undefined"):
            self.assertIn(guard, self.view, guard)

    def test_no_inner_html_with_data(self):
        self.assertIsNone(re.search(r"innerHTML\s*=\s*[^\"' ]", self.view))
        self.assertNotIn("innerHTML: data", self.view)


class DemToggleTest(unittest.TestCase):
    def setUp(self):
        self.scenes = read("scenes.js")

    def test_toggle_defaults_to_showing_the_model(self):
        self.assertIn('input.type = "checkbox"', self.scenes)
        self.assertIn("input.checked = false;", self.scenes)
        self.assertIn('document.getElementById("map").before(label)', self.scenes)
        # scenes.js は app.js より前に読まれるので、element() を初期化の中で使わない。
        toggle = block(self.scenes, "const demToggle", "})();")
        self.assertNotIn("element(", toggle)

    def test_play_turns_off_dem_when_checked(self):
        play = block(self.scenes, "function play(scene, card)", "function legend")
        self.assertIn("useDem: scene.useDem && !demToggle.checked", play)
        self.assertIn("HazardMap.playScene(shown,", play)
        # 模式の文と凡例は outcome.hadDem で出し分ける（模式を出さないときは出ない）。
        self.assertIn("if (outcome.hadDem) lines.push(", self.scenes)
        self.assertIn('if (outcome.hadDem) item("swatch-dem"', self.scenes)
        # map.js は useDem が偽なら標高タイルを読まず、水色を塗らない。
        hazard = read("map.js")
        self.assertIn("if (useDem) {", hazard)
        self.assertIn("useDem: scene.useDem && pinElevation !== null", hazard)
        self.assertIn("hadDem: sim.useDem", hazard)

    def test_card_judgement_still_sees_hollows(self):
        # 原則3：カードの当てはまりは凹み（basin）を見たまま。切り替えは塗り方だけ。
        self.assertIn('return colored(reading, "inland") || reading.basin;', self.scenes)
        applies = block(self.scenes, "function applies", "function count")
        self.assertNotIn("demToggle", applies)


class OutsideAreaLineTest(unittest.TestCase):
    def test_line_is_added_after_scope_line_once(self):
        panels = read("panels.js")
        self.assertIn('document.querySelector("#sheet-basis .scope-line")', panels)
        self.assertIn('!document.querySelector("#sheet-basis .scope-outside")', panels)
        line = re.search(r'"(東京電力パワーグリッドの区域の外では[^"]+)"', panels).group(1)
        self.assertIn("借室の照会先", line)
        self.assertIn("区域に入る都道府県の一覧は、まだ確かめていません", line)
        # 都道府県の名前と数字は出さない。
        self.assertIsNone(re.search(r"\d", line))
        rest = line.replace("都道府県", "")
        self.assertIsNone(re.search(r"[都府県]", rest))
        self.assertNotIn("北海道", rest)
        self.assertIn('class="sheet-pointer scope-line"', read("index.html"))


if __name__ == "__main__":
    unittest.main()
