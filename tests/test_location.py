import struct
import unittest
import urllib.error
import zlib
from unittest import mock

from app import location, png


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def make_png(width, height, color_type, raw, extra=b"") -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        png.SIGNATURE
        + chunk(b"IHDR", header)
        + extra
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class PngTest(unittest.TestCase):
    def test_rgba_with_sub_and_up_filters(self):
        raw = bytes([1, 10, 20, 30, 255, 5, 5, 5, 0]) + bytes([2, 1, 1, 1, 0, 1, 1, 1, 0])
        image = png.decode(make_png(2, 2, 6, raw))
        self.assertEqual(image.rgba(0, 0), (10, 20, 30, 255))
        self.assertEqual(image.rgba(1, 0), (15, 25, 35, 255))
        self.assertEqual(image.rgba(1, 1), (16, 26, 36, 255))

    def test_palette_with_transparency(self):
        extra = chunk(b"PLTE", bytes([0, 0, 0, 255, 216, 192])) + chunk(b"tRNS", bytes([0]))
        image = png.decode(make_png(2, 1, 3, bytes([0, 0, 1]), extra))
        self.assertEqual(image.rgba(0, 0)[3], 0)
        self.assertEqual(image.rgba(1, 0), (255, 216, 192, 255))


class AddressMatchTest(unittest.TestCase):
    def test_city_only_result_is_rejected(self):
        self.assertFalse(location.title_matches("千葉市 幸町2丁目", "千葉県千葉市"))

    def test_wrong_ward_result_is_rejected(self):
        self.assertFalse(location.title_matches("横浜市緑園3丁目", "神奈川県横浜市緑区"))

    def test_same_town_with_arabic_number_is_accepted(self):
        self.assertTrue(location.title_matches("東京都江東区大島2丁目", "東京都江東区大島二丁目"))

    def test_query_without_prefecture_is_accepted(self):
        self.assertTrue(location.title_matches("江東区大島2丁目", "東京都江東区大島二丁目"))

    def test_block_number_after_town_is_accepted(self):
        self.assertTrue(location.title_matches("江東区大島2丁目1-1", "東京都江東区大島二丁目"))

    def test_block_number_in_result_is_accepted(self):
        for query in ("東京都江東区大島２丁目１−１", "東京都江東区大島2-1-1", "江東区大島2丁目1番1号"):
            self.assertTrue(location.title_matches(query, "東京都江東区大島二丁目１番１号"), query)

    def test_different_town_is_rejected(self):
        self.assertFalse(location.title_matches("江東区大島3丁目", "東京都江東区大島二丁目"))

    def test_longer_number_is_not_a_prefix_match(self):
        self.assertFalse(location.title_matches("江東区大島21丁目", "東京都江東区大島二丁目"))

    def test_kanji_tens_are_read(self):
        self.assertEqual(location.normalize_address("大島十二丁目"), location.normalize_address("大島12丁目"))
        self.assertEqual(location.normalize_address("大島二十丁目"), location.normalize_address("大島20丁目"))


class GeometryTest(unittest.TestCase):
    def test_pixel_position_matches_known_tile(self):
        self.assertEqual(location.pixel_position(139.519836, 35.441181, 17), (116333, 51720, 159, 181))

    def test_point_in_hole_is_outside(self):
        square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
        geometry = {"type": "Polygon", "coordinates": [square, hole]}
        self.assertTrue(location.feature_contains(geometry, 2, 2))
        self.assertFalse(location.feature_contains(geometry, 5, 5))
        self.assertFalse(location.feature_contains(geometry, 20, 5))


if __name__ == "__main__":
    unittest.main()


class SceneLayerTest(unittest.TestCase):
    """場面のカードが重ねる地図は、どれもサーバーが値を読む地図であること。"""

    def test_scene_layers_are_read_by_the_server(self):
        import pathlib
        import re

        # 画面は層の名前を自分で持たない（2026-11-06・9回目：ハザードマップの地図はやめ、判定表の行と標高の断面で見せる）。
        source = (pathlib.Path(__file__).resolve().parent.parent / "web" / "start.js").read_text(encoding="utf-8")
        used = set(re.findall(r'"(0\d_[a-z0-9_]+)"', source))
        self.assertEqual(used, set())
        self.assertNotIn("disaportaldata.gsi.go.jp/raster", source)

    def test_tsunami_is_read(self):
        self.assertIn("tsunami", [key for key, _, _ in location.HAZARD_LAYERS])


def tile(colored=()) -> bytes:
    """256×256 の透明なタイル。colored の (x, y) だけに洪水の凡例の色（0.5m〜3m）を置く。"""
    rows = []
    marks = set(colored)
    for y in range(256):
        line = bytearray([0])
        for x in range(256):
            line += bytes([255, 216, 192, 255]) if (x, y) in marks else bytes([0, 0, 0, 0])
        rows.append(bytes(line))
    return make_png(256, 256, 6, b"".join(rows))


def aside(px, pixels):
    """同じタイルの中で、px から pixels だけ横にずらした位置。"""
    return px + pixels if px + pixels < 256 else px - pixels


def not_found(url):
    return urllib.error.HTTPError(url, 404, "Not Found", None, None)


class SurroundingsTest(unittest.TestCase):
    """縮尺17 にタイルがないとき、周りに国の地図があるかを粗い縮尺で確かめる（2026-11-11）。ネットワークには出ない。"""

    LON, LAT = 135.47569, 34.67482

    def read(self, responses, **kwargs):
        """responses: 縮尺 → タイルの中身（bytes）か、例外。呼ばれた縮尺の順も返す。"""
        asked = []

        def fake(url):
            zoom = int(url.split("/")[-3])
            asked.append(zoom)
            answer = responses.get(zoom, not_found(url))
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(location, "_get", side_effect=fake):
            result = location._read_hazard("flood_max", "洪水(想定最大規模)", "01_flood_l2_shinsuishin_data", self.LON, self.LAT, **kwargs)
        return result, asked

    def point(self, zoom):
        return location.pixel_position(self.LON, self.LAT, zoom)[2:]

    def test_tile_at_17_is_read_without_extra_requests(self):
        px, py = self.point(17)
        result, asked = self.read({17: tile([(px, py)])})
        self.assertEqual((result["status"], result["legend"]), ("color", "0.5m〜3m"))
        self.assertEqual(asked, [17])

    def test_no_tile_at_17_but_color_far_away_is_outside_with_distance(self):
        px, py = self.point(13)
        result, asked = self.read({13: tile([(aside(px, 60), py)])})
        self.assertEqual(result["status"], "outside")
        self.assertEqual(result["nearest_zoom"], 13)
        # 縮尺13 の1画素は、この緯度で約15.7m。60画素で約940m。
        self.assertAlmostEqual(result["nearest_m"], 60 * 156543.03392 * 0.8224 / 2**13, delta=5)
        self.assertEqual(asked, [17, 13])
        self.assertIsNone(result["legend"])

    def test_near_color_is_measured_again_at_the_finer_zoom(self):
        px13, py13 = self.point(13)
        px15, py15 = self.point(15)
        result, asked = self.read({13: tile([(aside(px13, 8), py13)]), 15: tile([(aside(px15, 30), py15)])})
        self.assertEqual(asked, [17, 13, 15])
        self.assertEqual((result["status"], result["nearest_zoom"]), ("outside", 15))
        self.assertAlmostEqual(result["nearest_m"], 30 * 156543.03392 * 0.8224 / 2**15, delta=3)

    def test_finer_zoom_missing_keeps_the_coarse_distance(self):
        px, py = self.point(13)
        result, asked = self.read({13: tile([(aside(px, 8), py)])})
        self.assertEqual(asked, [17, 13, 15])
        self.assertEqual((result["status"], result["nearest_zoom"]), ("outside", 13))

    def test_no_tile_at_13_either_means_not_on_the_national_map(self):
        result, asked = self.read({})
        self.assertEqual(result["status"], "no_tile")
        self.assertNotIn("nearest_m", result)
        self.assertEqual(asked, [17, 13])

    def test_empty_tile_at_13_means_not_on_the_national_map(self):
        result, _ = self.read({13: tile()})
        self.assertEqual(result["status"], "no_tile")

    def test_server_error_is_a_fetch_failure_not_a_missing_map(self):
        result, asked = self.read({17: urllib.error.HTTPError("u", 503, "x", None, None)})
        self.assertEqual(result["status"], "fetch_failed")
        self.assertEqual(asked, [17])
        result, _ = self.read({13: urllib.error.URLError("down")})
        self.assertEqual(result["status"], "fetch_failed")

    def test_duration_layer_does_not_ask_for_coarser_tiles(self):
        result, asked = self.read({}, surroundings=False)
        self.assertEqual(result["status"], "no_tile")
        self.assertEqual(asked, [17])
