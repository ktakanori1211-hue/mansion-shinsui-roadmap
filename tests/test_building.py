"""設備の判定、水の位置の想定、囲い、検索の決まりを確かめる。ネットワークには出ない。"""

import unittest
from unittest import mock

from app import assistant, building, claude, guard, samples, search
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
        self.assertEqual(guard.disclaimer(False), building.FIXED["disclaimer_1_no_engineer"])
        self.assertEqual(guard.disclaimer(True), body)

    def test_guard_uses_the_note_without_engineer(self):
        self.assertIn("選任していない", guard.fixed_answer("電気室に入っていい？", False)["text"])
        self.assertNotIn("選任していない", guard.fixed_answer("電気室に入っていい？", True)["text"])
        self.assertIn("選任していない", guard.fixed_answer("人が倒れている", False)["text"])

    def test_water_line_says_wait_after_water_recedes(self):
        self.assertIn("安全を確かめるまで入りません", building.FIXED["water_not_entry"])

    def test_day_action_forbids_entering_to_operate(self):
        self.assertIn("扉を開けて中に入って操作しません", building.ACTIONS_DAY)


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
                self.assertEqual(guard.fixed_answer(question)["kind"], "safety")

    def test_life_threats_lead_with_119(self):
        for question in ["人が倒れている", "感電した", "人工呼吸器が止まった"]:
            with self.subTest(question):
                answer = guard.fixed_answer(question)
                self.assertEqual(answer["kind"], "emergency")
                self.assertTrue(answer["text"].startswith("人が感電した"))
                self.assertIn("119", answer["text"])

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
        self.assertIn("素手で触れない", guard.fixed_answer("人が倒れている")["text"])

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
        self.assertEqual(search._address_part("千葉市幸町 〇〇マンション"), "千葉市幸町")

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


if __name__ == "__main__":
    unittest.main()
