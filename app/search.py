"""検索窓の 1 回の検索。ボタンを押したときだけ呼ぶ。入力補完はしない。

国土地理院の住所検索を先に使い、当たらなければ OpenStreetMap の Nominatim を 1 回だけ引く。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import List

from . import location

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "mansion-shinsui-roadmap (hackathon demo; one lookup per button press)"


def _gsi(query: str) -> List[dict]:
    url = location.GEOCODE_URL + "?" + urllib.parse.urlencode({"q": query})
    try:
        results = json.loads(location._get(url))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
    candidates = []
    for result in results:
        title = result["properties"]["title"]
        if location.title_matches(query, title):
            longitude, latitude = result["geometry"]["coordinates"]
            candidates.append({"label": title, "longitude": longitude, "latitude": latitude, "source": "国土地理院"})
    return candidates[:5]


def _osm(query: str) -> List[dict]:
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode({"q": query, "format": "jsonv2", "countrycodes": "jp", "limit": 5})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(request, timeout=location.TIMEOUT_SECONDS) as response:
            results = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
    return [
        {
            "label": result["display_name"],
            "longitude": float(result["lon"]),
            "latitude": float(result["lat"]),
            "source": "OpenStreetMap",
        }
        for result in results
    ]


def _address_part(query: str) -> str:
    """「千葉市幸町 〇〇マンション」から、住所らしい部分だけを取り出す。"""
    tokens = re.split(r"[\s　]+", query.strip())
    with_place = [token for token in tokens if re.search(r"(都|道|府|県|市|区|町|村|丁目|番)", token)]
    return with_place[0] if with_place else ""


def search(query: str) -> dict:
    query = query.strip()
    if not query:
        raise location.AddressError("住所かマンション名を入れてください。")
    candidates = _gsi(query)
    if not candidates:
        part = _address_part(query)
        if part and part != query:
            candidates = _gsi(part)
    if not candidates:
        candidates = _osm(query)
    if not candidates:
        raise location.AddressError("候補が見つかりませんでした。都道府県、市区町村（区を含む）、町丁まで入れてみてください。")
    return {"query": query, "candidates": candidates}
