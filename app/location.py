"""住所から、国の公開データの値を読み取る。

ここでは値を読むだけで、危険か安全かの判定はしない。
タイルが返らないことと、タイルの色がないことは別のものとして扱う。
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import png

GEOCODE_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
ELEVATION_URL = "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php"
HAZARD_URL = "https://disaportaldata.gsi.go.jp/raster/{layer}/{z}/{x}/{y}.png"
LANDFORM_URL = "https://cyberjapandata.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.geojson"

HAZARD_ZOOM = 17
LANDFORM_ZOOM = 16
# 「すぐ近く（数m先）」として見る範囲。ズーム 17 の 1 ピクセルは東京付近で約 1m。仮の値。
NEARBY_PIXELS = 8
PROFILE_STEP_M = 50
LOW_MARGIN_M = 0.1  # 標高データの細かな差を向きの目安にしないための仮の値
TIMEOUT_SECONDS = 15
USER_AGENT = "mansion-shinsui-roadmap"

HAZARD_LAYERS = [
    ("flood_planned", "洪水(計画規模)", "01_flood_l1_shinsuishin_newlegend_data"),
    ("flood_max", "洪水(想定最大規模)", "01_flood_l2_shinsuishin_data"),
    ("inland", "内水", "02_naisui_data"),
    ("storm_surge", "高潮", "03_hightide_l2_shinsuishin_data"),
]

# 凡例画像の色と、そこに書かれた区分。完全に一致したときだけ区分を返す。
HAZARD_LEGEND = {
    (220, 122, 220): "20m〜",
    (242, 133, 201): "10m〜20m",
    (255, 145, 145): "5m〜10m",
    (255, 183, 183): "3m〜5m",
    (255, 216, 192): "0.5m〜3m",
    (248, 225, 166): "0.5m〜1m",
    (247, 245, 169): "〜0.5m",
    (255, 255, 179): "〜0.3m",
}

LANDFORM_LAYERS = [
    ("natural", "自然地形", "experimental_landformclassification1"),
    ("artificial", "人工地形", "experimental_landformclassification2"),
]

LANDFORM_NAMES = {
    "10101": "山地斜面等",
    "10314": "台地・段丘",
    "10406": "山麓堆積地形",
    "10512": "砂州・砂丘",
    "10601": "凹地・浅い谷",
    "10701": "氾濫平野・海岸平野",
    "10703": "後背低地・湿地",
    "10704": "旧河道",
    "10804": "後背低地・湿地",
    "10903": "水部",
    "10904": "旧水部",
    "11001": "切土地",
    "11004": "盛土地・埋立地",
    "11005": "盛土地・埋立地",
    "11006": "盛土地・埋立地",
    "11007": "盛土地・埋立地",
    "11008": "干拓地",
    "11014": "盛土地・埋立地",
}

DIRECTIONS = [("north", "北", 1, 0), ("east", "東", 0, 1), ("south", "南", -1, 0), ("west", "西", 0, -1)]

_KANJI_DIGITS = "〇一二三四五六七八九"


class AddressError(ValueError):
    """住所を町丁まで特定できないときの、利用者に見せる理由。"""


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def _from_kanji_number(text: str) -> int:
    tens, _, ones = text.rpartition("十")
    if "十" not in text:
        return _KANJI_DIGITS.index(text)
    return (_KANJI_DIGITS.index(tens) if tens else 1) * 10 + (_KANJI_DIGITS.index(ones) if ones else 0)


def normalize_address(text: str) -> str:
    """「二丁目1番1号」「2丁目1-1」「2-1-1」を同じ形にそろえる。"""
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    text = re.sub(r"[−ー‐―–—]", "-", text)
    text = re.sub(r"([〇一二三四五六七八九十]+)丁目", lambda m: f"{_from_kanji_number(m.group(1))}丁目", text)
    text = re.sub(r"丁目|番地|番", "-", text).replace("号", "")
    return text.rstrip("-")


def title_matches(query: str, title: str) -> bool:
    """検索結果が、入力した町丁そのものかを確かめる。

    この検索は、区名を省くと市だけの結果や別の区の結果を 1 件だけ返すことがある。
    結果の件数では見分けられないので、結果の住所が入力の中に現れるかで確かめる。
    """
    query = normalize_address(query)
    title = normalize_address(title)
    if re.search(r"(都|道|府|県|市|区|郡)$", title):
        return False
    tail = re.sub(r"^.+?(都|道|府|県)", "", title)
    for candidate in (title, tail):
        if candidate.endswith(query) or query.startswith(candidate + "-"):
            return True
    return False


def geocode(address: str) -> dict:
    url = GEOCODE_URL + "?" + urllib.parse.urlencode({"q": address})
    try:
        results = json.loads(_get(url))
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise AddressError("住所の検索に接続できませんでした。少し待ってからもう一度試してください。") from error
    matches = [r for r in results if title_matches(address, r["properties"]["title"])]
    if not matches:
        raise AddressError("町丁まで特定できませんでした。都道府県、市区町村(区を含む)、町丁まで入れてください。")
    if len(matches) > 1:
        raise AddressError("同じ名前の町丁が複数見つかりました。都道府県と区まで入れてください。")
    longitude, latitude = matches[0]["geometry"]["coordinates"]
    return {"longitude": longitude, "latitude": latitude}


def pixel_position(longitude: float, latitude: float, zoom: int) -> tuple:
    """(タイル x, タイル y, タイル内の px, タイル内の py) を返す。"""
    size = 256 * 2**zoom
    world_x = (longitude + 180) / 360 * size
    phi = math.radians(latitude)
    world_y = (1 - math.asinh(math.tan(phi)) / math.pi) / 2 * size
    return (int(world_x // 256), int(world_y // 256), int(world_x) % 256, int(world_y) % 256)


def nearest_legend(image: png.Image, px: int, py: int, radius: int = NEARBY_PIXELS):
    """代表点のすぐ近くの色を探す。タイルの外までは見ない。"""
    nearest = None
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x, y = px + dx, py + dy
            if not (0 <= x < image.width and 0 <= y < image.height):
                continue
            r, g, b, a = image.rgba(x, y)
            if a and (r, g, b) in HAZARD_LEGEND:
                distance = dx * dx + dy * dy
                if nearest is None or distance < nearest[0]:
                    nearest = (distance, HAZARD_LEGEND[(r, g, b)])
    return nearest[1] if nearest else None


def _read_hazard(key: str, label: str, layer: str, longitude: float, latitude: float) -> dict:
    tile_x, tile_y, px, py = pixel_position(longitude, latitude, HAZARD_ZOOM)
    url = HAZARD_URL.format(layer=layer, z=HAZARD_ZOOM, x=tile_x, y=tile_y)
    result = {"key": key, "label": label, "layer": layer, "legend": None, "nearby_legend": None}
    try:
        image = png.decode(_get(url))
    except urllib.error.HTTPError as error:
        result["status"] = "no_tile" if error.code == 404 else "fetch_failed"
        return result
    except (urllib.error.URLError, TimeoutError, ValueError):
        result["status"] = "fetch_failed"
        return result
    r, g, b, a = image.rgba(px, py)
    if a == 0:
        result["status"] = "no_color"
        result["nearby_legend"] = nearest_legend(image, px, py)
    elif (r, g, b) in HAZARD_LEGEND:
        result["status"] = "color"
        result["legend"] = HAZARD_LEGEND[(r, g, b)]
    else:
        result["status"] = "unknown_color"
    return result


def _ring_contains(ring: list, longitude: float, latitude: float) -> bool:
    inside = False
    previous = ring[-1]
    for point in ring:
        crosses = (point[1] > latitude) != (previous[1] > latitude)
        if crosses:
            at = (previous[0] - point[0]) * (latitude - point[1]) / (previous[1] - point[1]) + point[0]
            if longitude < at:
                inside = not inside
        previous = point
    return inside


def _polygon_contains(rings: list, longitude: float, latitude: float) -> bool:
    if not _ring_contains(rings[0], longitude, latitude):
        return False
    return not any(_ring_contains(hole, longitude, latitude) for hole in rings[1:])


def feature_contains(geometry: dict, longitude: float, latitude: float) -> bool:
    if geometry["type"] == "Polygon":
        return _polygon_contains(geometry["coordinates"], longitude, latitude)
    if geometry["type"] == "MultiPolygon":
        return any(_polygon_contains(p, longitude, latitude) for p in geometry["coordinates"])
    return False


def _read_landform(key: str, label: str, layer: str, longitude: float, latitude: float) -> dict:
    tile_x, tile_y, _, _ = pixel_position(longitude, latitude, LANDFORM_ZOOM)
    url = LANDFORM_URL.format(layer=layer, z=LANDFORM_ZOOM, x=tile_x, y=tile_y)
    result = {"key": key, "label": label, "codes": [], "names": []}
    try:
        collection = json.loads(_get(url))
    except urllib.error.HTTPError as error:
        result["status"] = "no_tile" if error.code == 404 else "fetch_failed"
        return result
    except (urllib.error.URLError, TimeoutError, ValueError):
        result["status"] = "fetch_failed"
        return result
    for feature in collection.get("features", []):
        if feature_contains(feature["geometry"], longitude, latitude):
            code = str(feature["properties"]["code"])
            result["codes"].append(code)
            result["names"].append(LANDFORM_NAMES.get(code))
    result["status"] = "found" if result["codes"] else "none"
    return result


def offset_point(longitude: float, latitude: float, north_m: float, east_m: float) -> tuple:
    return (
        round(longitude + east_m / (111000 * math.cos(math.radians(latitude))), 6),
        round(latitude + north_m / 111000, 6),
    )


def _read_elevation(longitude: float, latitude: float) -> dict:
    query = urllib.parse.urlencode({"lon": longitude, "lat": latitude, "outtype": "JSON"})
    try:
        body = json.loads(_get(ELEVATION_URL + "?" + query))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {"elevation_m": None, "source": None}
    value = body.get("elevation")
    # データがない地点では "-----" が返る。
    return {
        "elevation_m": value if isinstance(value, (int, float)) else None,
        "source": body.get("hsrc") or None,
    }


def low_directions(points: list) -> list:
    """周囲より低い向きの目安。どの道路かまでは分からない。"""
    center = points[0]["elevation_m"]
    if center is None:
        return []
    return [point["label"] for point in points[1:] if point["elevation_m"] is not None and point["elevation_m"] < center - LOW_MARGIN_M]


def read_location(longitude: float, latitude: float, distance_m: float = 50) -> dict:
    """代表点の値を読む。周囲の点の距離は仮の値で、判定の段階で決める。"""
    points = [("center", "中心", longitude, latitude)]
    for key, label, north, east in DIRECTIONS:
        points.append((key, label, *offset_point(longitude, latitude, north * distance_m, east * distance_m)))

    profile_axes = {"ns": (1, 0), "ew": (0, 1)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        profile_jobs = {
            axis: [
                (step * PROFILE_STEP_M, pool.submit(_read_elevation, *offset_point(longitude, latitude, north * step * PROFILE_STEP_M, east * step * PROFILE_STEP_M)))
                for step in (2, -2)
            ]
            for axis, (north, east) in profile_axes.items()
        }
        elevations = [
            (key, label, pool.submit(_read_elevation, lon, lat)) for key, label, lon, lat in points
        ]
        hazards = [
            pool.submit(_read_hazard, key, label, layer, longitude, latitude)
            for key, label, layer in HAZARD_LAYERS
        ]
        landforms = [
            pool.submit(_read_landform, key, label, layer, longitude, latitude)
            for key, label, layer in LANDFORM_LAYERS
        ]
        points = [{"key": k, "label": l, **future.result()} for k, l, future in elevations]
        by_key = {point["key"]: point["elevation_m"] for point in points}
        profile = {
            "ns": sorted(
                [(d, f.result()["elevation_m"]) for d, f in profile_jobs["ns"]]
                + [(distance_m, by_key["north"]), (0, by_key["center"]), (-distance_m, by_key["south"])],
                reverse=True,
            ),
            "ew": sorted(
                [(d, f.result()["elevation_m"]) for d, f in profile_jobs["ew"]]
                + [(distance_m, by_key["east"]), (0, by_key["center"]), (-distance_m, by_key["west"])]
            ),
        }
        return {
            "point": {"longitude": longitude, "latitude": latitude},
            "elevation": {"distance_m": distance_m, "points": points},
            "profile": profile,
            "low_directions": low_directions(points),
            "hazards": [future.result() for future in hazards],
            "hazard_legend": [
                {"color": "#%02x%02x%02x" % rgb, "label": label} for rgb, label in HAZARD_LEGEND.items()
            ],
            "landforms": [future.result() for future in landforms],
        }
