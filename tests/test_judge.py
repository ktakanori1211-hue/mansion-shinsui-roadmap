"""立地の三分類の決まりを確かめる。ネットワークには出ない。"""

import re
import unittest

from app import judge, location, records, state
from app.location import HAZARD_LEGEND, AddressError, nearest_legend
from app.server import parse_pin


def hazard(key, status="no_color", legend=None, nearby=None):
    return {"key": key, "label": key, "layer": key, "status": status, "legend": legend, "nearby_legend": nearby}


def reading(hazards=None, center=20.0, around=(20.1, 20.0, 20.2, 20.1), codes=("10314",)):
    keys = ["flood_planned", "flood_max", "inland", "storm_surge"]
    given = hazards or {}
    return {
        "hazards": [given.get(key, hazard(key)) for key in keys],
        "elevation": {
            "distance_m": 50,
            "points": [{"key": "center", "label": "中心", "elevation_m": center}]
            + [{"key": str(i), "label": "北東南西"[i], "elevation_m": value} for i, value in enumerate(around)],
        },
        "landforms": [
            {"key": "natural", "label": "自然地形", "status": "found", "codes": list(codes), "names": [None] * len(codes)},
            {"key": "artificial", "label": "人工地形", "status": "none", "codes": [], "names": []},
        ],
    }


NO_RECORD = {"source": "s", "caution": "c", "confirm_by": "m", "note": None, "rows": []}


def row(rows, key):
    return next(item for item in rows if item.key == key)


class RepresentativePointTest(unittest.TestCase):
    # 2026-11-06 本人の決定：代表点でも、地図に色があれば「止まるおそれ」、色がなければ「問題なし（色なし）」。
    def test_color_at_representative_point_is_risk(self):
        rows = judge.judge_location(
            reading({"storm_surge": hazard("storm_surge", "color", "0.5m〜3m")}), state.REPRESENTATIVE, None
        )
        self.assertEqual(row(rows, "surge").verdict, state.RISK)
        self.assertIn("0.5m〜3m", row(rows, "surge").headline)
        self.assertTrue(any("代表点" in line for line in row(rows, "surge").details))

    def test_clean_values_at_representative_point_are_clear(self):
        rows = judge.judge_location(reading(), state.REPRESENTATIVE, NO_RECORD)
        self.assertTrue(all(item.verdict == state.CLEAR for item in rows))

    def test_nearby_color_is_reported(self):
        rows = judge.judge_location(
            reading({"flood_max": hazard("flood_max", nearby="〜0.5m")}), state.REPRESENTATIVE, None
        )
        self.assertIn("すぐ近く（数m先）", row(rows, "flood").headline)


class BuildingPositionTest(unittest.TestCase):
    def test_color_at_building_is_risk_without_confirmer(self):
        rows = judge.judge_location(reading({"inland": hazard("inland", "color", "〜0.3m")}), state.BUILDING, None)
        self.assertEqual(row(rows, "inland").verdict, state.RISK)
        self.assertIsNone(row(rows, "inland").confirm_by)

    def test_missing_tile_is_never_called_no_color(self):
        rows = judge.judge_location(reading({"inland": hazard("inland", "no_tile")}), state.BUILDING, NO_RECORD)
        inland = row(rows, "inland")
        self.assertEqual(inland.verdict, state.UNCONFIRMED)
        # 2026-11-11：「データなし」とまとめず、国の地図に載っていないと言う。
        self.assertIn("国の地図に載っていません", inland.headline)
        self.assertNotIn("色がありません", inland.headline)
        self.assertTrue(inland.confirm_by)

    def test_all_five_clean_at_building_are_clear(self):
        rows = judge.judge_location(reading(), state.BUILDING, NO_RECORD)
        self.assertTrue(all(item.verdict == state.CLEAR for item in rows))
        self.assertTrue(all(item.confirm_by is None for item in rows))

    def test_each_layer_is_judged_on_its_own(self):
        # 色なしの層は問題なし、データが取れない層は未確認（2026-11-06）。
        rows = judge.judge_location(reading({"storm_surge": hazard("storm_surge", "no_tile")}), state.BUILDING, NO_RECORD)
        self.assertEqual(row(rows, "flood").verdict, state.CLEAR)
        self.assertEqual(row(rows, "surge").verdict, state.UNCONFIRMED)

    def test_town_without_records_has_no_record_row(self):
        # 記録の行は手元に記録がある町丁だけ。代わりに地形分類の行が出る（2026-11-06 本人の指示）。
        rows = judge.judge_location(reading(), state.BUILDING, None)
        self.assertEqual([item.key for item in rows], ["flood", "inland", "surge", "ground", "landform", "rainband"])
        self.assertEqual(row(rows, "flood").verdict, state.CLEAR)

    def test_water_landform_is_a_caution_on_its_own_row(self):
        rows = judge.judge_location(reading(codes=("11005",)), state.BUILDING, NO_RECORD)
        rows[0].verdict  # noqa
        data = reading(codes=("11005",))
        data["landforms"][0]["names"] = ["盛土地・埋立地"]
        rows = judge.judge_location(data, state.BUILDING, NO_RECORD)
        self.assertEqual(row(rows, "landform").verdict, state.UNCONFIRMED)
        self.assertIn("盛土地・埋立地", row(rows, "landform").conclusion)
        self.assertEqual(row(rows, "ground").verdict, state.CLEAR)

    def test_missing_landform_data_is_unconfirmed(self):
        rows = judge.judge_location(reading(codes=()), state.BUILDING, NO_RECORD)
        self.assertEqual(row(rows, "landform").verdict, state.UNCONFIRMED)
        self.assertIn("データなし", row(rows, "landform").conclusion)

    def test_terrace_landform_is_clear(self):
        data = reading()
        data["landforms"][0]["names"] = ["台地・段丘"]
        rows = judge.judge_location(data, state.BUILDING, None)
        self.assertEqual(row(rows, "landform").verdict, state.CLEAR)


class GroundTest(unittest.TestCase):
    def test_depression_is_risk_with_the_elevation_in_the_conclusion(self):
        # 2026-11-06 本人の決定：凹みは「止まるおそれ」。理由に標高の数値を出す。
        rows = judge.judge_location(reading(center=10.0, around=(10.5, 10.4, 10.3, 10.6)), state.BUILDING, None)
        ground = row(rows, "ground")
        self.assertEqual(ground.verdict, state.RISK)
        self.assertEqual(ground.conclusion, "標高10.0m・周りより低い凹み")
        self.assertIn("くぼ地の仮の目安に当たります", ground.headline)
        higher = row(judge.judge_location(reading(center=20.5), state.BUILDING, None), "ground")
        self.assertEqual((higher.verdict, higher.conclusion), (state.CLEAR, "標高20.5m・周りより高い"))
        self.assertTrue(any("排水口" in line for line in ground.details))

    def test_flat_low_ground(self):
        rows = judge.judge_location(reading(center=3.0, around=(3.1, 3.0, 2.9, 3.0)), state.BUILDING, None)
        self.assertIn("低く平らな土地の仮の目安に当たります", row(rows, "ground").headline)

    def test_missing_elevation_is_reported(self):
        rows = judge.judge_location(reading(center=None), state.BUILDING, NO_RECORD)
        self.assertIn("一部取れていません", row(rows, "ground").headline)

    def test_landform_note_says_it_is_general(self):
        data = reading(codes=("11005",))
        data["landforms"][0]["names"] = ["盛土地・埋立地"]
        ground = row(judge.judge_location(data, state.REPRESENTATIVE, None), "ground")
        self.assertTrue(any("この敷地のリスクを示すものではありません" in line for line in ground.details))


class RecordTest(unittest.TestCase):
    def test_demo_towns_are_found_with_or_without_ward(self):
        self.assertIsNotNone(records.find("千葉市 幸町2丁目"))
        self.assertIsNotNone(records.find("横浜市 緑園3丁目"))
        self.assertIsNotNone(records.find("千葉市若葉区幸町二丁目1番"))

    def test_other_towns_are_not_found(self):
        self.assertIsNone(records.find("千葉市 幸町1丁目"))
        self.assertIsNone(records.find("千葉市 幸町21丁目"))
        self.assertIsNone(records.find("横浜市 幸町2丁目"))

    def test_saiwaicho_counts_rows_and_dates(self):
        rows = judge.judge_location(reading(), state.REPRESENTATIVE, records.find("千葉市 幸町2丁目"))
        record = row(rows, "record")
        self.assertEqual(record.verdict, state.RISK)
        self.assertIn("13行、日付は9つ", record.headline)

    def test_records_do_not_hold_block_numbers(self):
        rows = judge.judge_location(reading(), state.REPRESENTATIVE, records.find("千葉市 幸町2丁目"))
        record = row(rows, "record")
        self.assertEqual(len(record.records), 13)
        self.assertFalse(any(re.search(r"\d-\d", line) for line in record.records + record.details))


class StateTest(unittest.TestCase):
    def test_unknown_verdict_is_rejected(self):
        with self.assertRaises(ValueError):
            state.Row("k", "l", "危険", "h")

    def test_drawing_needs_a_person_to_confirm(self):
        read_only = state.Equipment("e", "電気室", state.UNCONFIRMED, "h", evidence=state.DRAWING)
        confirmed = state.Equipment(
            "e", "電気室", state.UNCONFIRMED, "h", evidence=state.DRAWING, confirmed_by_person=True
        )
        spoken = state.Equipment("e", "電気室", state.UNCONFIRMED, "h", evidence=state.QUESTION, confirmed_by_person=True)
        self.assertFalse(read_only.confirmed_on_drawing)
        self.assertTrue(confirmed.confirmed_on_drawing)
        self.assertFalse(spoken.confirmed_on_drawing)

    def test_new_state_has_the_shared_shape(self):
        site = state.Site("横浜市 緑園3丁目", 139.5, 35.4, state.REPRESENTATIVE, True)
        rows = judge.judge_location(reading(), state.REPRESENTATIVE, None)
        data = state.new_state(site, {}, rows)
        self.assertEqual(set(data), {"schema_version", "site", "location", "equipment", "pins"})
        self.assertEqual(len(data["location"]["rows"]), 6)  # 2026-11-07：大雨の型の行（rainband）が増えた
        self.assertEqual(data["location"]["rows"][0]["verdict_label"], "問題なし")


class PinTest(unittest.TestCase):
    def test_pin_outside_japan_is_rejected(self):
        with self.assertRaises(AddressError):
            parse_pin({"longitude": ["0"], "latitude": ["0"]})

    def test_broken_pin_is_rejected(self):
        with self.assertRaises(AddressError):
            parse_pin({"longitude": ["x"], "latitude": ["35"]})


class NearestLegendTest(unittest.TestCase):
    class FakeImage:
        width = height = 256

        def __init__(self, x, y, rgb):
            self.x, self.y, self.rgb = x, y, rgb

        def rgba(self, x, y):
            return (*self.rgb, 255) if (x, y) == (self.x, self.y) else (0, 0, 0, 0)

    def test_finds_color_within_radius(self):
        rgb = next(iter(HAZARD_LEGEND))
        self.assertEqual(nearest_legend(self.FakeImage(107, 100, rgb), 100, 100), HAZARD_LEGEND[rgb])

    def test_ignores_color_beyond_radius(self):
        rgb = next(iter(HAZARD_LEGEND))
        self.assertIsNone(nearest_legend(self.FakeImage(120, 100, rgb), 100, 100))



class CardFaceTest(unittest.TestCase):
    """カードの一段目の飾り。判定は変えない。"""

    def rows(self, data, basis=state.REPRESENTATIVE):
        return {row.key: row for row in judge.judge_location(data, basis, None)}

    def test_color_at_a_representative_point_is_accented_and_risk(self):
        data = reading({"flood_max": hazard("flood_max", "color", "3m〜5m")})
        row = self.rows(data)["flood"]
        self.assertEqual(row.verdict, state.RISK)
        self.assertEqual(row.value, "3m〜5m")
        # 大きな値がどちらの規模か（地図の別の規模の値と食い違って見えないように）。
        self.assertEqual(row.accent["badges"], ["ハザード着色あり", "想定最大の値"])
        self.assertEqual(row.accent["level"], "high")

    def test_deepest_color_is_the_big_value(self):
        data = reading({"flood_planned": hazard("flood_planned", "color", "0.5m〜3m"), "flood_max": hazard("flood_max", "color", "5m〜10m")})
        row = self.rows(data)["flood"]
        self.assertEqual(row.value, "5m〜10m")
        self.assertIn("想定最大", row.conclusion)

    def test_shallow_color_is_a_lighter_accent(self):
        data = reading({"storm_surge": hazard("storm_surge", "color", "0.5m〜1m")})
        self.assertEqual(self.rows(data)["surge"].accent["level"], "mid")

    def test_no_color_has_no_accent_and_is_clear(self):
        row = self.rows(reading())["flood"]
        self.assertIsNone(row.accent)
        self.assertEqual(row.value, "色なし")
        self.assertEqual(row.conclusion, "色なし")
        self.assertEqual(row.verdict, state.CLEAR)

    def test_no_data_is_not_called_no_color(self):
        row = self.rows(reading({"inland": hazard("inland", "no_tile")}))["inland"]
        self.assertEqual(row.value, judge.VALUE_NOT_ON_MAP)
        self.assertIsNone(row.accent)

    def test_nearby_color_is_accented(self):
        row = self.rows(reading({"inland": hazard("inland", nearby="〜0.5m")}))["inland"]
        self.assertEqual(row.accent["kind"], "nearby")

    def test_landform_is_accented(self):
        data = reading()
        data["landforms"][0]["names"] = ["旧水部"]
        data["landforms"][0]["codes"] = ["10904"]
        row = self.rows(data)["ground"]
        self.assertIn("地形分類：旧水部", row.accent["badges"])
        self.assertEqual(self.rows(data)["landform"].verdict, state.UNCONFIRMED)

    def test_basin_is_named_on_the_ground_card(self):
        data = reading(center=3.6, around=(3.7, 3.7, 3.6, 3.8))
        data["basin"] = True
        data["high_directions"] = ["北", "東", "西"]
        row = self.rows(data)["ground"]
        self.assertIn("周囲より低い凹み（目安）", row.accent["badges"])
        self.assertIn("周囲（北・東・西）より低い形", row.summary)
        self.assertEqual(row.verdict, state.RISK)
        self.assertEqual(row.conclusion, "標高3.6m・周りより低い凹み（北・東・西が高い）")


class BasinTest(unittest.TestCase):
    @staticmethod
    def points(center, north, east, south, west):
        names = [("中心", center), ("北", north), ("東", east), ("南", south), ("西", west)]
        return [{"label": name, "elevation_m": value} for name, value in names]

    def test_pin_lower_than_surroundings_is_a_basin(self):
        points = self.points(3.6, 3.7, 3.7, 3.6, 3.8)
        self.assertEqual(location.high_directions(points), ["北", "東", "西"])
        self.assertEqual(location.low_directions(points), [])
        self.assertTrue(location.is_basin(points))

    def test_a_low_side_is_not_a_basin(self):
        self.assertFalse(location.is_basin(self.points(3.6, 3.8, 3.8, 3.2, 3.8)))

    def test_flat_land_is_not_a_basin(self):
        self.assertFalse(location.is_basin(self.points(3.6, 3.6, 3.65, 3.6, 3.6)))

    def test_missing_center_is_not_a_basin(self):
        self.assertFalse(location.is_basin(self.points(None, 3.7, 3.7, 3.7, 3.7)))


if __name__ == "__main__":
    unittest.main()


class RainbandTest(unittest.TestCase):
    """大雨で、洪水の地図に色がなくても浸かる型（低い土地・くぼ地・内水の色）。規則で判定し、根拠は国土交通省の資料（2026-11-11 にウェザーニューズの数字から差し替え）。"""

    def test_low_landform_hits_even_without_map_colour(self):
        data = reading(codes=("11005",))
        data["landforms"][0]["names"] = ["後背低地"]
        rows = judge.judge_location(data, state.BUILDING, None)
        rain = row(rows, "rainband")
        self.assertEqual(rain.verdict, state.RISK)
        self.assertIn("土地の成り立ち", rain.conclusion)
        self.assertTrue(any("59%" in line and "内水氾濫" in line for line in rain.details))
        self.assertTrue(any("国土交通省" in line and "mlit.go.jp" in line for line in rain.details))
        self.assertTrue(any("空白域" in line for line in rain.details))
        # 色がなくても、型に当たるときは全部を問題なしにしない。
        self.assertEqual(row(rows, "flood").verdict, state.CLEAR)
        self.assertEqual([line["hit"] for line in rain.accent["lines"]], [True, False, False])

    def test_basin_hits_and_numbers_are_in_the_line(self):
        rows = judge.judge_location(reading(center=3.5, around=(3.6, 3.7, 3.4, 3.6)), state.BUILDING, None)
        rain = row(rows, "rainband")
        ground = rain.accent["lines"][1]
        self.assertIn("標高3.5m", ground["text"])
        self.assertIn("3.7", ground["text"])

    def test_inland_data_missing_is_said_not_assumed(self):
        rows = judge.judge_location(reading({"inland": hazard("inland", status="no_tile")}), state.BUILDING, None)
        rain = row(rows, "rainband")
        self.assertEqual(rain.verdict, state.UNCONFIRMED)
        self.assertEqual(rain.accent["lines"][2]["hit"], None)
        self.assertIn("内水", rain.conclusion)
        # 2026-11-07・13回目：データなしの理由（下水道未整備・側溝排水・処理能力超過）と、市の地図・下水道整備状況の確認を添える。数字は足さない。
        self.assertEqual(rain.accent["lines"][2]["text"], judge.INLAND_NO_DATA_SHORT)
        inland = row(rows, "inland")
        self.assertEqual(inland.value, judge.VALUE_NOT_ON_MAP)
        self.assertEqual(inland.conclusion, judge.INLAND_NO_DATA)
        for word in ("市の地図にはある場合がある", "排水が追いつかない", "洪水の地図に色のない区域でも冠水", "下水道の整備状況（合流式・分流式・側溝放流）"):
            self.assertIn(word, judge.INLAND_NO_DATA)
        self.assertNotRegex(judge.INLAND_NO_DATA, r"[0-9０-９]+[%％]")

    def test_clear_when_no_type_matches(self):
        rows = judge.judge_location(reading(), state.BUILDING, None)
        self.assertEqual(row(rows, "rainband").verdict, state.CLEAR)


def outside(key, nearest_m):
    return {**hazard(key, "outside"), "nearest_m": nearest_m, "nearest_zoom": 13}


class FourWordingsTest(unittest.TestCase):
    """「データなし」を、分かっている理由ごとに言い分ける（2026-11-11 本人の指摘）。"""

    def rows(self, data, basis=state.BUILDING, record=None):
        return {item.key: item for item in judge.judge_location(data, basis, record)}

    def test_outside_far_from_zone_is_clear_with_distance(self):
        flood = self.rows(reading({"flood_planned": outside("flood_planned", 3402), "flood_max": outside("flood_max", 741)}))["flood"]
        self.assertEqual(flood.verdict, state.CLEAR)
        self.assertEqual(flood.value, "想定区域の外")
        self.assertEqual(flood.conclusion, "一番近い区域まで約740m")
        self.assertIn("想定区域の外です（一番近い区域まで約740m）", flood.headline)
        self.assertIn("安全という意味ではありません", flood.headline)
        self.assertIsNone(flood.confirm_by)

    def test_outside_near_zone_is_unconfirmed_and_asks_to_check_the_building_position(self):
        flood = self.rows(reading({"flood_planned": outside("flood_planned", 2256), "flood_max": outside("flood_max", 135)}), state.REPRESENTATIVE)["flood"]
        self.assertEqual(flood.verdict, state.UNCONFIRMED)
        self.assertEqual(flood.verdict_label, "注意")
        self.assertEqual(flood.conclusion, "一番近い区域まで約140m")
        self.assertTrue(flood.confirm_by)
        self.assertTrue(any("建物の位置で確かめます" in line for line in flood.details))

    def test_threshold_is_two_hundred_meters(self):
        self.assertEqual(judge.NEAR_ZONE_M, 200)
        at = self.rows(reading({"storm_surge": outside("storm_surge", 200)}))["surge"]
        over = self.rows(reading({"storm_surge": outside("storm_surge", 201)}))["surge"]
        self.assertEqual((at.verdict, over.verdict), (state.UNCONFIRMED, state.CLEAR))

    def test_not_on_the_national_map_says_so_and_points_to_the_city_map(self):
        surge = self.rows(reading({"storm_surge": hazard("storm_surge", "no_tile")}))["surge"]
        self.assertEqual(surge.verdict, state.UNCONFIRMED)
        self.assertEqual(surge.value, "国の地図に載っていません")
        self.assertEqual(surge.conclusion, "市区町村のハザードマップで確かめます")
        self.assertIn(judge.NOT_ON_MAP_NOTE, surge.details)
        self.assertEqual(surge.summary, "国の地図になし")

    def test_fetch_failure_says_try_again(self):
        surge = self.rows(reading({"storm_surge": hazard("storm_surge", "fetch_failed")}))["surge"]
        self.assertEqual(surge.verdict, state.UNCONFIRMED)
        self.assertEqual(surge.value, "読み込めませんでした")
        self.assertEqual(surge.conclusion, "もう一度試します")
        self.assertIn("もう一度試します", surge.headline)

    def test_inland_outside_is_unconfirmed_even_far_from_zone(self):
        # 内水は市区町村ごとの地図なので、周りの市の色があるだけの「区域の外」を問題なしにしない（2026-11-11 本人が決定）。
        inland = self.rows(reading({"inland": outside("inland", 1300)}))["inland"]
        self.assertEqual(inland.verdict, state.UNCONFIRMED)
        self.assertNotEqual(inland.verdict_label, "注意")
        self.assertEqual(inland.value, "想定区域の外")
        self.assertEqual(inland.conclusion, "一番近い区域まで約1.3km。市区町村の内水ハザードマップで確かめます")
        self.assertIn("国の地図では", inland.headline)
        self.assertIn("市区町村の内水ハザードマップで確かめます", inland.headline)
        self.assertIn(judge.INLAND_OUTSIDE_NOTE, inland.details)
        self.assertTrue(inland.confirm_by)

    def test_inland_outside_near_zone_is_still_caution(self):
        inland = self.rows(reading({"inland": outside("inland", 150)}))["inland"]
        self.assertEqual((inland.verdict, inland.verdict_label), (state.UNCONFIRMED, "注意"))

    def test_inland_with_no_color_at_the_point_stays_clear(self):
        # 縮尺17 に市の地図があって色がない場合は、これまでどおり問題なし。
        inland = self.rows(reading({"inland": hazard("inland", "no_color")}))["inland"]
        self.assertEqual(inland.verdict, state.CLEAR)

    def test_other_layers_outside_far_stay_clear(self):
        surge = self.rows(reading({"storm_surge": outside("storm_surge", 1300)}))["surge"]
        self.assertEqual(surge.verdict, state.CLEAR)

    def test_inland_outside_is_unknown_in_rainband_and_blocks_all_clear(self):
        rows = self.rows(reading({"inland": outside("inland", 1300)}))
        line = next(l for l in rows["rainband"].accent["lines"] if l["name"] == "内水の地図")
        self.assertIsNone(line["hit"])
        self.assertIn("市の内水の図で確認", line["text"])
        self.assertNotEqual(rows["rainband"].verdict, state.CLEAR)

    def test_unreadable_color_is_not_called_a_fetch_failure(self):
        surge = self.rows(reading({"storm_surge": hazard("storm_surge", "unknown_color")}))["surge"]
        self.assertEqual(surge.value, "色を読み取れませんでした")
        self.assertEqual(surge.verdict, state.UNCONFIRMED)

    def test_one_layer_missing_from_the_map_keeps_the_row_unconfirmed(self):
        # 計画規模が国の地図になく、想定最大は区域の外：一つの層だけでは問題なしにしない（これまでの決まりのまま）。
        flood = self.rows(reading({"flood_planned": hazard("flood_planned", "no_tile"), "flood_max": outside("flood_max", 368)}))["flood"]
        self.assertEqual(flood.verdict, state.UNCONFIRMED)
        self.assertEqual(flood.value, "一部が国の地図に載っていません")
        self.assertIn("約370m", flood.conclusion)
        self.assertIn("計画規模：国の地図になし／想定最大：想定区域の外（一番近い区域まで約370m）", flood.summary)

    def test_color_wins_over_a_layer_outside_the_zone(self):
        flood = self.rows(reading({"flood_planned": outside("flood_planned", 194), "flood_max": hazard("flood_max", "color", "0.5m〜3m")}))["flood"]
        self.assertEqual(flood.verdict, state.RISK)
        self.assertEqual(flood.value, "0.5m〜3m")

    def test_all_clear_counts_outside_only_when_the_zone_is_far(self):
        far = judge.judge_location(reading({"storm_surge": outside("storm_surge", 1682)}), state.BUILDING, NO_RECORD)
        self.assertTrue(all(item.verdict == state.CLEAR for item in far))
        near = judge.judge_location(reading({"storm_surge": outside("storm_surge", 150)}), state.BUILDING, NO_RECORD)
        self.assertEqual(row(near, "surge").verdict, state.UNCONFIRMED)
        self.assertEqual(row(near, "flood").verdict, state.CLEAR)

    def test_rainband_reads_inland_outside_as_unknown(self):
        rain = self.rows(reading({"inland": outside("inland", 900)}))["rainband"]
        # 2026-11-11：内水の区域の外は「当たらない」でなく「確かめられていない」にした（本人が決定）。
        self.assertEqual(rain.accent["lines"][2], {"name": "内水の地図", "text": "想定区域の外（一番近い区域まで約900m）。市の内水の図で確認", "hit": None})
        failed = self.rows(reading({"inland": hazard("inland", "fetch_failed")}))["rainband"]
        self.assertIsNone(failed.accent["lines"][2]["hit"])
        self.assertIn("読み込めませんでした", failed.accent["lines"][2]["text"])

    def test_distance_is_rounded_to_ten_meters(self):
        self.assertEqual([judge.distance_text(m) for m in (4, 135, 741, 1268)], ["10m未満", "約140m", "約740m", "約1.3km"])


class TsunamiRowTest(unittest.TestCase):
    """津波の地図を判定に入れる（2026-11-11。高潮の行と同じ作り）。"""

    def with_tsunami(self, tsunami, **kwargs):
        data = reading(**kwargs)
        data["hazards"].append(tsunami)
        return data

    def test_row_comes_after_surge_and_is_risk_when_colored(self):
        rows = judge.judge_location(self.with_tsunami(hazard("tsunami", "color", "3m〜5m")), state.BUILDING, None)
        self.assertEqual([item.key for item in rows], ["flood", "inland", "surge", "tsunami", "ground", "landform", "rainband"])
        tsunami = row(rows, "tsunami")
        self.assertEqual((tsunami.verdict, tsunami.value, tsunami.label), (state.RISK, "3m〜5m", "津波"))
        self.assertIn("津波の想定に色があります（3m〜5m）", tsunami.headline)

    def test_not_on_the_map_is_unconfirmed_with_a_confirmer(self):
        tsunami = row(judge.judge_location(self.with_tsunami(hazard("tsunami", "no_tile")), state.BUILDING, None), "tsunami")
        self.assertEqual((tsunami.verdict, tsunami.value), (state.UNCONFIRMED, "国の地図に載っていません"))
        self.assertIn("津波", tsunami.confirm_by)

    def test_old_reading_without_the_layer_has_no_row(self):
        self.assertNotIn("tsunami", [item.key for item in judge.judge_location(reading(), state.BUILDING, None)])

    def test_deep_tsunami_counts_as_deep_water_for_the_building(self):
        from app import building
        rows = [{"key": "tsunami", "verdict": "risk", "value": "3m〜5m", "conclusion": ""}]
        self.assertTrue(building._deep_flood(rows))
        self.assertEqual(building._depth_label(rows), "津波 3m〜5m")
        self.assertFalse(building._deep_flood([{"key": "tsunami", "verdict": "risk", "value": "0.5m〜3m", "conclusion": ""}]))


class SourceLinesTest(unittest.TestCase):
    """出典と、加工した旨は分けて書く。国の公式の判定に見せない（規約の確認 2026-11-11）。"""

    def test_hazard_rows_carry_source_processing_note_and_disclaimers(self):
        flood = row(judge.judge_location(reading(), state.BUILDING, None), "flood")
        self.assertIn("出典：「ハザードマップポータルサイト」（https://disaportal.gsi.go.jp/hazardmap/copyright/opendata.html）", flood.details)
        self.assertIn("「ハザードマップポータルサイト」を加工して作成", flood.details)
        text = "".join(flood.details)
        for word in ("公式の判定ではありません", "市区町村のハザードマップで確かめます", "宅地建物取引業者の重要事項説明には使えません"):
            self.assertIn(word, text)

    def test_elevation_and_landform_sources_are_named_as_the_terms_ask(self):
        more = "".join(judge.ELEVATION_SOURCE_MORE)
        self.assertIn("出典：国土地理院ウェブサイト", more)
        self.assertIn("国土地理院ベクトルタイル提供実験", more)


class NoWeathernewsNumbersTest(unittest.TestCase):
    """ウェザーニューズの記事の数字は、利用規約（無許諾の二次利用・転載の禁止）のため使わない（2026-11-11）。"""

    OLD = ["64%", "447件", "36%", "16%", "48%", "55.7%", "216件", "158件", "73件", "weathernews", "ウェザーニューズ"]

    def test_app_and_chat_facts_do_not_carry_the_old_numbers(self):
        import pathlib
        from app import assistant
        root = pathlib.Path(__file__).resolve().parent.parent
        texts = {
            "judge": "\n".join([judge.RAIN_FACT, judge.RAIN_FACT_INLAND, judge.RAIN_SOURCE, judge.RAIN_INLAND_SOURCE, judge.RAIN_SOURCE_URL]),
            "assistant": "\n".join(item["text"] for item in assistant.FACTS),
            "materials": (root / "web" / "materials.json").read_text(encoding="utf-8"),
            "start.js": (root / "web" / "start.js").read_text(encoding="utf-8"),
        }
        for name, text in texts.items():
            for word in self.OLD:
                self.assertNotIn(word, text, f"{name}: {word}")

    def test_rainband_row_cites_the_ministry(self):
        rows = judge.judge_location(reading(), state.BUILDING, None)
        rain = row(rows, "rainband")
        self.assertEqual(rain.label, "大雨（洪水の地図の外で浸かる型）")
        self.assertIn("国土交通省", rain.accent["source"])
        self.assertIn("mlit.go.jp", rain.accent["inland_source_url"])

