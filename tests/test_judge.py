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
        self.assertIn("データが取れて", inland.headline)
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
        self.assertEqual([item.key for item in rows], ["flood", "inland", "surge", "ground", "landform"])
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
        self.assertEqual(len(data["location"]["rows"]), 5)
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
        self.assertEqual(row.value, "データなし")
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
