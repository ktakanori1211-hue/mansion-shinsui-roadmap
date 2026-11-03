"""A4 のおもてと裏を表裏1枚（2ページ）に収める分け方の検査。

ブラウザも API も使わない。HTML・JS・CSS を文字として読み、おもてと裏に出す項目と、
別紙・依頼メモの側へ移した項目の置き場所を確かめる。ページ数そのものは Chrome で印刷して測る
（このテストでは測らない）。
"""

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
PANELS = (WEB / "panels.js").read_text(encoding="utf-8")
STYLE = (WEB / "style.css").read_text(encoding="utf-8")
VIEW = (WEB / "view.html").read_text(encoding="utf-8")

DISCLAIMERS = [
    "本シートは公開データと入力情報から作成したもので、現地の判定や安全を保証するものではない。浸水中は電気室・借室（東京電力の変圧器の部屋）・ポンプ室・EVピットに立ち入らず、復電の可否は電気主任技術者が判断する",
    "浸水実績は自治体の公表データを独自に集計・加工したもので、自治体の公式証明ではない",
    "本シートは予報ではなく、現時点の静的な整理である",
    "費用は桁の目安で、保安法人・工事業者の見積りに置き換えること",
]


def article(sheet_id: str) -> str:
    """index.html の <article id="..."> から </article> まで。"""
    head = INDEX.index(f'id="{sheet_id}"')
    return INDEX[head: INDEX.index("</article>", head)]


def call(container_id: str) -> str:
    """panels.js の getElementById("...").replaceChildren( から、閉じかっこの行まで。"""
    head = PANELS.index(f'getElementById("{container_id}").replaceChildren(')
    line_end = PANELS.index("\n", head)
    if PANELS[line_end - 2: line_end] == ");":
        return PANELS[head:line_end]
    return PANELS[head: PANELS.index("\n    );", head)]


class SheetLayoutTest(unittest.TestCase):
    def test_front_keeps_the_five_sections(self):
        front = article("sheet-front")
        for box in ("sheet-top", "sheet-location", "sheet-equipment", "sheet-measures", "sheet-rain"):
            self.assertIn(f'id="{box}"', front, box)

    def test_back_keeps_after_flood_and_the_four_disclaimer_lines(self):
        back = article("sheet-back")
        for box in ("sheet-during", "sheet-days", "sheet-after"):
            self.assertIn(f'id="{box}"', back, box)
        disclaimer = back[back.index('class="disclaimer"'):]
        for line in DISCLAIMERS:
            self.assertIn(f"<li>{line}</li>", disclaimer)
        # 折りたたまずに出す。
        self.assertNotIn("<details", disclaimer)
        # 別紙が複製する免責は、裏の免責（最初の .disclaimer）のまま。
        self.assertLess(INDEX.index('id="sheet-back"'), INDEX.index('class="disclaimer"'))

    def test_engineer_section_moved_to_its_own_memo_page(self):
        self.assertNotIn('id="sheet-engineer"', article("sheet-back"))
        memo = article("sheet-engineer-memo")
        self.assertIn('id="sheet-engineer"', memo)
        self.assertIn("依頼メモ（電気主任技術者の方へ）", memo)
        self.assertIn("電気主任技術者の方へ", memo)
        # 裏には、移した先を一行で残す。
        self.assertIn("依頼メモ（電気主任技術者の方へ）", article("sheet-back"))
        # 依頼メモの後ろに置き、表裏の間に挟まない。
        self.assertLess(INDEX.index('id="sheet-memo"'), INDEX.index('id="sheet-engineer-memo"'))

    def test_detail_sheet_sits_after_the_back(self):
        detail = article("sheet-detail")
        for box in ("sheet-detail-notes", "sheet-detail-equipment", "sheet-detail-measures"):
            self.assertIn(f'id="{box}"', detail, box)
        self.assertLess(INDEX.index('id="sheet-back"'), INDEX.index('id="sheet-detail"'))
        self.assertLess(INDEX.index('id="sheet-detail"'), INDEX.index('id="sheet-basis"'))

    def test_new_sheets_are_shown_after_render(self):
        for sheet in ("sheet-detail", "sheet-memo", "sheet-engineer-memo"):
            self.assertIn(f'"{sheet}"', PANELS[PANELS.index("forEach((id) => {\n      document.getElementById(id).hidden = false;") - 80:])


class FrontAndDetailSplitTest(unittest.TestCase):
    def test_front_equipment_is_one_line_per_row(self):
        self.assertIn('["止まるもの", "判定", "誰が確かめるか"]', PANELS)
        self.assertEqual(call("sheet-equipment"), 'getElementById("sheet-equipment").replaceChildren(frontEquipment);')
        # 分かったことと、高さ・規模の一行は別紙へ。
        self.assertIn('["止まるもの", "判定", "分かったこと"]', PANELS)
        self.assertIn("equipmentBelow", call("sheet-detail-equipment"))
        self.assertIn("summaryCell(item)", PANELS[PANELS.index("const detailEquipment"):PANELS.index('getElementById("sheet-detail-equipment")')])

    def test_front_measures_have_four_columns_and_details_move(self):
        self.assertIn('slim(["いつ", "何をするか", "決め方・お金の出どころ", "桁"], measureRows(true))', PANELS)
        self.assertIn('slim(["いつ", "何をするか", "決め方・お金の出どころ", "桁", "担当", "補助"], measureRows(false))', PANELS)
        front = call("sheet-measures")
        detail = call("sheet-detail-measures")
        long_note = "総会から任されている、規約に定めがある、その年の予算に入っている"
        self.assertIn(long_note, detail)
        self.assertNotIn(long_note, front)
        self.assertIn("＊建物の規約と予算による（条件は別紙）。", front)
        self.assertIn("東京電力の変圧器の部屋が地下にあり", detail)
        self.assertIn("申請を勧めるものではありません", detail)
        # 止水材の使い分けの補足は別紙の表だけ。
        self.assertIn('front ? SHEET_LABELS[m.key] || m.label : withNote(', PANELS)

    def test_subsidy_pointer_names_the_current_fold(self):
        self.assertNotIn("④", PANELS)
        self.assertIn("条件は、画面の③の折りたたみ「費用の桁と補助・専門家への相談」にあります。", PANELS)
        self.assertIn("<summary>費用の桁と補助・専門家への相談</summary>", INDEX)

    def test_top_notes_go_to_detail_and_set_of_three_to_back(self):
        notes = PANELS[PANELS.index('const topNotes = document.getElementById("sheet-detail-notes")'):PANELS.index("const equipmentBelow")]
        self.assertIn("building.top_line.notes", notes)
        self.assertIn("top_line.a4_notes", notes)
        self.assertNotIn("set_of_three", call("sheet-measures"))
        self.assertIn("building.rain.set_of_three", call("sheet-during"))

    def test_fixed_lines_unchanged(self):
        self.assertIn("警戒レベル3：車を上へ。決議は要らず、住民が今日からできる対策です。", PANELS)
        self.assertIn("合図は自治体や気象庁が出す警戒レベルです。予報ではありません。", call("sheet-rain"))


class PrintStyleTest(unittest.TestCase):
    def test_no_font_below_seven_points(self):
        sizes = [float(v) for v in re.findall(r"font-size:\s*([\d.]+)pt", STYLE)]
        self.assertTrue(sizes)
        self.assertGreaterEqual(min(sizes), 7)

    def test_sheets_are_not_scaled_down_in_print(self):
        prints = re.findall(r"@media print\s*\{(.*?)\n\}", STYLE, re.S)
        for block in prints:
            for value in re.findall(r"zoom:\s*([\d.]+)", block):
                self.assertGreaterEqual(float(value), 1)
            self.assertNotRegex(block, r"transform:\s*scale")


class ShareViewTest(unittest.TestCase):
    def test_equipment_notes_read_from_detail_sheet(self):
        share = PANELS[PANELS.index("function shareData()"):PANELS.index("function applyPolish")]
        self.assertIn('texts("#sheet-detail-equipment > p")', share)
        self.assertNotIn("④", share)

    def test_view_follows_the_same_order(self):
        render = VIEW[VIEW.index("function render(data)"):]
        faces = ['"おもて（事前）"', '"裏（事後）"', '"別紙（おもての表のくわしい版と、条件と出典）"', '"依頼メモ"', '"そのほかの資料"']
        positions = [render.index(face) for face in faces]
        self.assertEqual(positions, sorted(positions))
        back, detail, memo = positions[1], positions[2], positions[3]
        self.assertTrue(back < render.index("if (data.set_of_three)") < detail)
        self.assertTrue(back < render.index("data.disclaimers.forEach") < detail)
        self.assertTrue(detail < render.index("item.owner !== undefined") < memo)
        self.assertTrue(detail < render.index("(data.equipment_notes || [])") < memo)
        self.assertTrue(memo < render.index('"電気主任技術者の方へ"'))


if __name__ == "__main__":
    unittest.main()
