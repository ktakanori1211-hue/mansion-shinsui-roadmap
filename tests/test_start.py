"""かんたん版（web/start.html・start.js、2026-11-05）の検査。API は呼ばない。

最初の画面がかんたん版になること、固定の免責をそのまま出すこと、
画面3の答え（図面で確かめた印）で、今の判定の色が変わることを確かめる。
"""

import re
import threading
import unittest
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import building, guard, samples, server

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
RISKY_PLACE = [{"key": "record", "label": "市の浸水の記録", "verdict": "risk"}]


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def payload(answers: dict, confirmed: list, rows=None, sample_id="a") -> dict:
    sample = samples.apply_answers(sample_id, answers, "千葉市 幸町2丁目")
    return building.building_payload(sample, confirmed, RISKY_PLACE if rows is None else rows, False, {}, [], [], [], False)


def verdicts(body: dict) -> dict:
    return {row["key"]: row["verdict"] for row in body["equipment"]}


class RootPageTest(unittest.TestCase):
    def test_root_serves_the_easy_page(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(WEB)))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            port = httpd.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
                html = response.read().decode("utf-8")
            self.assertIn('<script src="start.js"></script>', html)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html") as response:
                self.assertIn("かんたん版に戻る", response.read().decode("utf-8"))
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_full_page_links_back(self):
        self.assertIn('href="/"', read("index.html"))
        self.assertIn('href="/index.html"', read("start.html"))


class FixedTextTest(unittest.TestCase):
    def test_disclaimer_is_verbatim_and_not_folded(self):
        html = read("start.html")
        self.assertIn(guard.DISCLAIMER_1, html)
        footer = html[html.index('<footer class="fixed-note">'): html.index("</footer>")]
        self.assertNotIn("<details", footer)

    def test_disclaimer_is_printed(self):
        js = read("start.js")
        self.assertIn("print-fixed", js)
        self.assertIn("disclaimer_1_no_engineer", js)


class ColorMeaningTest(unittest.TestCase):
    def test_unconfirmed_is_not_called_danger(self):
        js = read("start.js")
        self.assertIn("未確認（危険という意味ではありません）", js)
        self.assertIn('unconfirmed: { mark: "？", word: "未確認" }', js)

    def test_screen_reads_only_server_verdicts(self):
        # 色はサーバーの equipment の verdict だけから決める。画面で risk を作らない。
        js = read("start.js")
        self.assertIn('(S.building?.equipment || []).find((item) => item.key === key)', js)
        # 赤は、サーバーが risk と返したものから選ぶだけ。画面の中で risk を代入しない。
        self.assertIsNone(re.search(r'(?<![=!\w])=\s*"risk"', js))


class AnswerLoopTest(unittest.TestCase):
    """画面3の答えが送る語は、今の判定の決まりの語のまま。"""

    def test_tokens_match_the_judge(self):
        js = read("start.js")
        for kind in ("pump", "elec", "panel_room", "tr"):
            self.assertIn(kind, building._UPPER_ROWS)
        for kind in ("pump",):
            self.assertIn(kind, building._ABSENT_ROWS)
        self.assertIn("`upper:${kind}`", js)
        self.assertIn("`absent:${kind}`", js)

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
        # 場所のリスクが確定していなければ、図面で地下と確かめても赤にしない。
        body = payload({"rooms_floor": "basement", "basement": "yes"}, ["elec"], rows=[{"key": "record", "verdict": "unconfirmed"}])
        self.assertEqual(verdicts(body)["power"], "unconfirmed")

    def test_asks_shrink_when_answered(self):
        base = {"rooms_floor": "basement", "basement": "yes"}
        before = [step["key"] for step in payload(base, [])["top_line"]["steps"]]
        after = [step["key"] for step in payload(base, ["upper:pump", "upper:tr"])["top_line"]["steps"]]
        self.assertIn("water", before)
        self.assertNotIn("water", after)
        self.assertNotIn("tr", after)

    def test_own_building_needs_the_engineer_answer(self):
        # 見本でない建物は、主任技術者がいるかが分かるまで②の色は変わらない。画面3で「名前がある」を聞く。
        base = {"rooms_floor": "basement", "basement": "yes"}
        stuck = payload(base, ["elec", "tr"], sample_id=None)
        self.assertEqual(verdicts(stuck)["power"], "unconfirmed")
        moved = payload({**base, "hv": "yes", "tr": "yes"}, ["elec", "tr"], sample_id=None)
        self.assertEqual(verdicts(moved)["power"], "risk")
        self.assertEqual(verdicts(moved)["tr"], "risk")
        js = read("start.js")
        self.assertIn('data-hv="yes"', js)
        self.assertIn('S.extra.tr = choice === "absent" ? "no" : "yes";', js)

    def test_every_ask_has_plain_words(self):
        js = read("start.js")
        for key in building._STEP_WHAT:
            self.assertRegex(js, rf"\n  {key}: \"", key)


class OneScreenTest(unittest.TestCase):
    def test_four_screens_one_button_each(self):
        js = read("start.js")
        for name in ("screenOne", "screenTwo", "screenThree", "screenFour"):
            body = js[js.index(f"function {name}()"):]
            body = body[: body.index("\n}\n")]
            self.assertEqual(body.count('class="primary"'), 1, name)

    def test_picture_text_does_not_overlap_tiles(self):
        # 暮らしの札と機械の札は同じ幅で、隣とすき間を空ける。
        js = read("start.js")
        xs = [int(v) for v in re.search(r"const xs = \[(\d+), (\d+), (\d+)\]", js).groups()]
        self.assertIn('width="98"', js)
        self.assertGreater(min(b - a for a, b in zip(xs, xs[1:])), 98)


if __name__ == "__main__":
    unittest.main()
