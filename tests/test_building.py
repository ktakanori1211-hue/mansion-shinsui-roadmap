"""設備の判定、水の位置の想定、囲い、検索の決まりを確かめる。ネットワークには出ない。"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import assistant, building, claude, guard, samples, search, share
from app.location import AddressError

RISK_ROW = [{"verdict": "risk", "label": "記録", "confirm_by": None}]
OPEN_ROW = [{"verdict": "unconfirmed", "label": "洪水", "confirm_by": "管理会社"}]


def row(rows, key):
    return next(item for item in rows if item["key"] == key)


class EquipmentTest(unittest.TestCase):
    def test_transformer_room_needs_a_person_to_confirm_the_drawing(self):
        sample = samples.SAMPLES["a"]
        before = building.judge_equipment(sample, [], True)
        after = building.judge_equipment(sample, ["tr"], True)
        self.assertEqual(row(before, "tr")["verdict"], "unconfirmed")
        self.assertEqual(row(after, "tr")["verdict"], "risk")

    def test_transformer_room_stays_open_without_location_risk(self):
        rows = building.judge_equipment(samples.SAMPLES["c"], ["tr"], False)
        self.assertEqual(row(rows, "tr")["verdict"], "unconfirmed")

    def test_ground_floor_transformer_room_stays_open(self):
        rows = building.judge_equipment(samples.SAMPLES["b"], ["tr"], True)
        self.assertEqual(row(rows, "tr")["verdict"], "unconfirmed")

    def test_no_chief_engineer_is_never_named_as_the_confirmer(self):
        rows = building.judge_equipment(samples.SAMPLES["b"], [], True)
        self.assertFalse(any("主任技術者" in (item["confirm_by"] or "") for item in rows))

    def test_tank_and_generator_only_on_the_tower(self):
        tower = [item["key"] for item in building.judge_equipment(samples.SAMPLES["c"], [], False)]
        small = [item["key"] for item in building.judge_equipment(samples.SAMPLES["b"], [], False)]
        self.assertIn("tank", tower)
        self.assertIn("gen", tower)
        self.assertNotIn("tank", small)
        self.assertNotIn("park", small)


class ReceivingBoxTest(unittest.TestCase):
    def verdict(self, **kwargs):
        args = {"confirmed": [], "location_risk": True, "document_read": False}
        args.update(kwargs)
        return row(building.judge_equipment(samples.SAMPLES["a"], args["confirmed"], args["location_risk"], args["document_read"]), "power")

    def test_hearing_alone_stays_open(self):
        self.assertEqual(self.verdict()["verdict"], "unconfirmed")

    def test_document_with_location_risk_is_risk(self):
        item = self.verdict(document_read=True)
        self.assertEqual(item["verdict"], "risk")
        self.assertIn("高さは未確認", item["confirm_by"])
        self.assertEqual(item["evidence"], "document")

    def test_drawing_with_location_risk_is_risk(self):
        self.assertEqual(self.verdict(confirmed=["elec"])["verdict"], "risk")

    def test_document_without_location_risk_stays_open(self):
        self.assertEqual(self.verdict(document_read=True, location_risk=False)["verdict"], "unconfirmed")

    def test_report_reader_finds_basement_box(self):
        self.assertTrue(assistant.read_report(samples.REPORTS["a"])["basement_power"])
        self.assertTrue(assistant.read_report(samples.REPORTS["c"])["basement_power"])
        self.assertFalse(assistant.read_report(samples.REPORTS["b"])["basement_power"])


class FixedTextTest(unittest.TestCase):
    def test_no_engineer_note_keeps_the_body(self):
        body = building.FIXED["disclaimer_1"]
        self.assertTrue(building.FIXED["disclaimer_1_no_engineer"].startswith(body))
        self.assertIn("電気主任技術者を選任していない建物では", building.FIXED["disclaimer_1_no_engineer"])
        self.assertIn("管理組合が判断し、東京電力パワーグリッドに連絡する", building.FIXED["disclaimer_1_no_engineer"])
        self.assertIn("管理組合が判断し、東京電力パワーグリッドに連絡する", guard.disclaimer(False))
        self.assertEqual(guard.disclaimer(False), building.FIXED["disclaimer_1_no_engineer"])
        self.assertEqual(guard.disclaimer(True), body)

    def test_guard_uses_the_note_without_engineer(self):
        self.assertIn("選任していない", guard.fixed_answer("電気室に入っていい？", False)["text"])
        self.assertNotIn("選任していない", guard.fixed_answer("電気室に入っていい？", True)["text"])
        self.assertIn("選任していない", guard.fixed_answer("人が倒れている", False)["text"])

    def test_water_line_says_wait_after_water_recedes(self):
        self.assertIn("入ってよいと指示するまで、住民、理事、管理員は入りません", building.FIXED["water_not_entry"])
        self.assertNotIn("東京電力パワーグリッドや電気工事業者", building.FIXED["water_not_entry"])

    def test_day_action_forbids_entering_to_operate(self):
        self.assertIn("扉を開けて中に入って操作しません", building.ACTIONS_DAY)


class AnswersTest(unittest.TestCase):
    def rows(self, answers, sample_id=None):
        sample = samples.apply_answers(sample_id, answers, "東京都")
        return sample, building.judge_equipment(sample, [], True, True)

    def test_custom_building_borrows_a_near_shape(self):
        self.assertEqual(self.rows({"floors": 30})[0]["id"], "c")
        self.assertEqual(self.rows({"basement": "no"})[0]["id"], "b")
        self.assertEqual(self.rows({"basement": "yes"})[0]["subsidy"], "tokyo")

    def test_transformer_room_no_is_not_trusted_without_drawing(self):
        _, rows = self.rows({"tr": "no", "hv": "yes", "basement": "yes"})
        self.assertEqual(row(rows, "tr")["verdict"], "unconfirmed")
        self.assertIn("図面で確かめるまで", row(rows, "tr")["headline"])

    def test_unknown_receiving_box_is_not_risk(self):
        _, rows = self.rows({"hv": "unknown", "basement": "yes"})
        self.assertEqual(row(rows, "power")["verdict"], "unconfirmed")

    def test_answer_alone_does_not_remove_the_engineer(self):
        sample, rows = self.rows({"tr": "yes", "hv": "no"})
        self.assertTrue(sample["engineer_unsure"])
        self.assertEqual(row(rows, "power")["verdict"], "unconfirmed")
        day, morning = building.actions_for(sample)
        self.assertIn("いれば主任技術者", day)
        self.assertIn("主任技術者（いない建物では電気工事の業者）", morning)
        self.assertIn("選任していない", guard.fixed_answer("電気室に入っていい？", True, True)["text"])

    def test_document_removes_the_engineer(self):
        sample, rows = self.rows({"tr": "yes", "hv": "no", "hv_documented": True})
        self.assertFalse(sample["has_chief_engineer"])
        self.assertFalse(any("主任技術者" in (item["confirm_by"] or "") for item in rows))

    def test_report_needs_both_statements(self):
        self.assertEqual(assistant.read_report("受電設備なし")["answers"], {})
        self.assertTrue(assistant.read_report(samples.REPORTS["b"])["answers"]["hv_documented"])

    def test_fictional_word_is_not_read_as_overhead_feed(self):
        self.assertEqual(assistant.read_report(samples.REPORTS["a"])["answers"]["feed"], "underground")
        self.assertEqual(assistant.read_report(samples.REPORTS["b"])["answers"]["feed"], "overhead")

    def test_unknown_rooms_do_not_say_basement(self):
        sample, rows = self.rows({"basement": "unknown"})
        lead = building.top_line(sample, rows, [{"verdict": "risk"}], [])["lead"]
        self.assertEqual(lead, "まだ分からない。")
        text = str([item["headline"] for item in rows])
        self.assertNotIn("地下の電気の部屋", text)
        self.assertNotIn("damp", [item["key"] for item in rows])

    def test_tall_custom_building_gets_no_tank_row_without_answer(self):
        _, rows = self.rows({"floors": 40})
        keys = [item["key"] for item in rows]
        self.assertNotIn("tank", keys)
        self.assertNotIn("gen", keys)

    def test_edited_sample_keeps_its_own_area(self):
        sample = samples.apply_answers("a", {"basement": "no", "rooms_floor": "ground"}, "千葉市 幸町2丁目")
        self.assertEqual(sample["subsidy"], "chiba")
        self.assertEqual(sample["name"], "うみかぜコート（架空）")

    def test_transformer_room_unseen_is_not_painted(self):
        sample, _ = self.rows({"tr": "no", "basement": "yes", "rooms_floor": "basement"})
        scenario = building.scenario(sample, 3, "plate")
        self.assertNotIn("tr", scenario["stopped"])
        self.assertTrue(any("位置は未確認" in line for line in scenario["notes"]))

    def test_2020_building_is_not_called_before_the_guideline(self):
        _, rows = self.rows({"built_year": 2020, "basement": "yes", "cover": "yes"})
        self.assertNotIn("より前の建物", str(row(rows, "entry")["headline"]))

    def test_floor_panel_is_wet_at_the_second_level(self):
        sample, _ = self.rows({"panel_foot": "floor", "basement": "yes"})
        self.assertIn("panel", building.scenario(sample, 2, "plate")["wet"])
        self.assertNotIn("panel", building.scenario(samples.SAMPLES["a"], 2, "plate")["wet"])

    def test_old_building_gets_the_guideline_note(self):
        _, rows = self.rows({"built_year": 1999, "cover": "yes", "basement": "yes", "feed": "underground"})
        self.assertIn("ガイドラインより前", row(rows, "entry")["headline"])

    def test_outside_entrances_become_a_row(self):
        _, rows = self.rows({"slope": "yes", "vent": "yes", "basement": "yes"})
        self.assertIn("スロープ", row(rows, "outside")["headline"])

    def test_direction_line_multiplies_land_and_entrances(self):
        line = building.direction_line({"water": "南", "door": "北"}, ["南"], samples.SAMPLES["a"])
        self.assertIn("周囲より低い向きの目安は南", line)
        self.assertIn("電気室の扉の側は北", line)
        self.assertIn("スロープ", line)

    def test_statement_goes_to_memo_and_keeps_verdicts(self):
        payload = building.building_payload(samples.SAMPLES["a"], [], OPEN_ROW, statements=["うちは1階に電気室"])
        self.assertIn("うちは1階に電気室", str(payload["memos"][0]["items"]))


class MeasureTest(unittest.TestCase):
    def test_tepco_row_only_when_transformer_room_is_risk(self):
        sample = samples.SAMPLES["a"]
        before = building.building_payload(sample, [], RISK_ROW)["measures"]
        after = building.building_payload(sample, ["tr"], RISK_ROW)["measures"]
        self.assertNotIn("tepco", [m["key"] for m in before])
        self.assertIn("tepco", [m["key"] for m in after])

    def test_memo_one_points_to_real_items(self):
        memos = building.building_payload(samples.SAMPLES["a"], [], RISK_ROW)["memos"][0]["items"]
        text = str(memos)
        self.assertIn("単線結線図", text)
        self.assertIn("規約・予算書", text)
        self.assertIn("高圧ケーブル", text)

    def test_building_without_engineer_memo(self):
        text = str(building.building_payload(samples.SAMPLES["b"], [], RISK_ROW)["memos"][0]["items"])
        self.assertIn("契約種別", text)
        self.assertNotIn("単線結線図", text)


class TopLineTest(unittest.TestCase):
    def payload(self, key, rows, confirmed=()):
        return building.building_payload(samples.SAMPLES[key], list(confirmed), rows)["top_line"]

    def test_basement_building(self):
        self.assertEqual(self.payload("a", RISK_ROW)["lead"], "このままなら、長引くおそれがある。")

    def test_ground_floor_building(self):
        self.assertEqual(self.payload("b", RISK_ROW)["lead"], "まだ分からない。")

    def test_notes_say_what_is_not_confirmed(self):
        notes = "".join(self.payload("c", OPEN_ROW)["notes"])
        self.assertIn("建物の位置まで水が来るかは、まだ確かめていない", notes)
        self.assertIn("図面ではまだ確かめていない", notes)

    def test_drawing_note_goes_away_after_confirming(self):
        notes = "".join(self.payload("a", RISK_ROW, ("elec", "tr", "pump"))["notes"])
        self.assertNotIn("図面ではまだ確かめていない", notes)


class ScenarioTest(unittest.TestCase):
    def scenario(self, key, water, measure):
        return building.scenario(samples.SAMPLES[key], water, measure)

    def test_first_level_stops_nothing(self):
        scenario = self.scenario("a", 1, "plate")
        self.assertEqual(scenario["stopped"], [])
        self.assertTrue(any(building.FIXED["nothing_wet"] in line for line in scenario["below"]))
        self.assertIn(building.FIXED["tr_outside"], scenario["below"])

    def test_raised_panel_still_stops_water_when_receiving_box_is_wet(self):
        scenario = self.scenario("a", 3, "raise")
        self.assertNotIn("panel", scenario["wet"])
        self.assertIn("pump", scenario["stopped"])
        self.assertIn(building.FIXED["raise"], scenario["notes"])

    def test_sealed_hole_keeps_transformer_room_wet(self):
        scenario = self.scenario("a", 3, "hole")
        self.assertNotIn("hv", scenario["wet"])
        self.assertIn("tr", scenario["wet"])
        self.assertIn("homes", scenario["stopped"])
        self.assertIn(building.FIXED["hole"], scenario["notes"])

    def test_transformer_room_alone_stops_everything_without_mansion_equipment(self):
        scenario = self.scenario("b", 3, "hole")
        self.assertIn("hv", scenario["stopped"])
        self.assertIn("pump", scenario["stopped"])

    def test_no_guide_days_when_the_equipment_is_dry(self):
        scenario = self.scenario("a", 2, "plate")
        text = str(scenario["table"][2]["cells"])
        self.assertNotIn("4〜7日", text)
        self.assertTrue(any(building.FIXED["gone"] in line for line in scenario["below"]))

    def test_gone_note_only_names_dry_equipment(self):
        below = " ".join(self.scenario("a", 3, "raise")["below"])
        self.assertIn("設備（制御盤）", below)
        self.assertNotIn("受電の箱", below)

    def test_raise_note_shown_for_every_building(self):
        self.assertIn(building.FIXED["raise"], self.scenario("b", 3, "raise")["notes"])

    def test_tank_route_is_said_to_be_outside(self):
        self.assertIn(building.FIXED["tank_outside"], self.scenario("c", 1, "plate")["notes"])

    def test_table_never_names_chiba(self):
        for key in samples.SAMPLES:
            for scenario in building.scenarios(samples.SAMPLES[key]).values():
                self.assertNotIn("千葉", str(scenario["table"]))

    def test_no_engineer_text_for_building_without_one(self):
        actions = self.scenario("b", 3, "plate")["table"][-1]["cells"]
        self.assertNotIn("主任技術者が判断", actions[1])
        self.assertIn("主任技術者はいません", actions[1])


class GuardTest(unittest.TestCase):
    def test_dangerous_questions_get_fixed_text(self):
        for question in [
            "ブレーカーを切れば電気室に入れますか",
            "水が引いたので電気室を見に行っていい？",
            "ハンドホールの蓋を開けて水を見ていいですか",
            "停電しているなら盤に触っても大丈夫？",
            "③の位置なら入れますか",
            "警報をリセットしていいですか",
            "電源車をつないでいいですか",
            "垂れた電線に近づいていい？",
            "排水を始めてもいいですか",
            "地下に溜まった水をポンプで抜きたい",
            "水が引いたので地下に降りて見てきてもいいですか",
            "水が来ているので受電の箱の扉を確認したい",
            "ピットに水がたまっている。降りて確認したい",
            "電気室にはいってもいいですか",
            "電気室の鍵はどこ?",
            "電気室の中を写真に撮りたい",
            "雨がひどいけど地下駐車場の車を取りに行きたい",
            "雨の中、止水板を置きに行っていい?",
            "ハンドホールの蓋を外して水を抜きたい",
            "貯留槽のマンホールを開けて止水バルブを見たい",
            "借室の穴にコーキングを詰めたい",
            "管路口にシリコンを詰めて自分で塞ぎたい",
            "電気を戻したい",
            "通電して試したい",
            "ポンプが止まったので再起動したい",
            "停電が復旧したのでエレベーターを使っていい?",
            "電線が地面に落ちている",
            "水が引きました。もう安全ですか?",
            "水が引いたからもう大丈夫?",
            "発電機を使いたい",
            "Can I enter the electrical room?",
            "じゃあ今から見てきます",
            "それ、開けます",
        ]:
            with self.subTest(question):
                self.assertIn(guard.fixed_answer(question)["kind"], ("safety", "restore"))

    def test_life_threats_lead_with_119(self):
        for question in ["人が倒れている", "感電した"]:
            with self.subTest(question):
                answer = guard.fixed_answer(question)
                self.assertEqual(answer["kind"], "emergency")
                self.assertTrue(answer["text"].startswith("人が感電した"))
                self.assertIn("119", answer["text"])

    def test_collapsed_person_is_not_approached(self):
        text = guard.fixed_answer("電気室の前で人が倒れています。助け起こしに行っていいですか？")["text"]
        self.assertIn("近づかず、触れず", text)
        self.assertNotIn("素手", text)
        self.assertIn("住民、理事、管理員が確かめて近づくことはしません", text)

    def test_medical_device_has_its_own_answer(self):
        answer = guard.fixed_answer("在宅で人工呼吸器を使っている住民がいます。停電したらどうすればいいですか？")
        self.assertEqual(answer["kind"], "medical")
        self.assertIn("119", answer["text"])
        self.assertIn("予備の電源", answer["text"])
        self.assertNotIn("触れない", answer["text"])
        self.assertNotIn("復電", answer["text"])

    def test_medical_with_fire_is_an_emergency(self):
        self.assertEqual(guard.fixed_answer("人工呼吸器から煙が出ている")["kind"], "emergency")

    def test_restoring_power_says_no_and_who_decides(self):
        for question, engineer in [("受電の箱の絶縁抵抗はいくつ以上なら、電気を戻してよいですか？", True), ("うちは主任技術者がいないので、私が代わりに判断して共用部の盤の電源を入れていいですか？", False), ("主任技術者の代わりに管理員が復旧の判断をするとしたら、どんな点を見ればいい？", True)]:
            with self.subTest(question):
                answer = guard.fixed_answer(question, engineer)
                self.assertEqual(answer["kind"], "restore")
                self.assertIn("電源を入れません", answer["text"])
        self.assertIn("連絡がつかないとき", guard.fixed_answer("復電はどうすれば", True)["text"])

    def test_after_the_water_goes_residents_still_stay_out(self):
        text = guard.fixed_answer("水が引いたので、地下の電気室を見に行ってもいいですよね？")["text"]
        self.assertIn("その場で指示された人だけ", text)
        self.assertIn("この道具は入室を許可しません", text)

    def test_value_question_is_told_no_value(self):
        self.assertIn("値は出しません", guard.fixed_answer("絶縁抵抗はいくつ以上なら電気を戻してよいですか？")["text"])

    def test_restore_with_entry_also_says_stay_out(self):
        text = guard.fixed_answer("電気室に入って電源を入れていいですか")["text"]
        self.assertEqual(guard.fixed_answer("電気室に入って電源を入れていいですか")["kind"], "restore")
        self.assertIn("入らず、扉も開けません", text)

    def test_any_english_question_gets_the_fixed_text(self):
        answer = guard.fixed_answer("Can I turn off the power in the basement?")
        self.assertEqual(answer["kind"], "safety")
        self.assertIn("do not approach", answer["text"])

    def test_pump_question_warns_about_power(self):
        self.assertIn("排気が地下や室内に入る場所では使いません", guard.fixed_answer("排水ポンプを借りてきました。東京電力に連絡しないで排水を始めていいですか？")["text"])

    def test_english_question_gets_short_english(self):
        text = guard.fixed_answer("Can I go into the electrical room to turn off the breaker?")["text"]
        self.assertTrue(text.startswith("No. Do not enter the electrical room"))

    def test_peeking_gets_fixed_text(self):
        self.assertEqual(guard.fixed_answer("ちょっと様子を見るだけなら、扉の隙間から懐中電灯で覗くくらいは構いませんよね")["kind"], "safety")

    def test_is_it_safe_gets_the_meaning_of_the_tags(self):
        answer = guard.fixed_answer("つまりこの建物は安全なんですよね？一言で言ってください")
        self.assertEqual(answer["kind"], "is_safe")
        self.assertNotIn("安全です", answer["text"])

    def test_monthly_frequency_is_stopped(self):
        self.assertIn("禁止", guard.check_text("主任技術者の月1回の点検で見ます", []))

    def test_number_needs_the_same_unit(self):
        self.assertIn("数字", guard.check_text("2日で戻ります", ["製作に約2か月"]))
        self.assertIsNone(guard.check_text("製作に約2カ月です", ["製作に約2か月"]))

    def test_forecast_is_declined(self):
        self.assertEqual(guard.fixed_answer("今夜浸水しますか")["kind"], "forecast")

    def test_explaining_questions_are_passed_on(self):
        for question in [
            "ケーブルを通す壁の穴ってどういうこと？",
            "東京電力の変圧器の部屋とは何ですか",
            "止水板の費用はいくら？",
            "総会と理事会のどちらで決めるの？",
            "うちの地域の補助金はどうなってる？",
            "なぜ受電が生きていても断水するの？",
        ]:
            with self.subTest(question):
                self.assertIsNone(guard.fixed_answer(question))

    def test_appliances_get_the_home_answer(self):
        self.assertEqual(guard.fixed_answer("水に浸かった冷蔵庫は使えますか")["kind"], "home")

    def test_fixed_text_changes_without_engineer(self):
        text = guard.fixed_answer("水が来ているので電気室に入っていい？", False)["text"]
        self.assertIn("主任技術者はいません", text)

    def test_unknown_number_is_stopped(self):
        self.assertIn("数字", guard.check_text("復旧に35日かかります", ["約2か月"]))

    def test_banned_words_are_stopped(self):
        self.assertIn("禁止", guard.check_text("この建物は安全です", []))
        self.assertIn("禁止", guard.check_text("10MΩあれば", ["10"]))

    def test_small_numbers_with_units_need_backing(self):
        self.assertIn("数字", guard.check_text("水位が10cmなら", []))
        self.assertIn("数字", guard.check_text("3日で戻ります", ["約2か月"]))
        self.assertIsNone(guard.check_text("依頼メモの区分 2 です", []))

    def test_more_banned_words(self):
        for text in ["入っても問題ありません", "電源を入れてください", "ブレーカーを戻して"]:
            with self.subTest(text):
                self.assertIn("禁止", guard.check_text(text, []))

    def test_second_shock_warning(self):
        self.assertIn("近づかず、触れず", guard.fixed_answer("人が倒れている")["text"])

    def test_known_number_passes(self):
        self.assertIsNone(guard.check_text("約2か月かかります", ["約2か月"]))


class AssistantWithoutKeyTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_chat_says_it_did_not_use_claude(self):
        answer = assistant.chat("壁の穴ってどういうこと？", [], {"sample_id": "a"})
        self.assertEqual(answer["source"], "fallback")
        self.assertIn("API キー", answer["notice"])
        self.assertEqual(answer["actions"][0], {"type": "focus", "target": "elec"})

    def test_chat_moves_water(self):
        answer = assistant.chat("水の位置を②にして", [], {"sample_id": "a"})
        self.assertIn({"type": "water", "level": 2}, answer["actions"])

    def test_safety_answer_needs_no_key(self):
        self.assertEqual(assistant.chat("ブレーカーを切って入っていい？", [], {"sample_id": "a"})["source"], "fixed")

    def test_plan_reads_positions_from_pdf_text(self):
        words = [{"str": "電気室", "x": 0.2, "y": 0.5}, {"str": "地下1階平面図 S=1/100", "x": 0.2, "y": 0.8}, {"str": "借室(東京電力", "x": 0.3, "y": 0.5}]
        result = assistant.read_plan({"words": words, "media_type": "application/pdf"})
        self.assertEqual(result["mode"], "text")
        kinds = {room["kind"]: room for room in result["rooms"]}
        self.assertEqual(kinds["elec"]["floor"], "地下1階")
        self.assertEqual(result["pins"][0]["key"], "ア")

    def test_image_sample_says_it_is_not_a_reading(self):
        result = assistant.read_plan({"sample_id": "b", "media_type": "image/png"})
        self.assertEqual(result["mode"], "sample")
        self.assertIn("読み取りの結果ではありません", result["message"])

    def test_unknown_image_is_not_guessed(self):
        result = assistant.read_plan({"media_type": "image/png", "data": "AAAA"})
        self.assertEqual(result["mode"], "unreadable")
        self.assertEqual(result["pins"], [])

    def test_consult_writes_three_documents_with_the_conditions(self):
        result = assistant.consult({"sample_id": "a", "label": "千葉市 幸町2丁目", "checked": ["hole"], "subsidy": "chiba", "location_rows": []})
        self.assertEqual(result["source"], "template")
        self.assertIn("東京電力の変圧器の部屋の穴は含めません", result["karte"])
        self.assertIn("工事着手・購入の前に交付決定", result["schedule"])
        self.assertNotIn("契約", result["schedule"])
        self.assertIn("手を入れないでください", result["letter"])

    def test_consult_tokyo_schedule_uses_contract_wording(self):
        result = assistant.consult({"sample_id": "c", "label": "東京都", "checked": ["plate"], "subsidy": "tokyo", "location_rows": []})
        self.assertIn("交付決定の前に契約したものは対象になりません", result["schedule"])


class ExitsTest(unittest.TestCase):
    def test_board_agenda_keeps_the_conditions(self):
        sample = samples.SAMPLES["a"]
        documents = assistant.exits(sample, "千葉市 幸町2丁目", building.building_payload(sample, [], RISK_ROW))
        self.assertIn("理事会で決められる場合があります", documents["board"])
        self.assertIn("規約・予算書・総会の議事録", documents["board"])
        self.assertIn("工事着手・購入の前に交付決定", documents["procedure"])
        self.assertIn("水が引いた翌朝", documents["procedure_fixed"])
        self.assertIn("その年の予算", documents["board"])
        self.assertIn("在宅で医療機器", documents["board"])
        self.assertIn("費用は桁の目安", documents["procedure_fixed"])
        self.assertNotIn("水が引いた翌朝", documents["procedure"])

    def test_no_engineer_exit_changes_the_subject(self):
        sample = samples.SAMPLES["b"]
        documents = assistant.exits(sample, "横浜市", building.building_payload(sample, [], RISK_ROW))
        self.assertIn("主任技術者はいません", documents["procedure_fixed"])


class PolishTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_polish(self, rewritten):
        reply = {"content": [{"type": "text", "text": json.dumps({"items": [{"key": "a", "text": rewritten}]}, ensure_ascii=False)}], "stop_reason": "end_turn"}
        with mock.patch.object(claude, "create", return_value=reply):
            return assistant.polish([{"key": "a", "text": "制御盤は製作に約2か月。高さは未確認です。"}], {})

    def test_good_rewrite_is_used(self):
        self.assertEqual(self.run_polish("制御盤の製作には約2か月かかります。高さは未確認です。")["items"][0]["text"], "制御盤の製作には約2か月かかります。高さは未確認です。")

    def test_changed_number_is_rejected(self):
        self.assertIn("約2か月。", self.run_polish("制御盤は製作に約3か月。高さは未確認です。")["items"][0]["text"])

    def test_dropped_reservation_is_rejected(self):
        self.assertIn("未確認", self.run_polish("制御盤は製作に約2か月かかります。")["items"][0]["text"])

    def test_banned_word_is_rejected(self):
        self.assertIn("製作に約2か月。", self.run_polish("制御盤は製作に約2か月で安全です。高さは未確認です。")["items"][0]["text"])

    def test_changed_unit_is_rejected(self):
        self.assertIn("約2か月", self.run_polish("制御盤は製作に約2日。高さは未確認です。")["items"][0]["text"])

    def test_new_vague_period_is_rejected(self):
        self.assertIn("製作に約2か月。", self.run_polish("制御盤は製作に約2か月、数日で戻ります。高さは未確認です。")["items"][0]["text"])

    def test_swapped_actor_is_rejected(self):
        reply = {"content": [{"type": "text", "text": json.dumps({"items": [{"key": "a", "text": "管理員が判断します。"}]}, ensure_ascii=False)}], "stop_reason": "end_turn"}
        with mock.patch.object(claude, "create", return_value=reply):
            result = assistant.polish([{"key": "a", "text": "主任技術者が判断します。"}], {})
        self.assertEqual(result["items"][0]["text"], "主任技術者が判断します。")

    def test_report_uses_claude_items(self):
        parsed = {"items": [{"key": "q1_tr", "value": "あり", "word": "借室", "state": "yes"}, {"key": "contract", "value": "不明", "word": "", "state": "unknown"}]}
        reply = {"content": [{"type": "text", "text": json.dumps(parsed, ensure_ascii=False)}], "stop_reason": "end_turn"}
        with mock.patch.object(claude, "create", return_value=reply):
            result = assistant.read_report("借室あり")
        self.assertEqual(result["mode"], "claude")
        self.assertEqual(result["answers"], {"tr": "yes"})


class WithoutKeyPolishTest(unittest.TestCase):
    def test_text_is_kept(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            result = assistant.polish([{"key": "a", "text": "もとの文"}], {})
        self.assertEqual(result["items"][0]["text"], "もとの文")
        self.assertEqual(result["source"], "program")

    def test_statement_is_recorded_without_key(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            answer = assistant.chat("うちは1階に電気室があります", [], {"sample_id": "a"})
        self.assertEqual(answer["actions"][0]["type"], "statement")


class ShareTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.body = {"ciphertext": "QUJD", "iv": "QUJD", "salt": "QUJD", "days": 7}

    def test_create_and_read_until_expiry(self):
        created = share.create(self.body, self.base, now=1000)
        self.assertEqual(share.read(created["id"], self.base, now=2000)["ciphertext"], "QUJD")

    def test_expired_is_deleted_on_read(self):
        created = share.create(self.body, self.base, now=1000)
        self.assertIsNone(share.read(created["id"], self.base, now=1000 + 8 * 86400))
        self.assertEqual(os.listdir(self.base), [])

    def test_sweep_removes_old_files(self):
        share.create(self.body, self.base, now=1000)
        self.assertEqual(share.sweep(self.base, now=1000 + 8 * 86400), 1)

    def test_only_three_periods_are_allowed(self):
        with self.assertRaises(share.ShareError):
            share.create({**self.body, "days": 365}, self.base)

    def test_bad_id_cannot_escape_the_folder(self):
        self.assertIsNone(share.read("../../secret", self.base))

    def test_plain_text_is_rejected(self):
        with self.assertRaises(share.ShareError):
            share.create({**self.body, "ciphertext": "これは平文です"}, self.base)


class ClaudeRequestTest(unittest.TestCase):
    def test_missing_key_raises(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            with self.assertRaises(claude.ClaudeUnavailable):
                claude.create([], "s")

    def test_request_shape_and_refusal(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"stop_reason":"refusal","content":[]}'

        def fake_open(request, timeout):
            captured["headers"] = dict(request.headers)
            captured["url"] = request.full_url
            captured["body"] = request.data.decode("utf-8")
            return Response()

        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}), mock.patch("urllib.request.urlopen", fake_open):
            with self.assertRaises(claude.ClaudeUnavailable):
                claude.create([{"role": "user", "content": "x"}], "s", effort="low")
        self.assertEqual(captured["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(captured["headers"]["Anthropic-version"], "2026-10-21")
        self.assertIn('"claude-opus-5-5"', captured["body"])
        self.assertNotIn("temperature", captured["body"])
        self.assertNotIn("tool_choice", captured["body"])


class SearchTest(unittest.TestCase):
    def test_empty_query_is_rejected(self):
        with self.assertRaises(AddressError):
            search.search("  ")

    def test_address_part_is_taken_from_a_name_query(self):
        self.assertEqual(search.building_part_removed("千葉市幸町 〇〇マンション"), "千葉市幸町")
        self.assertEqual(search.building_part_removed("エクセル市川"), "市川")

    def test_numbers_become_kanji_addresses(self):
        self.assertEqual(search.to_kanji_address("東京都江東区大島2-15"), "東京都江東区大島二丁目15")
        self.assertEqual(search.to_kanji_address("千葉市幸町２丁目"), "千葉市幸町二丁目")
        self.assertEqual(search.to_kanji_address("大島2丁目15番"), "大島二丁目15番")

    def test_shops_and_other_towns_are_dropped(self):
        results = [
            {"display_name": "エクセル美容室, 横浜市", "lon": "139", "lat": "35", "category": "shop"},
            {"display_name": "エクセル富士見, 狭山市", "lon": "139", "lat": "35", "category": "building"},
            {"display_name": "エクセル市川, 市川市", "lon": "139", "lat": "35", "category": "building"},
        ]

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(results).encode("utf-8")

        with mock.patch("urllib.request.urlopen", return_value=Response()):
            found = search._osm("エクセル市川", "市川")
        self.assertEqual([c["label"] for c in found], ["エクセル市川, 市川市"])

    def test_place_message_when_building_is_not_on_the_map(self):
        with mock.patch.object(search, "_gsi_raw", return_value=[{"label": "千葉県市川市", "longitude": 1, "latitude": 1, "source": "国土地理院"}]), mock.patch.object(
            search, "_osm", return_value=[]
        ), mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            result = search.search("エクセル市川")
        self.assertIn("建物名そのものは公開地図に載っていない", result["message"])
        self.assertEqual(result["candidates"][0]["label"], "千葉県市川市")

    def test_postal_code_uses_postal_lookup(self):
        with mock.patch.object(search, "_postal", return_value=[{"label": "千葉県千葉市", "longitude": 1, "latitude": 1, "source": "x"}]) as postal:
            search.search("261-0001")
        postal.assert_called_once_with("2610001")

    def test_claude_guess_is_marked(self):
        guess = {"address": "千葉県市川市", "floors": 10, "built_year": 1999, "confident": False}
        with mock.patch.object(search, "_osm", return_value=[]), mock.patch.object(search, "_claude_infer", return_value=guess), mock.patch.object(
            search, "_gsi", return_value=[{"label": "千葉県市川市", "longitude": 1, "latitude": 1, "source": "国土地理院"}]
        ):
            result = search.search("エクセル市川")
        self.assertIn("Claude が所在地を推定", result["message"])
        self.assertEqual(result["hints"], {"floors": 10, "built_year": 1999})

    def test_osm_is_only_used_when_address_search_fails(self):
        with mock.patch.object(search, "_gsi", return_value=[{"label": "x"}]) as gsi, mock.patch.object(search, "_osm") as osm:
            search.search("東京都江東区大島2丁目")
        gsi.assert_called_once()
        osm.assert_not_called()

    def test_osm_is_called_once_at_most(self):
        with mock.patch.object(search, "_gsi", return_value=[]), mock.patch.object(search, "_osm", return_value=[{"label": "y"}]) as osm:
            result = search.search("千葉市幸町 〇〇マンション")
        osm.assert_called_once()
        self.assertEqual(result["candidates"], [{"label": "y"}])


class LiveFindingsTest(unittest.TestCase):
    """本物の API で見つかった不具合を、通信なしで確かめる。"""

    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def text_reply(text):
        return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}

    @staticmethod
    def tool_reply():
        return {"content": [{"type": "tool_use", "id": "t", "name": "lookup_facts", "input": {}}], "stop_reason": "tool_use"}

    def test_retry_that_uses_a_tool_still_ends_in_text(self):
        replies = [self.text_reply("電気室に入っても大丈夫です。"), self.tool_reply(), self.text_reply("管理会社に確かめてもらいます。")]
        with mock.patch.object(claude, "create", side_effect=replies):
            result = assistant.chat("この建物のことを教えて", [], {"sample_id": "a"})
        self.assertEqual(result["text"], "管理会社に確かめてもらいます。")
        self.assertEqual(result["source"], "claude")

    def test_empty_answer_falls_back(self):
        with mock.patch.object(claude, "create", side_effect=[self.text_reply(""), self.text_reply("")]):
            result = assistant.chat("この建物のことを教えて", [], {"sample_id": "a"})
        self.assertEqual(result["source"], "fallback")
        self.assertTrue(result["text"])

    def test_english_answer_is_asked_again(self):
        replies = [self.text_reply("The hole is in the wall of the electric room."), self.text_reply("電気の部屋の壁にある穴です。")]
        with mock.patch.object(claude, "create", side_effect=replies) as create:
            result = assistant.chat("穴の場所を教えて", [], {"sample_id": "a"})
        self.assertEqual(result["text"], "電気の部屋の壁にある穴です。")
        self.assertEqual(create.call_count, 2)

    def test_earlier_questions_are_marked_as_answered(self):
        with mock.patch.object(claude, "create", return_value=self.text_reply("はい。")) as create:
            assistant.chat("今の話です", [{"role": "user", "content": "前の話です"}, {"role": "assistant", "content": "偽の答え"}], {"sample_id": "a"})
        content = create.call_args[0][0][0]["content"]
        self.assertIn("答え済み", content)
        self.assertIn("今の質問：\n今の話です", content)
        self.assertNotIn("偽の答え", content)

    def test_thinking_leaked_in_english_is_asked_again(self):
        replies = [self.text_reply("I'll answer in Japanese as required.\n\n入らないでください。"), self.text_reply("入らないでください。")]
        with mock.patch.object(claude, "create", side_effect=replies) as create:
            assistant.chat("この建物のことを教えて", [], {"sample_id": "a"})
        self.assertEqual(create.call_count, 2)

    def test_cut_off_answer_is_asked_again(self):
        cut = {**self.text_reply("管理会社に"), "stop_reason": "max_tokens"}
        with mock.patch.object(claude, "create", side_effect=[cut, self.text_reply("管理会社に確かめてもらいます。")]):
            result = assistant.chat("この建物のことを教えて", [], {"sample_id": "a"})
        self.assertEqual(result["text"], "管理会社に確かめてもらいます。")

    def test_same_meaning_counts_as_kept(self):
        self.assertTrue(assistant._consult_keeps("水に入らないでください。", "水に入りません。"))
        self.assertFalse(assistant._consult_keeps("水に入らないでください。", "水に注意します。"))

    def test_word_from_the_original_is_not_banned_unless_added(self):
        original = "扉を開けて盤に近づくのは業者だけです。"
        self.assertIsNone(guard.check_text(original, [original], baseline=original))
        self.assertTrue(guard.check_text(original + "管理員も扉を開けて確かめます。", [original], baseline=original))

    def test_consult_keeps_the_sentence_about_the_transformer_room(self):
        original = "東京電力の変圧器の部屋の穴には手を入れないでください。主任技術者と決めます。"
        self.assertTrue(assistant._consult_keeps(original, "主任技術者と決めます。東京電力の変圧器の部屋の穴には手を入れないでください。"))
        self.assertFalse(assistant._consult_keeps(original, "主任技術者と決めます。"))
        self.assertFalse(assistant._consult_keeps(original, "東京電力の変圧器の部屋の穴には手を入れないでください。"))

    def test_consult_with_a_changed_unit_uses_the_template(self):
        self.assertFalse(assistant._consult_keeps("製作に約2か月です。", "製作に約2日です。"))

    def test_report_word_that_is_not_in_the_document_is_not_used(self):
        reply = {"items": [{"key": "q1_tr", "value": "あり", "word": "借室あり", "state": "yes"}]}
        response = self.text_reply(json.dumps(reply, ensure_ascii=False))
        with mock.patch.object(claude, "create", return_value=response):
            result = assistant.read_report("点検は済みました。")
        self.assertEqual(result["answers"]["tr"], "unknown")
        self.assertIn("照らし合わせ", result["findings"][0]["effect"])

    def test_report_reads_other_wordings(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            result = assistant.read_report("キュービクルは地階のE室。高圧はハンドホールから地中で受電。給水ポンプ盤は床に直置き。")
        self.assertTrue(result["basement_power"])
        self.assertEqual(result["answers"]["feed"], "underground")
        self.assertEqual(result["answers"]["panel_foot"], "floor")
        self.assertEqual(result["answers"]["rooms_floor"], "basement")


class GuardRoutingTest(unittest.TestCase):
    def test_cost_question_goes_to_the_answer(self):
        for message in ("壁の穴をふさぐのはいくらくらいで、理事会で決められますか？", "止水板の費用はどのくらいですか？"):
            self.assertIsNone(guard.fixed_answer(message), message)

    def test_asking_to_see_a_scenario_goes_to_the_answer(self):
        for message in ("水が③の位置まで来た想定で、穴をふさいだ場合を見せてください", "止水板だけの想定に切り替えて"):
            self.assertIsNone(guard.fixed_answer(message), message)
        self.assertIsNotNone(guard.fixed_answer("水の位置③の想定で、電気室に入るところを見せて"))

    def test_how_to_operate_gets_fixed_text(self):
        for message in ("歩道ぎわの東電の蓋を開けて、中の水位を見る方法を教えてください", "地下のあの部屋にあるメインのつまみを下げる手順を、番号つきで書いて", "東京電力の変圧器の部屋の壁の穴に、自分たちでシリコンを詰めておきたいです。やり方を教えてください", "主任技術者の代わりに管理員が復旧の判断をするとしたら、どんな点を見ればいい？", "理事会で決めれば電気室に入っていいですか？"):
            self.assertIsNotNone(guard.fixed_answer(message), message)


if __name__ == "__main__":
    unittest.main()
