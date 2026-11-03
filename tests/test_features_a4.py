"""A4 のおもて・裏・依頼メモ・3D の表・試算に足した表示（全部入りの版）の検査。

API は呼ばない。JS は文字として読み、表示に要る関数と文があるか、出してはいけない言い方がないかを確かめる。
サーバーのデータは building_payload を直接呼んで形を確かめる。
"""

import pathlib
import re
import unittest

from app import building, samples

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANELS = (ROOT / "web" / "panels.js").read_text(encoding="utf-8")
SIM = (ROOT / "web" / "sim.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
RISK_ROW = [{"key": "flood", "verdict": "risk", "label": "洪水", "value": "0.5m〜3m"}]


def payload(sample_id, answers=None, confirmed=None):
    sample = samples.apply_answers(sample_id, answers) if answers else samples.SAMPLES[sample_id]
    return building.building_payload(sample, confirmed or [], RISK_ROW)


class EngineerSectionTest(unittest.TestCase):
    def test_f001_reuse_table_has_no_verdicts_or_numbers(self):
        # 専門家の論点4：水没機器は使える／使えないを出さない。絶縁抵抗の数字を書かない。
        for word in ["応急可", "原則交換", "全数交換", "MΩ", "ブレーカーを入れてよい", "バイパス"]:
            self.assertNotIn(word, PANELS, word)
        self.assertIn("REUSE_ROWS", PANELS)
        self.assertIn("判断する人", PANELS)
        self.assertIn("国交省・経産省ガイドライン本体 P.16", PANELS)
        self.assertIn("宛先：電気工事の業者とメーカーの技術者へ", PANELS)
        self.assertIn("row.underground || sample.underground_feed", PANELS)

    def test_f002_restore_line_splits_subjects(self):
        self.assertIn("借室（東京電力の変圧器の部屋）は東京電力パワーグリッドが、マンション側の受電設備は主任技術者が確かめます", PANELS)
        self.assertIn("どれか一つでも確かめられていなければ、電気を戻しません", PANELS)

    def test_f003_f004_f005_lines(self):
        self.assertIn("検電は負荷側全体で行います（逆充電と直流側の部分は実務の見立て）", PANELS)
        self.assertIn("入室したら検電・放電・短絡接地を先に済ませ", PANELS)
        self.assertIn("日本電線工業会の資料。毛細管や結露で入る経路は実務の見立て", PANELS)
        self.assertIn("保安管理業務の契約によります", PANELS)
        self.assertIn("単線結線図と、東京電力パワーグリッドへの書面での確認", PANELS)
        # 今の地中引込の文は消さずに残す
        self.assertIn("一度の冠水でどの程度進むかは確かめていません。歩道ぎわの蓋は開けないでください。", PANELS)


class FrontSideTest(unittest.TestCase):
    def test_existing_approved_lines_kept(self):
        self.assertIn("警戒レベル3：車を上へ。決議は要らず、住民が今日からできる対策です。", PANELS)
        self.assertIn("低い土地か高潮の色がかかる地点なので（建物の位置では未確認）、", PANELS)
        self.assertIn("満潮の2時間前までに出します（仮の目安。満潮と重なると排水が遅れると考えられ、時刻は潮位表で確かめます）。", PANELS)
        for text in building.RAIN_THIRD.values():
            self.assertIn(text, PANELS)
        self.assertIn("本シートは予報ではなく、現時点の静的な整理である", INDEX)

    def test_f032_rain_reads_building(self):
        self.assertIn("building.rain?.third", PANELS)
        self.assertIn("building.rain?.extra", PANELS)
        self.assertIn("building.rain.set_of_three", PANELS)

    def test_f014_valve_only_in_tide_branch(self):
        self.assertIn("building.rain_tank_valve?.show", PANELS)
        line = next(l for l in PANELS.splitlines() if "警戒レベル4" in l)
        self.assertIn("${valve}", line)
        self.assertLess(line.index("${tide ?"), line.index("${valve}"))

    def test_f033_a4_notes_not_polished(self):
        line = next(l for l in PANELS.splitlines() if "top_line.a4_notes ||" in l and "forEach" in l)
        self.assertNotIn("polish", line)
        self.assertIn("...(building.top_line.a4_notes || [])", PANELS)

    def test_f025_f021_f022_f024_f026_f028_f029_f051_hooks(self):
        for hook in ["row.tags", "row.note", "chain.note", "scale_focus", "building.scale?.shown", "out_of_scope",
                     "building.heights", "memo_no", "item.no", "対照表", "m.owner", "SimPanel.markFor", "renewalRow", "m.note"]:
            self.assertIn(hook, PANELS, hook)
        self.assertIn('["いつ", "何をするか", "決め方・お金の出どころ", "桁", "担当", "補助"]', PANELS)
        self.assertIn("申請を勧めるものではありません", PANELS)


class BackSideAndScopeTest(unittest.TestCase):
    def test_f034_after_section(self):
        self.assertIn('id="sheet-after"', INDEX)
        self.assertIn("水が引いたあと、管理組合がすること", INDEX)
        self.assertIn("床上浸水、または地盤面より45cmを超える浸水", PANELS)
        # 45cm だけを単独で書かない
        self.assertEqual(PANELS.count("45cm"), PANELS.count("床上浸水、または地盤面より45cm"))

    def test_f035_scope_line_in_basis_and_hero(self):
        scope = "対象：東京電力パワーグリッドの区域の、高圧で電気を受けるマンション。"
        basis = INDEX[INDEX.index('id="sheet-basis"'):INDEX.index('id="sheet-memo"')]
        self.assertIn(scope, basis)
        hero = INDEX[INDEX.index('id="hero"'):INDEX.index('data-stage="1"')]
        self.assertIn(scope, hero)
        self.assertIn("<details", hero)


class SimTest(unittest.TestCase):
    def test_shared_mark_and_tier_order(self):
        self.assertIn("function byTier", SIM)
        self.assertIn("markFor, byTier", SIM)
        self.assertIn("byTier(building.measures).forEach", SIM)
        tiers = re.search(r'TIER_ORDER = \[([^\]]+)\]', SIM).group(1)
        for measure in samples.MEASURES:
            self.assertIn(f'"{measure["tier"]}"', tiers, measure["key"])

    def test_f036_future_tag_and_mock(self):
        self.assertIn("将来の形：手続きも含めて相談できる窓口（デモ画面：実際には送信していません。紹介料は取りません）", SIM)
        self.assertIn("この画面は将来の姿で、今は何も送っていません。", SIM)
        self.assertIn("send.disabled = true", SIM)
        # 今の折りたたみの文は残す
        self.assertIn("補足：将来の窓口", SIM)
        self.assertIn("手続きも含めて相談できる窓口は、将来の構想です。今は送信の機能を持たず、紹介料も取りません。", SIM)


class PayloadShapeTest(unittest.TestCase):
    """画面が読むサーバーのデータの形。"""

    def test_keys_the_sheet_reads(self):
        for sample_id in "abc":
            data = payload(sample_id)
            self.assertIsInstance(data["top_line"].get("a4_notes"), list)
            self.assertIn(data["rain"]["third"], PANELS)
            self.assertIsInstance(data["rain"]["extra"], list)
            self.assertTrue(data["rain"]["set_of_three"])
            self.assertIn("note", data["chain"])
            for section in data["memos"]:
                self.assertIsInstance(section["index"], dict)
                for item in section["items"]:
                    self.assertTrue(item["no"].startswith(section["label"]))
                    self.assertIsInstance(item["sources"], list)
            for row in data["equipment"]:
                if row.get("memo_section"):
                    self.assertIn("memo_no", row)
            hole = next(m for m in data["measures"] if m["key"] == "hole")
            self.assertTrue(hole["owner"])
            self.assertIn("非硬化", hole["note"])
            tags = [row.get("tags") for row in data["scenarios"]["3:plate"]["table"] if row.get("tags")]
            self.assertTrue(tags)

    def test_conditional_data(self):
        valve = payload("c", {"tank": "yes", "tank_valve": "yes"})["rain_tank_valve"]
        self.assertTrue(valve["show"])
        self.assertNotRegex(valve["text"], r"\d")
        self.assertFalse(payload("a")["rain_tank_valve"]["show"])
        scale = payload("a", {"scale": "mid"})
        self.assertTrue(scale["scale"]["shown"])
        self.assertTrue(any("この規模で重点" in (row.get("badges") or []) for row in scale["equipment"]))
        self.assertFalse(payload("a")["scale"]["shown"])
        heights = payload("a", {"heights": {"panel_bottom": {"cm": 30, "source": "drawing"}}})["heights"]
        self.assertEqual(heights[0]["text"], "入力値：床から 30cm（竣工図）")

    def test_renewal_tier_only_where_shown(self):
        keys = lambda d: [m["key"] for m in d["measures"] if m["tier"] == "更新と一緒"]
        self.assertIn("gen_move", keys(payload("c")))
        self.assertEqual(keys(payload("b")), [])


if __name__ == "__main__":
    unittest.main()
