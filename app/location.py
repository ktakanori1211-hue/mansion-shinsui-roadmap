"""住所から、国の公開データの値を読み取る。

ここでは値を読むだけで、危険か安全かの判定はしない。
タイルが返らないことと、タイルの色がないことは別のものとして扱う。
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Optional
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
# 縮尺17 にタイルがないとき、周りに国の地図があるかを確かめる粗い縮尺。深さは読まない（粗い縮尺の色は縮尺17 と食い違うことがある）。
SURROUND_ZOOM = 13
SURROUND_REFINE_ZOOM = 15
# 粗い縮尺で一番近い色がこの距離より近いときだけ、一段細かい縮尺で距離を測り直す。仮の値。
SURROUND_REFINE_WITHIN_M = 400
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
    ("tsunami", "津波", "04_tsunami_newlegend_data"),
]

# 浸水継続時間（水が引くまでの時間）。重ねるハザードマップのオープンデータの「浸水継続時間（想定最大規模）」統合版。
# https://disaportal.gsi.go.jp/hazardmap/copyright/opendata.html （2026-11-05 に確認）
DURATION_LAYERS = [
    ("duration_max", "洪水(想定最大規模)の浸水継続時間", "01_flood_l2_keizoku_data"),
]
# 凡例画像（img/shinsui_legend_l2_keizoku.png）の色と区分。画像の色の箱をそのまま読んだ値で、完全に一致したときだけ返す。
# 凡例の注記：「2週間以上〜」の色の場合、「4週間以上〜」となる場合もある。
DURATION_LEGEND = {
    (160, 210, 255): "12時間未満",
    (0, 65, 255): "12時間〜1日未満",
    (250, 245, 0): "1日〜3日未満",
    (255, 153, 0): "3日〜1週間未満",
    (255, 40, 0): "1週間〜2週間未満",
    (180, 0, 104): "2週間以上〜",
    (96, 0, 96): "4週間以上〜",
}
DURATION_NOTE = "「2週間以上〜」の色の場合、「4週間以上〜」となる場合もあります（凡例の注記）"

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

# 国土地理院の地形分類（提供実験）の分類番号と名前。番号と名前は、国土地理院が配る style.js の表
# （https://cyberjapandata.gsi.go.jp/xyz/experimental_landformclassification1/style.js）をそのまま写した。
# 5桁の番号と7桁の番号の両方がある。表にない番号は名前を出さない。
LANDFORM_NAMES = {
    "10101": "山地斜面等",
    "10202": "崖・段丘崖",
    "10204": "崖・段丘崖",
    "10205": "地すべり地形",
    "10206": "地すべり地形",
    "10301": "台地・段丘",
    "10302": "台地・段丘",
    "10303": "台地・段丘",
    "10304": "台地・段丘",
    "10305": "台地・段丘",
    "10306": "台地・段丘",
    "10307": "台地・段丘",
    "10308": "台地・段丘",
    "10310": "台地・段丘",
    "10312": "台地・段丘",
    "10314": "台地・段丘",
    "10401": "山麓堆積地形",
    "10402": "山麓堆積地形",
    "10403": "山麓堆積地形",
    "10404": "山麓堆積地形",
    "10406": "山麓堆積地形",
    "10407": "山麓堆積地形",
    "10501": "扇状地",
    "10502": "扇状地",
    "10503": "自然堤防",
    "10504": "砂州・砂丘",
    "10505": "砂州・砂丘",
    "10506": "天井川等",
    "10507": "天井川等",
    "10508": "台地・段丘",
    "10512": "砂州・砂丘",
    "10601": "凹地・浅い谷",
    "10701": "氾濫平野・海岸平野",
    "10702": "氾濫平野・海岸平野",
    "10703": "後背低地・湿地",
    "10704": "旧河道",
    "10705": "氾濫平野・海岸平野",
    "10801": "天井川等",
    "10802": "河川敷・浜",
    "10803": "河川敷・浜",
    "10804": "後背低地・湿地",
    "10805": "水部",
    "10806": "水部",
    "10807": "河川敷・浜",
    "10808": "河川敷・浜",
    "10901": "水部",
    "10903": "水部",
    "10904": "旧水部",
    "11001": "切土地",
    "11002": "農耕平坦化地",
    "11003": "切土地",
    "11004": "盛土地・埋立地",
    "11005": "盛土地・埋立地",
    "11006": "盛土地・埋立地",
    "11007": "盛土地・埋立地",
    "11008": "干拓地",
    "11009": "切土地",
    "11010": "改変工事中",
    "11011": "切土地",
    "11014": "盛土地・埋立地",
    "11201": "山地斜面等",
    "11202": "山地斜面等",
    "11203": "山地斜面等",
    "11204": "山地斜面等",
    "1010101": "山地斜面等",
    "2010101": "台地・段丘",
    "2010201": "崖・段丘崖",
    "2010301": "凹地・浅い谷",
    "3010101": "山麓堆積地形",
    "3020101": "扇状地",
    "3030101": "氾濫平野・海岸平野",
    "3030201": "後背低地・湿地",
    "3040101": "自然堤防",
    "3040201": "旧河道",
    "3040202": "旧河道",
    "3040301": "落堀",
    "3050101": "砂州・砂丘",
    "4010101": "干拓地",
    "4010201": "盛土地・埋立地",
    "4010301": "切土地",
    "5010201": "水部",
    "5010301": "旧水部",
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


def nearest_legend(image: png.Image, px: int, py: int, radius: int = NEARBY_PIXELS, legend: Optional[dict] = None):
    """代表点のすぐ近くの色を探す。タイルの外までは見ない。"""
    legend = HAZARD_LEGEND if legend is None else legend
    nearest = None
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x, y = px + dx, py + dy
            if not (0 <= x < image.width and 0 <= y < image.height):
                continue
            r, g, b, a = image.rgba(x, y)
            if a and (r, g, b) in legend:
                distance = dx * dx + dy * dy
                if nearest is None or distance < nearest[0]:
                    nearest = (distance, legend[(r, g, b)])
    return nearest[1] if nearest else None


def nearest_colored_m(image: png.Image, px: int, py: int, latitude: float, zoom: int) -> Optional[int]:
    """点から一番近い、色のついた画素までの距離（m）。タイルに色が一つもなければ None。"""
    best = None
    for y in range(image.height):
        for x in range(image.width):
            if image.rgba(x, y)[3]:
                distance = (x - px) ** 2 + (y - py) ** 2
                if best is None or distance < best:
                    best = distance
    if best is None:
        return None
    meters_per_pixel = 156543.03392 * math.cos(math.radians(latitude)) / 2**zoom
    return round(math.sqrt(best) * meters_per_pixel)


def _surround_distance(layer: str, longitude: float, latitude: float, zoom: int) -> Optional[int]:
    """粗い縮尺のタイル1枚で、一番近い色までの距離を測る。タイルがなければ HTTPError(404) がそのまま上がる。"""
    tile_x, tile_y, px, py = pixel_position(longitude, latitude, zoom)
    image = png.decode(_get(HAZARD_URL.format(layer=layer, z=zoom, x=tile_x, y=tile_y)))
    return nearest_colored_m(image, px, py, latitude, zoom)


def _read_surroundings(layer: str, longitude: float, latitude: float) -> dict:
    """縮尺17 にタイルがない層について、周りに国の地図があるかを確かめる（追加の取得は、このときだけ）。

    outside＝地図はあるが、この点は想定区域の外（nearest_m に一番近い区域までの距離）。
    no_tile＝粗い縮尺にもタイルがない、または色が一つもない（国の地図に載っていない）。
    fetch_failed＝読み込めなかった。
    見るのは点を含むタイル1枚（縮尺13 で約4km四方）なので、タイルの端に近い点は周りを見落とすことがある。
    """
    try:
        nearest = _surround_distance(layer, longitude, latitude, SURROUND_ZOOM)
    except urllib.error.HTTPError as error:
        return {"status": "no_tile" if error.code == 404 else "fetch_failed"}
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {"status": "fetch_failed"}
    if nearest is None:
        return {"status": "no_tile"}
    zoom = SURROUND_ZOOM
    if nearest <= SURROUND_REFINE_WITHIN_M:
        try:
            finer = _surround_distance(layer, longitude, latitude, SURROUND_REFINE_ZOOM)
        except (urllib.error.URLError, TimeoutError, ValueError):
            finer = None
        if finer is not None:
            nearest, zoom = finer, SURROUND_REFINE_ZOOM
    return {"status": "outside", "nearest_m": nearest, "nearest_zoom": zoom}


def _read_hazard(key: str, label: str, layer: str, longitude: float, latitude: float, legend: Optional[dict] = None, surroundings: bool = True) -> dict:
    legend = HAZARD_LEGEND if legend is None else legend
    tile_x, tile_y, px, py = pixel_position(longitude, latitude, HAZARD_ZOOM)
    url = HAZARD_URL.format(layer=layer, z=HAZARD_ZOOM, x=tile_x, y=tile_y)
    result = {"key": key, "label": label, "layer": layer, "legend": None, "nearby_legend": None}
    try:
        image = png.decode(_get(url))
    except urllib.error.HTTPError as error:
        result["status"] = "no_tile" if error.code == 404 else "fetch_failed"
        if error.code == 404 and surroundings:
            result.update(_read_surroundings(layer, longitude, latitude))
        return result
    except (urllib.error.URLError, TimeoutError, ValueError):
        result["status"] = "fetch_failed"
        return result
    r, g, b, a = image.rgba(px, py)
    if a == 0:
        result["status"] = "no_color"
        result["nearby_legend"] = nearest_legend(image, px, py, legend=legend)
    elif (r, g, b) in legend:
        result["status"] = "color"
        result["legend"] = legend[(r, g, b)]
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


def high_directions(points: list) -> list:
    """ピンより高い向き。丸めるのは、3.7 と 3.6 の差が小数の誤差で 0.1 に届かなくなるのを防ぐため。"""
    center = points[0]["elevation_m"]
    if center is None:
        return []
    return [point["label"] for point in points[1:] if point["elevation_m"] is not None and round(point["elevation_m"] - center, 2) >= LOW_MARGIN_M]


def is_basin(points: list) -> bool:
    """低い向きがなく、高い向きが二つ以上ある形。地図の標高データの目安で、判定には使わない。"""
    return not low_directions(points) and len(high_directions(points)) >= 2


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
        durations = [
            pool.submit(_read_hazard, key, label, layer, longitude, latitude, DURATION_LEGEND, False)
            for key, label, layer in DURATION_LAYERS
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
            "high_directions": high_directions(points),
            "basin": is_basin(points),
            "hazards": [future.result() for future in hazards],
            "hazard_legend": [
                {"color": "#%02x%02x%02x" % rgb, "label": label} for rgb, label in HAZARD_LEGEND.items()
            ],
            "landforms": [future.result() for future in landforms],
            "durations": [future.result() for future in durations],
            "duration_note": DURATION_NOTE,
        }
