import struct
import unittest
import zlib

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
