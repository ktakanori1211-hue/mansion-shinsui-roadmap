"""サーバー側で足したノートの機能に、画面の受け口（質問の欄、図面のボタン、地図の札、書類の受け口）があるかを確かめる。

ブラウザも API も使わない。JS の中の文と、サーバーの決まり（key の名前）とが合っているかだけを見る。
"""

import re
import unittest
from pathlib import Path

from app import building

WEB = Path(__file__).resolve().parent.parent / "web"


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def block(text: str, start: str, end: str) -> str:
    head = text.index(start)
    return text[head: text.index(end, head)]


class KeepAnswersTest(unittest.TestCase):
    """質問を送り直しても、書類で入った答え（damp、sealed など）と選んだ形を消さない。"""

    def test_submit_keeps_documented_answers(self):
        app = read("app.js")
        submit = block(app, 'questions.addEventListener("submit"', "await App.rebuild()")
        self.assertIn("const documented = App.building.sample.answers || {};", submit)
        self.assertIn("App.answers = { ...documented, ...fresh };", submit)
        # 選ばれていない欄（undefined）で、書類の答えやサーバーの既定を上書きしない。
        self.assertIn("value !== undefined", submit)
        # 前の作り方（二つの key だけを残す）に戻っていない。
        self.assertNotIn("hv_documented: documented.hv_documented, feed: documented.feed", app)

    def test_documented_keys_are_linked_to_questions(self):
        app = read("app.js")
        questions = block(app, "const DOC_QUESTIONS = {", "const DOC_KEY_OF")
        for key in ("tank", "generator", "tank_valve", "damp", "sealed", "homes_feed"):
            self.assertIn(f"    {key}: {{", questions)
        self.assertIn('const DOC_KEY_OF = { hv_documented: "hv", homes_feed_documented: "homes_feed" };', app)


class QuestionFieldsTest(unittest.TestCase):
    def setUp(self):
        self.app = read("app.js")

    def test_new_questions_exist(self):
        for name in ("entrance_step", "tank", "generator", "scale"):
            self.assertIn(f'optional("{name}")', self.app)
        self.assertIn('["upper", "2階以上"]', self.app)

    def test_scale_choices_match_server_and_have_no_numbers(self):
        line = re.search(r"const SCALE_CHOICES = (\[.*\]);", self.app).group(1)
        for value, label in building.SCALE_LABELS.items():
            self.assertIn(f'["{value}", "{label}"]', line)
        self.assertIsNone(re.search(r"\d", line))
        self.assertIn("建物の規模（総戸数のおおよそ）", self.app)

    def test_height_fields_match_server(self):
        fields = block(self.app, "const HEIGHT_FIELDS = [", "];")
        for key, (label, _) in building.HEIGHT_FIELDS.items():
            self.assertIn(f'["{key}", "{label}"]', fields)
        sources = re.search(r"const HEIGHT_SOURCES = (\[.*\]);", self.app).group(1)
        for value, label in building.HEIGHT_SOURCES.items():
            self.assertIn(f'["{value}", "{label}"]', sources)

    def test_height_input_has_no_lower_bound_and_sends_numbers(self):
        field = block(self.app, "function heightField", "function collectHeights")
        self.assertIn('input.step = "any";', field)
        self.assertNotIn("input.min", field)
        collect = block(self.app, "function collectHeights", "function collect(root)")
        self.assertIn("const cm = Number(raw);", collect)
        # 浸かる・浸からないを画面で計算しない。
        self.assertNotIn("water", collect)

    def test_tower_sample_keeps_server_default(self):
        self.assertIn('answers.tank ?? (tower ? "yes" : undefined)', self.app)
        self.assertIn('answers.generator ?? (tower ? "yes" : undefined)', self.app)

    def test_existing_heading_is_unchanged(self):
        self.assertIn('element("h3", "外から見える3つ")', self.app)

    def test_questions_are_split_for_residents_and_experts(self):
        # 上の段は住民・理事長が外から見て答えられる項目。借室・受電設備・盤・高さは下の段（畳んで、分からないままでよい）。
        render = block(self.app, "  function render() {\n    const { sample } = App.building;", "questions.addEventListener")
        self.assertIn("grid.append(outside, second, vents)", render)
        self.assertIn("expertGrid.append(first, third, fourth, extra, heightBox)", render)
        self.assertIn("管理会社や技術者が図面・現地で確かめる項目です（分からないままでOK）", render)
        residents = block(render, "const outside", "const first")
        for word in ("階数", "築年", "スロープ", "「東電」「高圧」の蓋", "出入口"):
            self.assertIn(word, residents)
        for word in ("借室", "受電", "盤の足元", "cm"):
            self.assertNotIn(word, residents)


class ReportPdfTest(unittest.TestCase):
    """F-042：点検報告書・修繕履歴の PDF の文字を画面の中で取り出す。"""

    def test_pdf_text_keeps_lines_and_full_width_colon(self):
        app = read("app.js")
        body = block(app, "async function reportPdfText", "window.reportPdfText")
        self.assertIn("pdf.numPages", body)
        self.assertIn('.join("\\n")', body)
        # 全体に NFKC をかけると「受電設備：地下」などの規則が当たらなくなる。康熙部首だけ直す。
        self.assertNotIn('.normalize("NFKC"))', body.replace('char.normalize("NFKC"))', ""))
        self.assertIn("\\u2F00-\\u2FDF", body)
        self.assertNotIn("fetch(", body)

    def test_receiver_fills_the_paste_box(self):
        app = read("app.js")
        self.assertIn('pdfInput.accept = "application/pdf";', app)
        self.assertIn("draft = text;", app)


class AbsentButtonsTest(unittest.TestCase):
    """F-017・F-021：設備図が写しにあるときだけ「描かれていない」「2階以上」を出す。"""

    def setUp(self):
        self.plan = read("plan.js")

    def test_kind_rows_match_server(self):
        rows = re.search(r"const KIND_ROWS = (\{.*\});", self.plan).group(1)
        for kind, row in {**building._ABSENT_ROWS, **building._UPPER_ROWS, "tr": "tr"}.items():
            self.assertIn(f"{kind}: \"{row}\"", rows)
        upper = re.search(r"const UPPER_KINDS = (\[.*\]);", self.plan).group(1)
        self.assertEqual(sorted(re.findall(r'"(\w+)"', upper)), sorted(building._UPPER_ROWS))

    def test_buttons_need_a_declared_drawing(self):
        self.assertIn("DRAWINGS.filter(([key]) => copies.has(key))", self.plan)
        self.assertIn("App.setConfirmedKeys([`absent:${kind}`, `upper:${kind}`]", self.plan)

    def test_sales_layout_is_offered_and_not_a_drawing_for_absent(self):
        self.assertIn('["sales", "販売時の配置図"]', self.plan)
        self.assertNotIn("sales", block(self.plan, "const DRAWINGS = [", "];"))

    def test_existing_reading_text_is_unchanged(self):
        self.assertIn("読み取りのあとに人が「確かめた」を押すまで、判定では図面で確かめたことになりません。描かれていないことは「なし」にしません。", self.plan)

    def test_app_has_one_step_replace_and_reset(self):
        app = read("app.js")
        self.assertIn("async setConfirmedKeys(remove, add)", app)
        self.assertIn("PlanPanel.renderAbsent();", app)
        self.assertIn("PlanPanel.reset();", app)
        self.assertIn('id="plan-absent"', read("index.html"))


class LandformTagTest(unittest.TestCase):
    """F-011：地図の層の一覧の下に地形分類の札。取れないときの文はサーバーと同じ。"""

    def test_missing_text_matches_server(self):
        from app import judge

        js = read("map.js")
        for status, text in judge._LANDFORM_MISSING.items():
            self.assertIn(f'{status}: "{text}"', js)
        self.assertIn("地図のデータが取れていない（${LANDFORM_MISSING[item.status]}）", js)

    def test_tag_is_outside_the_radiogroup_and_fetches_nothing(self):
        html = read("index.html")
        self.assertIn('<div class="landform-tags" id="landform-tags" hidden></div>', html)
        group = re.search(r'<div class="layer-choices"[^>]*></div>', html).group(0)
        self.assertNotIn("landform", group)
        js = read("map.js")
        self.assertNotIn("fetch(", block(js, "function renderLandforms", "function pinNote"))


class Model3DHeightTest(unittest.TestCase):
    def test_source_words_match_server(self):
        js = read("model3d.js")
        self.assertIn('{ drawing: "竣工図", measured: "実測", hearing: "聞き取り" }', js)
        self.assertEqual(building.HEIGHT_SOURCES, {"drawing": "竣工図", "measured": "実測", "hearing": "聞き取り"})


if __name__ == "__main__":
    unittest.main()
