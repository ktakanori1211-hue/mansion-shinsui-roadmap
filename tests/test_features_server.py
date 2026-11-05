"""ノートの「実現したい機能」から足したサーバー側の決まりを確かめる。API もネットワークも使わない。"""

import json
import pathlib
import unittest

from app import assistant, building, guard, judge, samples
from app import state
from tests.test_judge import NO_RECORD, hazard, reading

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWLIST = json.loads((ROOT / "tests" / "facts_allowlist.json").read_text(encoding="utf-8"))

RISK_ROW = [{"key": "record", "verdict": "risk", "label": "記録", "confirm_by": None}]
OPEN_ROW = [{"key": "flood", "verdict": "unconfirmed", "label": "洪水", "confirm_by": "管理会社"}]
CLEAR_ROWS = [{"key": k, "verdict": "clear", "label": k, "confirm_by": None} for k in ("flood", "inland", "surge", "ground", "record")]


def row(rows, key):
    return next(item for item in rows if item["key"] == key)


def keys(rows):
    return [item["key"] for item in rows]


def memo_texts(payload, section=None):
    sections = payload["memos"] if section is None else [payload["memos"][section - 1]]
    return " ".join(item["text"] for s in sections for item in s["items"])


def custom(answers, label="東京都"):
    return samples.apply_answers(None, answers, label)


class NewTextRulesTest(unittest.TestCase):
    """足した固定の文に、禁止の語と、済の行にない数字が入っていないこと。"""

    def texts(self):
        # 既存の承認済みの文（FIXED、ACTIONS_*）は検査の外。足した文だけを見る。
        names = [n for n in dir(building) if n.isupper() and n not in ("FIXED", "WATER_LEVELS", "SERVICES") and not n.startswith("ACTIONS_")]
        values = []
        for name in names:
            value = getattr(building, name)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, dict):
                values.extend(v for v in value.values() if isinstance(v, str))
        values += [assistant.LONG_TERM_PLAN_NOTE, assistant.AGENDA_TEPCO_CALL, samples.HOLE_NOTE, judge.BAND_SHALLOW_NOTE, *judge.ELEVATION_SOURCE_MORE]
        values += [m["label"] for m in samples.MEASURES] + list(samples.MEASURE_OWNERS.values())
        return values

    def test_no_banned_words(self):
        for text in self.texts():
            self.assertIsNone(guard._BANNED.search(text), text)
            for word in ("世界初", "唯一", "東国分", "美浜", "HEXSTRATA", "MΩ", "ブレーカーを入れ", "入れてよい"):
                self.assertNotIn(word, text)

    def test_numbers_come_from_checked_facts(self):
        allowed = set()
        for item in ALLOWLIST:
            allowed.update(guard.numbers_with_units(item["value"]))
        allowed |= {"2か月", "8日", "11日", "4万円"}  # 既存の承認済みの文にある数字
        for text in self.texts():
            for number in guard.numbers_with_units(text):
                self.assertIn(number, allowed, text)

    def test_no_new_yen_amounts_in_new_measures(self):
        for key in ("pump_check", "backflow", "main_panel", "gen_move"):
            measure = next(m for m in samples.MEASURES if m["key"] == key)
            self.assertIsNone(measure["low"])
            self.assertEqual(measure["sample_yen"], 0)
            self.assertTrue(measure["range"].startswith("—"))
            for field in ("decision", "account", "tokyo", "chiba", "high"):
                self.assertIn(field, measure)


class MemoAdditionsTest(unittest.TestCase):
    def test_f004_site_survey_item_in_memo_two(self):
        payload = building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)
        self.assertIn("結露の跡", memo_texts(payload, 2))
        self.assertIn("判定には使いません", memo_texts(payload, 2))
        b = building.building_payload(samples.SAMPLES["b"], [], RISK_ROW)
        item = next(i for i in b["memos"][1]["items"] if "結露" in i["text"])
        self.assertNotIn("主任技術者", item["text"])

    def test_f027_free_survey_is_last_in_memo_two(self):
        payload = building.building_payload(samples.SAMPLES["c"], [], RISK_ROW)
        last = payload["memos"][1]["items"][-1]
        self.assertIn("無料の現地診断", last["text"])
        self.assertIn("補助として使います", last["text"])

    def test_f030_pump_check_measure_and_memo_three(self):
        payload = building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)
        self.assertIn("pump_check", keys(payload["measures"]))
        self.assertIn("排水ポンプ", memo_texts(payload, 3))

    def test_f023_water_supply_note_and_memo(self):
        payload = building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)
        self.assertIn(building.WATER_SUPPLY_NOTE, row(payload["equipment"], "water")["details"])
        self.assertIn("給水設備図", memo_texts(payload, 1))


class CableAndFeedTest(unittest.TestCase):
    def test_f005_no_engineer_underground_asks_tepco(self):
        sample = samples.apply_answers("b", {"feed": "underground"})
        text = memo_texts(building.building_payload(sample, [], RISK_ROW), 1)
        self.assertIn(building.MEMO_CABLE_NO_ENGINEER, text)
        self.assertNotIn("電気主任技術者に、高圧ケーブル", text)

    def test_f005_engineer_building_keeps_the_old_line(self):
        text = memo_texts(building.building_payload(samples.SAMPLES["a"], [], RISK_ROW), 1)
        self.assertIn("電気主任技術者に、高圧ケーブル", text)

    def test_f005_unknown_feed_adds_single_line_diagram_memo(self):
        sample = custom({"basement": "yes"})
        self.assertTrue(sample["feed_unknown"])
        self.assertIn(building.MEMO_FEED_FORM, memo_texts(building.building_payload(sample, [], RISK_ROW), 1))


class HazardBandTest(unittest.TestCase):
    def flood(self, legend):
        rows = judge.judge_location(reading({"flood_planned": hazard("flood_planned", "color", legend)}), state.BUILDING, None)
        return next(r for r in rows if r.key == "flood")

    def test_f006_bands_use_legend_edges(self):
        self.assertIn("深さの帯：深い", self.flood("3m〜5m").conclusion)
        self.assertIn("深さの帯：中くらい", self.flood("0.5m〜3m").conclusion)
        self.assertIn("深さの帯：浅い", self.flood("〜0.5m").conclusion)

    def test_f006_level_and_verdict_unchanged(self):
        deep = self.flood("3m〜5m")
        self.assertEqual(deep.accent["level"], "high")
        self.assertEqual(deep.accent["band"], "deep")
        self.assertEqual(self.flood("〜0.3m").accent["level"], "mid")
        self.assertEqual(deep.verdict, state.RISK)

    def test_f006_shallow_band_is_not_called_safe(self):
        self.assertIn(judge.BAND_SHALLOW_NOTE, self.flood("〜0.3m").details)


class GroundRowTest(unittest.TestCase):
    def ground(self, data):
        return next(r for r in judge.judge_location(data, state.BUILDING, NO_RECORD) if r.key == "ground")

    def test_f010_source_sentences_added_and_old_kept(self):
        details = self.ground(reading()).details
        self.assertIn(judge.ELEVATION_SOURCE, details)
        self.assertIn("この値は、上のデータを読み取って加工したものです。", details)
        self.assertTrue(any("lfc_index.html" in d for d in details))

    def test_f011_missing_landform_layer_is_said(self):
        data = reading()
        data["landforms"][1]["status"] = "fetch_failed"
        data["landforms"][0]["status"] = "no_tile"
        details = " ".join(self.ground(data).details)
        self.assertIn("地形分類（人工地形）：地図のデータが取れていない（接続できず）", details)
        self.assertIn("地形分類（自然地形）：地図のデータが取れていない（この地域のデータなし）", details)
        self.assertEqual(self.ground(data).verdict, state.UNCONFIRMED)


class NeighborRecordTest(unittest.TestCase):
    def record(self, rows, neighbors):
        return {**NO_RECORD, "rows": rows, "neighbors": neighbors}

    def test_f007_neighbor_with_record_is_risk(self):
        rows = judge.judge_location(reading(), state.BUILDING, self.record([], [{"town": "見本町1丁目", "rows": [("令和元年10月25日", "大雨", "道路冠水")]}]))
        item = next(r for r in rows if r.key == "record")
        self.assertEqual(item.verdict, state.RISK)
        self.assertIn("隣の町丁（見本町1丁目）", item.headline)

    def test_f007_missing_neighbor_goes_to_memo_and_blocks_clear(self):
        rows = judge.judge_location(reading(), state.BUILDING, self.record([], [{"town": "見本町3丁目", "rows": None}]))
        item = next(r for r in rows if r.key == "record")
        self.assertEqual(item.verdict, state.UNCONFIRMED)
        self.assertIn("見本町3丁目）：手元の表に未収録", " ".join(item.details))

    def test_f007_without_neighbors_keeps_old_sentence(self):
        from app import records

        record = records.find("千葉市 幸町2丁目")
        self.assertEqual(record["neighbors"], [])
        item = next(r for r in judge.judge_location(reading(), state.BUILDING, record) if r.key == "record")
        self.assertIn("隣の町丁の記録は、まだ照らし合わせていません。", item.details)


class HollowTest(unittest.TestCase):
    def test_f009_hollow_shows_drain_row_with_reason(self):
        ground = [{"key": "ground", "verdict": "unconfirmed", "label": "敷地の高低差", "confirm_by": "管理会社が履歴で", "accent": {"badges": ["くぼ地の目安"]}}]
        payload = building.building_payload(samples.SAMPLES["b"], [], ground)
        drain = row(payload["equipment"], "drain")
        self.assertIn(building.HOLLOW_REASON, drain["details"])
        self.assertIn(building.HOLLOW_REASON, memo_texts(payload, 1))
        self.assertNotIn("drain", keys(building.building_payload(samples.SAMPLES["b"], [], OPEN_ROW)["equipment"]))

    def test_f009_basin_flag_counts(self):
        self.assertIn("drain", keys(building.building_payload(samples.SAMPLES["b"], [], OPEN_ROW, basin=True)["equipment"]))


class AnswerRowsTest(unittest.TestCase):
    def test_f012_entrance_step(self):
        rows = building.judge_equipment(custom({"basement": "yes", "entrance_step": "no"}), [], True)
        self.assertIn("出入口・搬入口", row(rows, "outside")["headline"])
        self.assertIn(building.STREET_VIEW_NOTE, row(rows, "outside")["details"])

    def test_f013_tank_and_generator_from_answers(self):
        rows = building.judge_equipment(custom({"basement": "yes", "tank": "yes", "generator": "yes"}), [], True)
        self.assertEqual(row(rows, "tank")["verdict"], "unconfirmed")
        gen = row(rows, "gen")
        self.assertNotIn("地下にあるので", gen["headline"])
        self.assertNotIn("使えません", gen["headline"])
        self.assertNotIn("tank", keys(building.judge_equipment(custom({"basement": "yes", "tank": "no"}), [], True)))

    def test_f013_sample_c_rows_unchanged_and_switchable(self):
        rows = building.judge_equipment(samples.SAMPLES["c"], [], False)
        self.assertIn("地下にあるので、浸かれば使えません", row(rows, "gen")["headline"])
        edited = samples.apply_answers("c", {"tank": "no", "generator": "no"})
        self.assertNotIn("tank", keys(building.judge_equipment(edited, [], False)))

    def test_f013_report_reads_tank_and_generator(self):
        answers = assistant.read_report(samples.REPORTS["c"])["answers"]
        self.assertEqual(answers["tank"], "yes")
        self.assertEqual(answers["generator"], "yes")
        self.assertNotIn("tank_valve", answers)  # 「記載なし」は「なし」と読まない

    def test_f014_tank_valve_flag(self):
        payload = building.building_payload(samples.apply_answers("c", {"tank": "yes", "tank_valve": "yes"}), [], RISK_ROW)
        self.assertTrue(payload["rain_tank_valve"]["show"])
        self.assertNotIn("時間", payload["rain_tank_valve"]["text"])
        self.assertFalse(building.building_payload(samples.SAMPLES["c"], [], RISK_ROW)["rain_tank_valve"]["show"])

    def test_f016_upper_floor(self):
        sample = custom({"basement": "yes", "rooms_floor": "upper"})
        self.assertEqual(sample["id"], "b")
        rows = building.judge_equipment(sample, [], True)
        self.assertIn("2階以上", row(rows, "water")["headline"])
        self.assertIsNone(row(rows, "water")["floor"])
        self.assertEqual(row(rows, "water")["verdict"], "unconfirmed")
        self.assertFalse(building.rooms_in_basement(samples.apply_answers("a", {"rooms_floor": "upper"})))

    def test_f019_damp_from_report(self):
        self.assertEqual(assistant.read_report(samples.REPORTS["a"])["answers"]["damp"], "yes")
        self.assertEqual(assistant.read_report(samples.REPORTS["b"])["answers"]["damp"], "no")
        self.assertNotEqual(assistant.read_report("指摘事項：湿気・漏水なし")["answers"].get("damp"), "yes")
        rows = building.judge_equipment(custom({"basement": "yes", "rooms_floor": "basement", "damp": "yes"}), [], True)
        self.assertIn("床の湿気（点検で指摘済み）", row(rows, "damp")["label"])
        no_engineer = samples.apply_answers("b", {"damp": "yes"})
        damp = row(building.judge_equipment(no_engineer, [], True), "damp")
        self.assertIn("電気工事の業者が立ち会い", damp["confirm_by"])
        self.assertNotIn("主任技術者", damp["confirm_by"])
        self.assertNotIn("damp", keys(building.judge_equipment(samples.apply_answers("a", {"damp": "no"}), [], True)))

    def test_f020_lock_row(self):
        lock = row(building.judge_equipment(samples.SAMPLES["b"], [], True), "lock")
        self.assertEqual(lock["memo_section"], 3)
        self.assertEqual(lock["headline"], building.LOCK_HEADLINE)

    def test_f015_backflow_row_and_measure(self):
        payload = building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)
        self.assertIn("平時に動作を確かめたか", row(payload["equipment"], "backflow")["confirm_by"])
        measure = row(payload["measures"], "backflow")
        self.assertEqual(measure["tokyo"], "with_plate")
        self.assertNotIn("backflow", [k for k, _ in building.SERVICES])


class ClearPathTest(unittest.TestCase):
    def test_f017_absent_on_drawing_is_clear_without_memo(self):
        payload = building.building_payload(samples.SAMPLES["c"], ["absent:tank", "absent:gen"], RISK_ROW)
        tank = row(payload["equipment"], "tank")
        self.assertEqual(tank["verdict"], "clear")
        self.assertIsNone(tank["confirm_by"])
        self.assertEqual(tank["evidence"], "drawing")
        self.assertNotIn("雨水ますから地下の貯留タンク", str([i["sources"] for s in payload["memos"] for i in s["items"]]))

    def test_f017_upper_room_is_clear(self):
        rows = building.judge_equipment(samples.SAMPLES["a"], ["upper:pump", "upper:elec"], True)
        self.assertEqual(row(rows, "water")["verdict"], "clear")
        self.assertEqual(row(rows, "power")["verdict"], "clear")
        self.assertIn(building.CLEAR_NOT_ENTRY, row(rows, "water")["details"])

    def test_f017_absent_electric_room_does_not_clear_power(self):
        rows = building.judge_equipment(samples.SAMPLES["a"], ["absent:elec"], True)
        self.assertNotEqual(row(rows, "power")["verdict"], "clear")
        self.assertIn(building.ABSENT_POWER_NOTE, row(rows, "power")["details"])

    def test_f017_sealed_hole_only_clears_entry(self):
        sample = samples.apply_answers("c", {"sealed": "yes"})
        rows = building.judge_equipment(sample, [], True)
        self.assertEqual(row(rows, "entry")["verdict_label"], "問題なし（対策済）")
        self.assertNotEqual(row(rows, "power")["verdict"], "clear")
        damp = samples.apply_answers("c", {"sealed": "yes", "damp": "yes"})
        self.assertEqual(row(building.judge_equipment(damp, [], True), "entry")["verdict"], "unconfirmed")
        # 見本A は点検で湿気の指摘がある建物なので、止水施工済みの記載があっても未確認のまま。
        a = samples.apply_answers("a", {"sealed": "yes"})
        self.assertEqual(row(building.judge_equipment(a, [], True), "entry")["verdict"], "unconfirmed")

    def test_f017_report_word_for_sealed(self):
        result = assistant.read_report("修繕履歴：電気室 管路口 止水施工済（2018年）")
        self.assertEqual(result["answers"]["sealed"], "yes")
        self.assertIn("止水施工済", [f["word"] for f in result["findings"]])

    def test_f017_absent_transformer_room_keeps_tepco_check(self):
        tr = row(building.judge_equipment(samples.SAMPLES["a"], ["absent:tr"], True), "tr")
        self.assertEqual(tr["verdict"], "unconfirmed")
        self.assertIn("東京電力パワーグリッドに照会", tr["confirm_by"])

    def test_f018_top_line_says_how_it_was_checked(self):
        notes = building.top_line(samples.SAMPLES["a"], [], CLEAR_ROWS, [])["notes"]
        self.assertIn(building.TOP_NOTE_LOCATION_CLEAR, notes)
        equipment = [{"label": "水", "verdict": "clear", "evidence": "drawing"}, {"label": "穴", "verdict": "clear", "evidence": "document"}]
        notes = building.top_line(samples.SAMPLES["a"], equipment, OPEN_ROW, [])["notes"]
        self.assertIn("図面で確かめた設備：水／書類で確かめた設備：穴。", notes)


class BulkReceivingTest(unittest.TestCase):
    def bulk(self):
        sample = samples.apply_answers("a", {"tr": "no", "hv": "yes", "homes_feed": "mansion", "homes_feed_documented": True})
        return sample, ["absent:tr"]

    def test_f021_chain_goes_from_receiving_box_to_homes(self):
        sample, confirmed = self.bulk()
        chain = building.chain_nodes(sample, confirmed)
        self.assertIn(("hv", "homes"), chain["edges"])
        self.assertNotIn("tr", [n["key"] for n in chain["nodes"]])
        self.assertEqual(chain["note"], building.CHAIN_NOTE_BULK)

    def test_f021_needs_the_document(self):
        sample = samples.apply_answers("a", {"tr": "no", "hv": "yes", "homes_feed": "mansion"})
        self.assertFalse(building.is_bulk(sample, ["absent:tr"]))
        self.assertFalse(building.is_bulk(self.bulk()[0], []))

    def test_f021_homes_stop_with_receiving_box_and_count_never_drops(self):
        sample, confirmed = self.bulk()
        table = building.scenarios(sample, confirmed)
        for measure in [m["key"] for m in building.measures_for_model(sample)]:
            counts = [sum(1 for i in table[f"{w}:{measure}"]["services"] if i["state"] == "stopped") for w in (1, 2, 3)]
            self.assertEqual(counts, sorted(counts))
            self.assertEqual(len(table[f"3:{measure}"]["services"]), 4)
        self.assertIn("homes", table["3:plate"]["stopped"])
        self.assertNotIn("tr", table["3:plate"]["wet"])
        self.assertEqual(row(building.judge_equipment(sample, confirmed, True), "tr")["label"], building.BULK_LABEL)

    def test_f021_transformer_room_buildings_get_common_only_note(self):
        self.assertEqual(building.chain_nodes(samples.SAMPLES["a"])["note"], building.CHAIN_NOTE_TR)


class ScaleTest(unittest.TestCase):
    def test_f022_tags_existing_rows_and_adds_missing(self):
        payload = building.building_payload(samples.apply_answers("a", {"scale": "large"}), [], RISK_ROW)
        self.assertIn(building.SCALE_TAG, row(payload["equipment"], "entry")["badges"])
        self.assertIn("tank", keys(payload["equipment"]))
        self.assertTrue(payload["scale"]["shown"])
        self.assertIn("仮の目安", payload["scale"]["note"])

    def test_f022_no_numbers_and_no_engineer_wording(self):
        payload = building.building_payload(samples.apply_answers("b", {"scale": "large"}), [], RISK_ROW)
        text = json.dumps(payload["scale"], ensure_ascii=False)
        self.assertEqual(guard.numbers_in(text), [])
        self.assertNotIn("主任技術者は技術面", text)
        self.assertFalse(any("主任技術者" in (i["confirm_by"] or "") for i in payload["equipment"]))

    def test_f022_unknown_goes_to_memo_and_clear_location_hides(self):
        payload = building.building_payload(samples.apply_answers("a", {"scale": "unknown"}), [], RISK_ROW)
        self.assertIn(building.MEMO_SCALE_UNKNOWN, memo_texts(payload, 1))
        clear = building.building_payload(samples.apply_answers("a", {"scale": "small"}), [], CLEAR_ROWS)
        self.assertFalse(clear["scale"]["shown"])

    def test_f022_scale_is_not_inferred_from_units(self):
        self.assertIsNone(building.building_payload(samples.SAMPLES["c"], [], RISK_ROW)["scale"]["value"])


class HeightTest(unittest.TestCase):
    def test_f024_input_value_is_shown_as_given(self):
        sample = samples.apply_answers("a", {"heights": {"panel_bottom": {"cm": 30, "source": "drawing"}, "elec_floor": {"cm": -20, "source": "管理員の聞き取り"}}})
        payload = building.building_payload(sample, [], RISK_ROW)
        water = row(payload["equipment"], "water")
        self.assertIn("入力値：床から 30cm（竣工図）", water["headline"])
        self.assertIn("入力値：床から 30cm（竣工図）", water["summary"])
        self.assertIn("電気の部屋の床：入力値：外の地面との差 -20cm（管理員の聞き取り）", row(payload["equipment"], "power")["details"])
        self.assertEqual(water["verdict"], "unconfirmed")
        self.assertEqual(payload["heights"][0]["cm"], 30)

    def test_f024_measured_values_replace_the_measure_memo(self):
        sample = samples.apply_answers("a", {"heights": {"panel_bottom": {"cm": 30, "source": "measured"}, "pump_floor": {"cm": 0, "source": "measured"}}})
        self.assertEqual(row(building.judge_equipment(sample, [], True), "water")["confirm_by"], building.WATER_MEASURED_CONFIRM)

    def test_f024_bad_values_are_ignored(self):
        sample = samples.apply_answers("a", {"heights": {"panel_bottom": {"cm": "30"}, "pump_floor": {"cm": True}}})
        self.assertEqual(building.heights(sample), {})

    def test_f025_tags_on_timeline_rows(self):
        table = building.scenario(samples.SAMPLES["a"], 3, "plate", [])["table"]
        self.assertEqual(row(table, "water")["tags"], ["位置は図面で未確認", "高さは未確認"])
        sample = samples.apply_answers("a", {"heights": {"panel_bottom": {"cm": 30, "source": "drawing"}}})
        table = building.scenario(sample, 3, "plate", ["pump"])["table"]
        self.assertEqual(row(table, "water")["tags"], [])
        self.assertIn("note", row(table, "tr"))


class MemoNumberTest(unittest.TestCase):
    def test_f026_numbers_and_merge(self):
        payload = building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)
        numbers = [i["no"] for s in payload["memos"] for i in s["items"]]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertEqual(payload["memos"][0]["items"][0]["no"], "①-1")
        sections = building._number_memos([{"label": "①", "items": [{"from": "x", "text": "同じ"}, {"from": "y", "text": "同じ"}]}], [])
        self.assertEqual(sections[0]["items"][0]["sources"], ["x", "y"])
        self.assertEqual(len(sections[0]["items"]), 1)

    def test_f026_rows_know_their_memo_number(self):
        payload = building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)
        lock = row(payload["equipment"], "lock")
        self.assertEqual(payload["memos"][2]["index"][lock["label"]], lock["memo_no"])


class MeasureOwnerTest(unittest.TestCase):
    def test_f028_owner_column(self):
        a = building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)["measures"]
        self.assertEqual(row(a, "plate")["owner"], "理事会→管理会社")
        b = building.building_payload(samples.SAMPLES["b"], [], RISK_ROW)["measures"]
        self.assertNotIn("主任技術者", row(b, "hole")["owner"])

    def test_f029_generator_move_only_with_generator(self):
        self.assertIn("gen_move", keys(building.building_payload(samples.SAMPLES["c"], [], RISK_ROW)["measures"]))
        self.assertNotIn("gen_move", keys(building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)["measures"]))

    def test_f031_main_panel_only_without_engineer(self):
        self.assertIn("main_panel", keys(building.building_payload(samples.SAMPLES["b"], [], RISK_ROW)["measures"]))
        self.assertNotIn("main_panel", keys(building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)["measures"]))

    def test_f051_hole_note_and_label_unchanged(self):
        hole = next(m for m in samples.MEASURES if m["key"] == "hole")
        self.assertIn("非硬化", hole["note"])
        self.assertTrue(hole["label"].startswith("ケーブルを通す壁の穴をふさぐ"))


class RainTest(unittest.TestCase):
    def test_f032_third_line_is_the_a4_text(self):
        # 大雨の一行は、サーバーの文（RAIN_THIRD）のまま理事会A4の表に出す。画面に文を写さない。
        js = (ROOT / "web" / "start.js").read_text(encoding="utf-8")
        self.assertIn("rain?.third", js)
        for text in building.RAIN_THIRD.values():
            self.assertNotIn(text, js)

    def test_f032_lines_by_building(self):
        a = building.rain_lines(samples.SAMPLES["a"])
        self.assertIn(building.RAIN_TR_CALL, a["extra"])
        self.assertIn(building.RAIN_DRAIN_BAN, a["extra"])
        bulk = samples.apply_answers("a", {"tr": "no", "hv": "yes", "homes_feed": "mansion", "homes_feed_documented": True})
        self.assertNotIn(building.RAIN_TR_SCOPE, building.rain_lines(bulk, ["absent:tr"])["extra"])
        b = building.rain_lines(samples.SAMPLES["b"])
        self.assertNotIn("主任技術者", "".join(b["extra"]) + b["set_of_three"])
        self.assertNotIn("主遮断器", "".join(b["extra"]))

    def test_f032_timeline_keeps_actions_before(self):
        cell = building.scenario(samples.SAMPLES["a"], 1, "hole")["table"][-1]["cells"][0]
        self.assertTrue(cell.startswith(building.ACTIONS_BEFORE))
        self.assertIn(building.RAIN_THIRD["engineer"], cell)

    def test_f032_agenda_has_tepco_call(self):
        sample = samples.SAMPLES["a"]
        payload = building.building_payload(sample, [], RISK_ROW)
        self.assertIn(assistant.AGENDA_TEPCO_CALL, assistant.exits(sample, "千葉市", payload)["board"])


class TopNotesTest(unittest.TestCase):
    def test_f033_guide_days_and_a4_only_chiba(self):
        top = building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)["top_line"]
        self.assertIn(building.TOP_NOTE_GUIDE_DAYS, top["notes"])
        self.assertNotIn("千葉", "".join(top["notes"]))
        self.assertIn(building.A4_NOTE_CHIBA, top["a4_notes"])
        self.assertNotIn("かかった", building.A4_NOTE_CHIBA)

    def test_f037_long_term_plan(self):
        sample = samples.SAMPLES["c"]
        exits = assistant.exits(sample, "東京都", building.building_payload(sample, [], RISK_ROW))
        self.assertIn("長期修繕計画に入れるもの（更新と一緒の段）", exits["board"])
        self.assertIn(assistant.LONG_TERM_PLAN_NOTE, exits["board_fixed"])
        self.assertNotIn(assistant.LONG_TERM_PLAN_NOTE, exits["procedure_fixed"])
        self.assertNotIn("義務", assistant.LONG_TERM_PLAN_NOTE)


class ReportWordsTest(unittest.TestCase):
    def test_f042_repair_words_with_negation_guard(self):
        words = [f["word"] for f in assistant.read_report("修繕履歴：2019年 給水ポンプ制御盤を更新。地下 排水ポンプ 交換。")["findings"]]
        self.assertIn("制御盤の更新", words)
        self.assertIn("排水ポンプ", words)
        words = [f["word"] for f in assistant.read_report(samples.REPORTS["a"])["findings"]]
        self.assertNotIn("止水", words)  # 「止水処理：点検項目になく、記載なし」は記載ありと読まない

    def test_fiction_mark_is_not_read_as_overhead_feed(self):
        for key in ("a", "c"):
            result = assistant.read_report(samples.REPORTS[key])
            self.assertNotIn("架空", [f["word"] for f in result["findings"]], key)
            self.assertEqual(result["answers"]["feed"], "underground")
        self.assertIn("架空", [f["word"] for f in assistant.read_report(samples.REPORTS["b"])["findings"]])


if __name__ == "__main__":
    unittest.main()
