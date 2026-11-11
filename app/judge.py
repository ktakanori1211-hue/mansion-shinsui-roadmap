"""読み取った立地の値を、三分類の行にする。

分からないことを危険とは言わない。未確認には、誰が確かめれば確定するかを添える。
2026-11-06 本人の決定：検索したら国のデータから一発で判定を出す。地図に色があれば「止まるおそれ」、色がなければ「問題なし（色なし）」。
土地の高さは標高と凹みで判定し、数値を出す。浸水の記録の行は、手元に記録がある町丁だけ。代わりに国の地形分類（土地の成り立ち）の行を出す。
"""

from __future__ import annotations

import re
from typing import List, Optional

from .state import BUILDING, CLEAR, REPRESENTATIVE, RISK, UNCONFIRMED, Row

# 仮の目安。検証前なので、当たっても確定にはしない。
DEPRESSION_DIFF_M = -0.3
LOW_ELEVATION_M = 5
FLAT_DIFF_M = 0.3

# 国の地形分類のうち、水に関わる説明がある分類。当たっても確定にはせず、問題なしから外すだけ。
WATER_LANDFORM_CODES = {
    "10601", "10703", "10704", "10804", "10904",
    "11004", "11005", "11006", "11007", "11008", "11014",
    # 同じ分類の7桁の番号（国土地理院の style.js の表で同じ名前のもの）。
    "2010301", "3030201", "3040201", "3040202", "5010301", "4010101", "4010201",
}

# 出典と、加工した旨は分けて書く（ハザードマップポータルサイトの利用規約の「出典」の書き方。2026-11-11 に原文で確認）。
HAZARD_SOURCE_URL = "https://disaportal.gsi.go.jp/hazardmap/copyright/opendata.html"
HAZARD_SOURCE = f"出典：「ハザードマップポータルサイト」（{HAZARD_SOURCE_URL}）"
HAZARD_PROCESSED = "「ハザードマップポータルサイト」を加工して作成"
# 国が作った判定に見せない。規約の注意（重要事項説明には使えない、最新・詳細は市町村のハザードマップで）をそのまま添える。
HAZARD_DISCLAIMER = [
    "この判定は、国の地図を読み取って加工した目安です。国や自治体の公式の判定ではありません。",
    "最新の詳しい内容は、市区町村のハザードマップで確かめます。",
    "宅地建物取引業者の重要事項説明には使えません。",
]
# 国の地図の区域の外でも、一番近い区域までがこの距離以内なら「未確認（注意）」にして、建物の位置で確かめてもらう。
# 仮の値（町丁の代表点と建物の位置のずれを見込んだもの。検証前）。
NEAR_ZONE_M = 200
VALUE_OUTSIDE = "想定区域の外"
VALUE_NOT_ON_MAP = "国の地図に載っていません"
VALUE_PARTLY_NOT_ON_MAP = "一部が国の地図に載っていません"
VALUE_FAILED = "読み込めませんでした"
VALUE_UNREADABLE = "色を読み取れませんでした"
NOT_ON_MAP_NEXT = "市区町村のハザードマップで確かめます"
FAILED_NEXT = "もう一度試します"
NOT_ON_MAP_NOTE = "国の地図に載っていないことは、浸水の想定がないという意味ではありません。市区町村が別に地図を出している場合があります。"
OUTSIDE_NOTE = "想定区域の外であることは、安全という意味ではありません。"
# 内水の地図は市区町村ごとに作られる。周りの市の色が数km先にあるだけで「区域の外」になり、この市の地図が載っていなくても問題なしに見えてしまう。
# そのため内水だけは、国の地図の「区域の外」を問題なしにせず、未確認にする（2026-11-11 本人が決定）。
INLAND_OUTSIDE_NOTE = "内水の地図は市区町村ごとに作られます。国の地図で区域の外でも、この市区町村の内水の地図が国の地図に載っていない場合があります。"
INLAND_OUTSIDE_NEXT = "市区町村の内水ハザードマップで確かめます"
# 線状降水帯の大雨で、洪水の地図に色がなくても浸かった場所の型（2026年9月の台風25号・千葉県の報道の実数。2026-11-07 原文で確認）。
RAIN_SOURCE_URL = "https://weathernews.jp/news/202609/220091/"
RAIN_SOURCE = "出典：ウェザーニューズ 2026/9/22「台風25号 千葉県の浸水・道路冠水447件の分析」"
RAIN_FACT = "2026年9月の台風25号（千葉県）の浸水・道路冠水447件の内訳：川沿いの低地36%（158件）、海・水路沿いの低地16%（73件）、川から離れた高台のくぼ地48%（216件）。後ろの2つ（足すと64%）は洪水の地図で色のない場所でした。"
RAIN_FACT_INLAND = "高台で冠水した場所の多くは、内水ハザードマップでは「0.5m未満」の色が付いていました（同じ記事）。"
# 「低い土地」の型に当たる国土地理院の地形分類（報道の「海・水路沿いの低い土地」に対応）。
_RAIN_LOW_LANDFORM = re.compile(r"後背低地|湿地|旧河道|三角州|海岸低地|埋立|干拓|旧水部|凹地|低地")
ELEVATION_SOURCE = "出典：国土地理院 標高API、地形分類（提供実験）を加工して作成"
# 別紙の出典の欄に、二文に分けて添える。上の文は変えない。
ELEVATION_SOURCE_MORE = [
    "出典：国土地理院ウェブサイト（標高 API：https://maps.gsi.go.jp/development/elevation_s.html）",
    "出典：国土地理院ベクトルタイル提供実験（地形分類：https://www.gsi.go.jp/bousaichiri/lfc_index.html）",
    "この値は、上のデータを読み取って加工したものです。",
]
# 地形分類の層が取れないときの言い方。判定はもとから未確認なので変えない。
_LANDFORM_MISSING = {"fetch_failed": "接続できず", "no_tile": "この地域のデータなし"}

_REPRESENTATIVE_NOTE = (
    "これは町丁の代表点の値で、建物の位置の値ではありません。"
    "地図の上でピンを建物の位置へ動かすと、その位置で読み直します。"
)
_BUILDING_NOTE = "これはピンの位置で読んだ値です。ピンの位置が建物からずれていれば、値も変わります。"

_FLOOD_CONFIRM = "管理会社が、市の洪水ハザードマップで、建物の位置に色があるかを確かめます。"
# 国の内水データがないときの理由（2026-11-07・13回目）。数字は足さない。仕組みの文は国交省「内水ハザードマップ作成の手引き（案）」（内水＝下水道等に雨水を排水できず地表面に溜まった水）と
# 市川市水害ハザードマップ（令和8年4月改訂版 p.5「大雨で排水が追いつかない時…内水氾濫が発生」）の範囲で書く。国のポータルに未配信でも市の地図にはある場合がある（市川市がその例）。
# 線状降水帯のカードの行は短く（理由は国の地図のカードに1回だけ）。
INLAND_NO_DATA_SHORT = "国の地図に載っていません（市の内水ハザードマップを確認）"
INLAND_NO_DATA = "国の内水データは未配信（市の地図にはある場合がある）。大雨で下水道や水路の排水が追いつかないときは、洪水の地図に色のない区域でも冠水が起きる。市の内水ハザードマップと、前面道路の下水道の整備状況（合流式・分流式・側溝放流）を確認"
_INLAND_CONFIRM = (
    "管理会社が市区町村に、大雨で下水や水路があふれる場合の浸水想定区域図があるか、"
    "あればこの住所に色があるかを確かめます。"
)
_SURGE_CONFIRM = (
    "管理会社が、県の高潮浸水想定区域図か市の高潮ハザードマップで、"
    "建物の位置の想定の深さと、その想定の条件を確かめます。"
)
_TSUNAMI_CONFIRM = (
    "管理会社が、県の津波浸水想定か市の津波ハザードマップで、"
    "建物の位置の想定の深さを確かめます。"
)
_GROUND_CONFIRM = "管理会社が、自治体の浸水履歴と内水の想定、管理員の記録で、敷地のまわりが冠水したことがあるかを確かめます。"
_RECORD_CONFIRM = "管理会社から市区町村の窓口へ、この町丁と隣の町丁で過去に浸水や道路冠水の記録があるかを問い合わせます。"


def _place(basis: str) -> str:
    return "町丁の代表点" if basis == REPRESENTATIVE else "ピンの位置"


def basis_note(basis: str) -> str:
    """どの点で読んだ値かの一文。全部の行に当たるので、行ごとには持たない。"""
    return _REPRESENTATIVE_NOTE if basis == REPRESENTATIVE else _BUILDING_NOTE


def distance_text(meters: float) -> str:
    """一番近い区域までの距離。10m 単位に丸める（粗い縮尺の1画素は十数m）。"""
    if meters < 10:
        return "10m未満"
    if meters < 1000:
        return f"約{int(round(meters, -1))}m"
    return f"約{meters / 1000:.1f}km"


def _outside_text(hazard: dict) -> str:
    return f"{VALUE_OUTSIDE}（一番近い区域まで{distance_text(hazard['nearest_m'])}）"


def _is_outside(hazard: dict) -> bool:
    """地図はあるが、この点は想定区域の外（縮尺17 にタイルがなく、粗い縮尺で周りに色がある）。"""
    return hazard["status"] == "outside" and hazard.get("nearest_m") is not None


def _is_inland_outside(hazard: dict) -> bool:
    """内水の「区域の外」。周りの市の地図があるだけかもしれないので、問題なしの根拠にしない。"""
    return hazard.get("key") == "inland" and _is_outside(hazard)


def _is_mapped(hazard: dict) -> bool:
    """国の地図があり、この点に色がないと分かっている（縮尺17 で色なし、または想定区域の外）。"""
    return hazard["status"] == "no_color" or _is_outside(hazard)


def _nearest_zone_m(hazards: List[dict]) -> Optional[float]:
    distances = [h["nearest_m"] for h in hazards if _is_outside(h)]
    return min(distances) if distances else None


def _status_text(hazard: dict) -> str:
    status = hazard["status"]
    if status == "color":
        return f"凡例の「{hazard['legend']}」の色"
    if status == "no_color":
        if hazard.get("nearby_legend"):
            return f"色がない（すぐ近く（数m先）に「{hazard['nearby_legend']}」の色）"
        return "色がない"
    if _is_outside(hazard):
        return _outside_text(hazard)
    if status == "no_tile":
        return VALUE_NOT_ON_MAP
    if status == "unknown_color":
        return "凡例にない色で、読み取れていない"
    return VALUE_FAILED


def _short_status(hazard: dict) -> str:
    status = hazard["status"]
    if status == "color":
        return f"色あり（{hazard['legend']}）"
    if status == "no_color":
        return f"色なし（数m先に{hazard['nearby_legend']}）" if hazard.get("nearby_legend") else "色なし"
    if _is_outside(hazard):
        return _outside_text(hazard)
    if status == "no_tile":
        return "国の地図になし"
    if status == "unknown_color":
        return "読み取れず"
    return "読み込めず"


_LAYER_SHORT = {"flood_planned": "計画規模", "flood_max": "想定最大"}

# 地図の凡例を深い順に並べたもの。カードの色の強さに使う。判定には使わない。
_LEGEND_DEPTH = ["20m〜", "10m〜20m", "5m〜10m", "3m〜5m", "0.5m〜3m", "0.5m〜1m", "〜0.5m", "〜0.3m"]
# 水に関わる説明がある地形分類のうち、カードで強調する名前。
_ACCENT_LANDFORM = re.compile(r"旧水部|低地|盛土|埋立|旧河道|凹地|干拓")


def _deepest(legends: List[str]) -> str:
    return min(legends, key=lambda legend: _LEGEND_DEPTH.index(legend) if legend in _LEGEND_DEPTH else len(_LEGEND_DEPTH))


def _legend_level(legend: str) -> str:
    index = _LEGEND_DEPTH.index(legend) if legend in _LEGEND_DEPTH else len(_LEGEND_DEPTH)
    return "high" if index <= 3 else "mid"


# 深さの帯。境目は公的な凡例の区分（3m、0.5m）をそのまま使い、新しい閾値は作らない。判定には使わない。
_BAND_DEEP = {"20m〜", "10m〜20m", "5m〜10m", "3m〜5m"}
_BAND_MID = {"0.5m〜3m", "0.5m〜1m"}
_BAND_SHALLOW = {"〜0.5m", "〜0.3m"}
BAND_LABELS = {"deep": "深い", "mid": "中くらい", "shallow": "浅い"}
BAND_SHALLOW_NOTE = "深さの帯が「浅い」でも、地下の部屋や床に近い盤には水が入ることがあります。"


def _legend_band(legend: str) -> Optional[str]:
    if legend in _BAND_DEEP:
        return "deep"
    if legend in _BAND_MID:
        return "mid"
    if legend in _BAND_SHALLOW:
        return "shallow"
    return None


def _hazard_face(hazards: List[dict]) -> tuple:
    """カードの一段目（大きな値、太字の一行、強調）。判定は変えない。"""
    colored = [h for h in hazards if h["status"] == "color"]
    nearby = [h for h in hazards if h.get("nearby_legend")]
    if colored:
        legend = _deepest([h["legend"] for h in colored])
        where = next(h for h in colored if h["legend"] == legend)
        line = f"{_LAYER_SHORT[where['key']]}の想定に色あり" if len(hazards) > 1 else "想定に色あり"
        band = _legend_band(legend)
        accent = {"kind": "hazard", "level": _legend_level(legend), "badges": ["ハザード着色あり"]}
        # 地図の切り替えで別の規模の値も見えるので、大きな値がどちらの規模かを札で言う（二つの値が食い違って見えないように）。
        if len(hazards) > 1:
            accent["badges"].append(f"{_LAYER_SHORT[where['key']]}の値")
        if band:
            line = f"{line}（深さの帯：{BAND_LABELS[band]}）"
            accent["band"] = band
            accent["band_label"] = BAND_LABELS[band]
        return legend, line, accent
    if nearby:
        legend = _deepest([h["nearby_legend"] for h in nearby])
        return legend, "ピンの点に色はなく、数m先に色あり", {"kind": "nearby", "level": "low", "badges": ["すぐ近くに色あり"]}
    if all(h["status"] == "no_color" for h in hazards):
        return "色なし", "色がないことは安全という意味ではありません", None
    nearest = _nearest_zone_m(hazards)
    if all(_is_mapped(h) for h in hazards):
        return VALUE_OUTSIDE, f"一番近い区域まで{distance_text(nearest)}", None
    # 「データなし」とまとめず、分かっている理由を言う（2026-11-11 本人の指摘：国の地図にないのか、読めなかったのかが見て分かるように）。
    if any(h["status"] == "unknown_color" for h in hazards):
        return VALUE_UNREADABLE, NOT_ON_MAP_NEXT, None
    if any(h["status"] not in ("no_color", "outside", "no_tile") for h in hazards):
        return VALUE_FAILED, FAILED_NEXT, None
    if any(_is_mapped(h) for h in hazards):
        known = f"載っている地図では{VALUE_OUTSIDE}（一番近い区域まで{distance_text(nearest)}）" if nearest is not None else "載っている地図では色なし"
        return VALUE_PARTLY_NOT_ON_MAP, f"{known}。{NOT_ON_MAP_NEXT}", None
    return VALUE_NOT_ON_MAP, NOT_ON_MAP_NEXT, None


def _hazard_summary(hazards: List[dict]) -> str:
    if len(hazards) == 1:
        return _short_status(hazards[0])
    return "／".join(f"{_LAYER_SHORT[h['key']]}：{_short_status(h)}" for h in hazards)


def _hazard_row(
    key: str, label: str, what: str, hazards: List[dict], basis: str, confirm: str, extra: List[str], confirm_short: str
) -> Row:
    place = _place(basis)
    colored = [h for h in hazards if h["status"] == "color"]
    nearby = [h for h in hazards if h.get("nearby_legend")]
    if colored:
        legends = "、".join(dict.fromkeys(h["legend"] for h in colored))
        headline = f"{place}で、{what}の想定に色があります（{legends}）。"
    elif all(h["status"] == "no_color" for h in hazards) and not nearby:
        headline = f"{place}では、{what}の地図に色がありません。色がないことは安全という意味ではありません。"
    elif nearby:
        legends = "、".join(dict.fromkeys(h["nearby_legend"] for h in nearby))
        headline = f"{place}では{what}の地図に色がありませんが、すぐ近く（数m先）に色があります（{legends}）。"
    elif any(_is_inland_outside(h) for h in hazards) and all(_is_mapped(h) for h in hazards):
        headline = f"{place}は、国の地図では{what}の想定区域の外です（一番近い区域まで{distance_text(_nearest_zone_m(hazards))}）。{INLAND_OUTSIDE_NOTE}{INLAND_OUTSIDE_NEXT}。"
    elif all(_is_mapped(h) for h in hazards):
        headline = f"{place}は、{what}の想定区域の外です（一番近い区域まで{distance_text(_nearest_zone_m(hazards))}）。{OUTSIDE_NOTE}"
    elif any(h["status"] == "unknown_color" for h in hazards):
        headline = f"{place}の{what}の地図の色を読み取れませんでした。市区町村のハザードマップで確かめます。"
    elif any(h["status"] not in ("no_color", "outside", "no_tile") for h in hazards):
        headline = f"{what}の地図を読み込めませんでした。もう一度試します。"
    elif any(_is_mapped(h) for h in hazards):
        headline = f"{what}の地図の一部が、国の地図に載っていません。市区町村のハザードマップで確かめます。"
    else:
        headline = f"{what}の想定は、国の地図に載っていません。市区町村のハザードマップで確かめます。"

    # 地図があって色がない（色なし・想定区域の外）なら問題なし。ただし区域の境目が近いときは、建物の位置で確かめるまで未確認にする。
    nearest = _nearest_zone_m(hazards)
    near_zone = nearest is not None and nearest <= NEAR_ZONE_M
    inland_outside = any(_is_inland_outside(h) for h in hazards)
    no_color = all(_is_mapped(h) for h in hazards) and not nearby and not near_zone and not inland_outside
    verdict = RISK if colored else CLEAR if no_color else UNCONFIRMED
    details = [f"{h['label']}：{_status_text(h)}" for h in hazards]
    if not colored and nearest is not None:
        details.append(OUTSIDE_NOTE)
        if inland_outside:
            details.append(INLAND_OUTSIDE_NOTE)
        if near_zone:
            details.append(f"区域の境目が近いので（{NEAR_ZONE_M}m以内。検証前の仮の目安）、建物の位置で確かめます。{place}と建物の位置がずれていると、区域に入ることがあります。")
    if not colored and any(h["status"] == "no_tile" for h in hazards):
        details.append(NOT_ON_MAP_NOTE)
    if colored and basis == REPRESENTATIVE:
        details.append("この色は町丁の代表点の値です。地図を押すと、建物の位置で読み直します。")
    if colored and _legend_band(_deepest([h["legend"] for h in colored])) == "shallow":
        details.append(BAND_SHALLOW_NOTE)
    details.extend(extra)
    details.extend([HAZARD_SOURCE, HAZARD_PROCESSED, *HAZARD_DISCLAIMER])
    open_item = verdict != RISK
    value, conclusion, accent = _hazard_face(hazards)
    if verdict == CLEAR and value == "色なし":
        conclusion = "色なし"
    row = Row(
        key,
        label,
        verdict,
        headline,
        details,
        confirm if open_item else None,
        summary=_hazard_summary(hazards),
        confirm_short=confirm_short if open_item else None,
        value=value,
        conclusion=conclusion,
        accent=accent,
    )
    if (nearby or (near_zone and value == VALUE_OUTSIDE)) and verdict == UNCONFIRMED:
        row.verdict_label = "注意"
    if key == "inland" and value == VALUE_NOT_ON_MAP:
        row.conclusion = INLAND_NO_DATA
    if inland_outside and value == VALUE_OUTSIDE:
        row.conclusion = f"{conclusion}。{INLAND_OUTSIDE_NEXT}"
    return row


def _ground_shape(center: float, around: List[float]) -> Optional[str]:
    if center - sum(around) / len(around) <= DEPRESSION_DIFF_M:
        return "depression"
    if center <= LOW_ELEVATION_M and all(abs(center - value) <= FLAT_DIFF_M for value in around):
        return "flat_low"
    return None


def _landform_names(landforms: List[dict]) -> List[str]:
    names = []
    for landform in landforms:
        for code, name in zip(landform["codes"], landform["names"]):
            names.append(name or "名前の分からない分類")
    return list(dict.fromkeys(names))


def _landform_clean(landforms: List[dict]) -> bool:
    """データがない地域や取れないときは、それだけで問題なしにしない。"""
    if any(landform["status"] == "fetch_failed" for landform in landforms):
        return False
    codes = [code for landform in landforms for code in landform["codes"]]
    return bool(codes) and not WATER_LANDFORM_CODES.intersection(codes)


def _ground_row(reading: dict, basis: str) -> Row:
    elevation = reading["elevation"]
    center = elevation["points"][0]["elevation_m"]
    around = [point["elevation_m"] for point in elevation["points"][1:]]
    place = _place(basis)
    details = []
    summary = "標高のデータが一部取れず"
    value = "データなし"
    conclusion = "標高のデータなし"
    verdict = UNCONFIRMED
    badges = []
    if center is None or None in around:
        headline = f"{place}と周囲の標高のデータが、一部取れていません。"
        details.append("標高が取れないので、くぼ地の目安を当てられません。")
    else:
        shape = _ground_shape(center, around)
        value = f"標高{center}m"
        mean = sum(around) / len(around)
        if shape == "depression":
            headline = f"{place}の標高は{center}mで、周囲より低く、水がたまるくぼ地の仮の目安に当たります。"
            summary = f"標高{center}m。くぼ地の仮の目安に当たる"
            conclusion = f"標高{center}m・周りより低い凹み"
            verdict = RISK
            badges.append("くぼ地の目安")
            details.append("くぼ地では、地表から入る水だけでなく、建物の排水口や雨水ますから水が上がってくる経路もありえます。起きるかどうかは判定していません。")
        elif shape == "flat_low":
            headline = f"{place}の標高は{center}mで、低く平らな土地の仮の目安に当たります。"
            summary = f"標高{center}m。低く平らな土地の仮の目安に当たる"
            conclusion = f"標高{center}m・低く平らな土地"
            verdict = UNCONFIRMED
            badges.append("低く平らな土地の目安")
            details.append("水の逃げ場がなく、放流先の海や川の水位が高いと排水できなくなることがあります。")
        elif center >= mean + 0.1:
            headline = f"{place}の標高は{center}mで、周囲より高く、くぼ地や低く平らな土地の仮の目安には当たりません。"
            summary = f"標高{center}m。周りより高い"
            conclusion = f"標高{center}m・周りより高い"
            verdict = CLEAR
        elif center >= mean - 0.1:
            headline = f"{place}の標高は{center}mで、周囲とほぼ同じ高さです。くぼ地や低く平らな土地の仮の目安には当たりません。"
            summary = f"標高{center}m。周りとほぼ同じ"
            conclusion = f"標高{center}m・周りとほぼ同じ"
            verdict = CLEAR
        else:
            headline = f"{place}の標高は{center}mで、周囲より少し低い土地です。くぼ地の仮の目安には当たりません。"
            summary = f"標高{center}m。周りより少し低い"
            conclusion = f"標高{center}m・周りより少し低い"
            verdict = UNCONFIRMED
        if reading.get("basin"):
            high = "・".join(reading.get("high_directions") or [])
            summary = f"{summary}。周囲（{high}）より低い形"
            conclusion = f"標高{center}m・周りより低い凹み（{high}が高い）"
            verdict = RISK
            badges.insert(0, "周囲より低い凹み（目安）")
            details.append(f"50m先の点では、周囲（{high}）の方がピンより高く、低い向きの点がありません。地図の標高データの目安で、雨や浸水の深さの予測ではありません。")
        points = "、".join(f"{p['label']} {p['elevation_m']}m" for p in elevation["points"][1:])
        details.append(f"周囲{elevation['distance_m']:g}m：{points}")
        details.append("目安と周囲の点の距離は検証前の仮のものです。比べる距離を変えると結果が変わることがあります。")
    details.append("標高は地図の標高データの値で、敷地を測ったものではありません。")
    names = _landform_names(reading["landforms"])
    badges.extend(f"地形分類：{name}" for name in names if _ACCENT_LANDFORM.search(name))
    if names:
        joined = "』『".join(names)
        details.append(f"国の地形分類で『{joined}』にあたる地域です（国土地理院。地形分類ごとの一般的なリスクで、この敷地のリスクを示すものではありません）。")
    for landform in reading["landforms"]:
        if landform.get("status") in _LANDFORM_MISSING:
            label = f"（{landform['label']}）" if landform.get("label") else ""
            details.append(f"地形分類{label}：地図のデータが取れていない（{_LANDFORM_MISSING[landform['status']]}）")
    details.append(ELEVATION_SOURCE)
    details.extend(ELEVATION_SOURCE_MORE)
    row = Row(
        "ground", "敷地の高低差", verdict, headline, details, _GROUND_CONFIRM if verdict == UNCONFIRMED else None,
        summary=summary, confirm_short="管理会社が履歴と管理員の記録で" if verdict == UNCONFIRMED else None,
        value=value, conclusion=conclusion,
        accent={"kind": "terrain", "level": "mid", "badges": badges} if badges else None,
    )
    # データがあって低い土地と分かるときは「注意」（データがなくて分からない未確認とは分ける。2026-11-06）。
    if verdict == UNCONFIRMED and value != "データなし":
        row.verdict_label = "注意"
    return row


# 土地の成り立ち（国の地形分類）。低地・埋立地・旧河道などは注意（未確認）、台地・段丘などは問題なし（2026-11-06 本人の決定）。
_LANDFORM_CAUTION = re.compile(r"低地|平野|三角州|旧河道|湿地|干拓|埋立|盛土|凹地|旧水部|谷|扇状地|砂州|砂丘|自然堤防|氾濫|後背|河川敷|浜|水部")
_LANDFORM_SAFE = re.compile(r"台地|段丘|山地|丘陵|火山|切土")
LANDFORM_CONFIRM = "地形分類は国土地理院の一般的な分類です。敷地のまわりの冠水歴は、管理会社が自治体の浸水履歴と管理員の記録で確かめます。"


def _landform_row(reading: dict) -> Row:
    landforms = reading.get("landforms") or []
    names = _landform_names(landforms)
    missing = [lf for lf in landforms if lf.get("status") in _LANDFORM_MISSING]
    details = ["国土地理院の地形分類（提供実験）。地形分類ごとの一般的なリスクで、この敷地のリスクを示すものではありません。", ELEVATION_SOURCE, *ELEVATION_SOURCE_MORE]
    if not names:
        why = "地図のデータが取れていない" if missing else "この地点の分類なし"
        return Row("landform", "土地の成り立ち（地形分類）", UNCONFIRMED, f"国の地形分類のデータが、この地点では取れていません。", details, LANDFORM_CONFIRM,
                   summary=why, confirm_short="管理会社が履歴と管理員の記録で", value="データなし", conclusion=f"データなし（{why}）")
    joined = "・".join(names)
    if any(_LANDFORM_CAUTION.search(name) for name in names):
        verdict = UNCONFIRMED
        headline = f"国の地形分類で『{joined}』にあたる地域です。水がたまりやすい、または地盤が低い土地の分類です。"
        conclusion = f"{joined}（水がたまりやすい土地の分類）"
    elif all(_LANDFORM_SAFE.search(name) for name in names):
        verdict = CLEAR
        headline = f"国の地形分類で『{joined}』にあたる地域です。周りより高い土地の分類です。"
        conclusion = f"{joined}（高い土地の分類）"
    else:
        verdict = UNCONFIRMED
        headline = f"国の地形分類で『{joined}』にあたる地域です。"
        conclusion = joined
    row = Row("landform", "土地の成り立ち（地形分類）", verdict, headline, details, LANDFORM_CONFIRM if verdict == UNCONFIRMED else None,
              summary=joined, confirm_short="管理会社が履歴と管理員の記録で" if verdict == UNCONFIRMED else None,
              value=joined, conclusion=conclusion)
    if verdict == UNCONFIRMED:
        row.verdict_label = "注意"
    return row


def _ground_clean(reading: dict) -> bool:
    points = reading["elevation"]["points"]
    center = points[0]["elevation_m"]
    around = [point["elevation_m"] for point in points[1:]]
    if center is None or None in around:
        return False
    return _ground_shape(center, around) is None and _landform_clean(reading["landforms"])


def _neighbor_parts(record: dict) -> tuple:
    """隣の町丁を、記録あり・記録なし・未収録に分ける。"""
    found, empty, missing = [], [], []
    for neighbor in record.get("neighbors") or []:
        if neighbor.get("rows") is None:
            missing.append(neighbor["town"])
        elif neighbor["rows"]:
            found.append(neighbor)
        else:
            empty.append(neighbor["town"])
    return found, empty, missing


def _neighbor_details(found: List[dict], empty: List[str], missing: List[str]) -> List[str]:
    lines = []
    for neighbor in found:
        lines.append(f"隣の町丁（{neighbor['town']}）にも記録があります：" + "、".join(f"{date} {cause} {kind}" for date, cause, kind in neighbor["rows"]))
    for town in empty:
        lines.append(f"隣の町丁（{town}）の記録は見当たりません。記録がないことは、浸水がなかったことを示すものではありません。")
    for town in missing:
        lines.append(f"隣の町丁（{town}）：手元の表に未収録 → 管理会社から市区町村へ照会")
    return lines


def _neighbor_confirm(missing: List[str]) -> str:
    return f"隣の町丁（{'・'.join(missing)}）の記録は、管理会社から市区町村へ照会します。" if missing else ""


def _record_row(record: Optional[dict]) -> Row:
    if record is None:
        return Row(
            "record",
            "市の浸水の記録",
            UNCONFIRMED,
            "この町丁の記録は、まだ手元の表に入れていません。",
            ["推測では埋めません。手元の表に入れているのはデモの町丁の分だけです。"],
            _RECORD_CONFIRM,
            summary="手元の表に未収録",
            confirm_short="管理会社から市区町村へ照会",
            value="未収録",
            conclusion="管理会社から市区町村へ照会します",
        )
    rows = record["rows"]
    source = f"出典：{record['source']}（読み取った事実を加工して作成）"
    found, empty, missing = _neighbor_parts(record)
    if not rows and found:
        towns = "・".join(n["town"] for n in found)
        details = [record["caution"], *_neighbor_details(found, empty, missing), source]
        return Row(
            "record", "市の浸水の記録", RISK,
            f"同じ町丁の記録は見当たりませんが、隣の町丁（{towns}）に浸水の記録があります。",
            details, (record["confirm_by"] + _neighbor_confirm(missing)),
            summary=f"隣の町丁（{towns}）に記録あり", confirm_short="深さは管理会社が確かめる",
            value="隣に記録", conclusion="隣の町丁に浸水の記録あり",
        )
    if not rows:
        return Row(
            "record",
            "市の浸水の記録",
            UNCONFIRMED,
            "同じ町丁の記録は見当たりません。記録がないことは、浸水がなかったことを示すものではありません。",
            [record["caution"], *_neighbor_details(found, empty, missing), source],
            _RECORD_CONFIRM,
            summary="同じ町丁の記録は見当たらず",
            confirm_short="管理会社から市区町村へ照会",
            value="記録なし",
            conclusion="記録がないことは、浸水がなかったことを示しません",
        )
    dates = len({date for date, _, _ in rows})
    amount = f"{len(rows)}行、日付は{dates}つ" if len(rows) > 1 else "1行"
    headline = f"同じ丁目に浸水の記録があります（{amount}）。"
    lines = [f"{date}　{cause}　{kind}" for date, cause, kind in rows]
    details = [record["note"]] if record["note"] else []
    neighbor_lines = _neighbor_details(found, empty, missing)
    details.extend([record["caution"], *(neighbor_lines or ["隣の町丁の記録は、まだ照らし合わせていません。"]), source])
    return Row(
        "record", "市の浸水の記録", RISK, headline, details, record["confirm_by"] + _neighbor_confirm(missing), records=lines,
        summary=f"同じ丁目に記録あり（{amount}）", confirm_short="深さは管理会社が確かめる",
        value=f"記録{len(rows)}行", conclusion="同じ丁目に浸水の記録あり",
    )


def _rain_lines(reading: dict) -> List[dict]:
    """線状降水帯で浸かる型に、この場所の事実が当たるか。name・text（数値つき）・hit（True／False／None＝データなし）。"""
    names = _landform_names(reading.get("landforms") or [])
    low_names = [name for name in names if _RAIN_LOW_LANDFORM.search(name)]
    missing = any(lf.get("status") in _LANDFORM_MISSING for lf in reading.get("landforms") or [])
    if low_names:
        landform = {"name": "土地の成り立ち", "text": "・".join(low_names), "hit": True}
    elif names:
        landform = {"name": "土地の成り立ち", "text": "・".join(names), "hit": False}
    else:
        landform = {"name": "土地の成り立ち", "text": "データなし", "hit": None if missing else False}
    points = (reading.get("elevation") or {}).get("points") or []
    center = points[0]["elevation_m"] if points else None
    around = [pt for pt in points[1:] if pt.get("elevation_m") is not None]
    if center is None or len(around) < 4:
        ground = {"name": "土地の高さ", "text": "標高のデータなし", "hit": None}
    else:
        order = {"west": 0, "east": 1, "north": 2, "south": 3}
        around.sort(key=lambda pt: order.get(pt.get("key"), 9))
        numbers = " ".join(f"{pt['label']}{pt['elevation_m']}" for pt in around)
        low = reading.get("low_directions") or []
        basin = bool(reading.get("basin"))
        shape = "周囲50mに低い向きなし（くぼ地の型）" if basin else f"{'・'.join(low)}が低い" if low else "周囲とほぼ同じ高さ"
        ground = {"name": "土地の高さ", "text": f"標高{center}m、{shape}。{numbers}", "hit": basin}
    inland = next((h for h in reading.get("hazards") or [] if h.get("key") == "inland"), None)
    if inland is not None and inland.get("status") == "color":
        inland_line = {"name": "内水の地図", "text": f"色あり（{inland.get('legend') or ''}）", "hit": True}
    elif inland is not None and inland.get("status") == "no_color":
        inland_line = {"name": "内水の地図", "text": "色なし", "hit": False}
    elif inland is not None and _is_outside(inland):
        inland_line = {"name": "内水の地図", "text": f"{_outside_text(inland)}。市の内水の図で確認", "hit": None}
    elif inland is None or inland.get("status") == "no_tile":
        inland_line = {"name": "内水の地図", "text": INLAND_NO_DATA_SHORT, "hit": None}
    else:
        inland_line = {"name": "内水の地図", "text": f"{VALUE_FAILED}（{FAILED_NEXT}）", "hit": None}
    return [landform, ground, inland_line]


def _rain_hits(reading: dict) -> bool:
    return any(line["hit"] for line in _rain_lines(reading))


def _rainband_row(reading: dict) -> Row:
    """線状降水帯の大雨で、洪水の地図に色がなくても浸かる型（低い土地・くぼ地・内水の色）に当たるか。規則で判定し、根拠は実数と出典。"""
    lines = _rain_lines(reading)
    hits = [line for line in lines if line["hit"]]
    unknown = [line for line in lines if line["hit"] is None]
    details = [f"{line['name']}：{line['text']}" for line in lines]
    details += [RAIN_FACT, RAIN_FACT_INLAND, RAIN_SOURCE, ELEVATION_SOURCE, *ELEVATION_SOURCE_MORE, HAZARD_SOURCE, HAZARD_PROCESSED]
    if hits:
        what = "・".join(line["name"] for line in hits)
        verdict = RISK
        headline = f"線状降水帯の大雨で、洪水の地図に色がなくても浸かった型（{what}）に当たります。"
        value = "・".join(line["text"].split("、")[0].split("。")[0] for line in hits)
        conclusion = f"型に当たる（{what}）"
    elif unknown:
        verdict = UNCONFIRMED
        headline = "線状降水帯で浸かる型には今の根拠では当たりませんが、確かめられていない項目があります。"
        value = "一部が未確認"
        conclusion = f"確かめられていない項目（{'・'.join(line['name'] for line in unknown)}）"
    else:
        verdict = CLEAR
        headline = "線状降水帯で浸かった型（低い土地・くぼ地・内水の色）のどれにも、今の根拠では当たりません。"
        value = "型に当たらず"
        conclusion = "型に当たらず"
    return Row("rainband", "線状降水帯の大雨（洪水の地図の外で浸かる型）", verdict, headline, details,
               "管理会社が市区町村の内水ハザードマップと浸水履歴で" if verdict == UNCONFIRMED else None,
               summary=conclusion, confirm_short="管理会社が市の内水の図で" if verdict == UNCONFIRMED else None,
               value=value, conclusion=conclusion, accent={"lines": lines, "fact": RAIN_FACT, "fact_inland": RAIN_FACT_INLAND, "source_url": RAIN_SOURCE_URL, "source": "ウェザーニューズ 2026/9/22"})


def _all_clear(reading: dict, record: Optional[dict], basis: str) -> bool:
    """一つの層だけでは問題なしにしない。項目がそろったときだけ、全部を問題なしにする（記録の行は、あるときだけ見る）。"""
    return (
        all(_is_mapped(hazard) and not hazard.get("nearby_legend") and not _is_inland_outside(hazard) for hazard in reading["hazards"])
        and (_nearest_zone_m(reading["hazards"]) is None or _nearest_zone_m(reading["hazards"]) > NEAR_ZONE_M)
        and _ground_clean(reading)
        and not _rain_hits(reading)
        and (
            record is None
            or (not record["rows"] and not any(neighbor.get("rows") is None or neighbor["rows"] for neighbor in record.get("neighbors") or []))
        )
    )


def judge_location(reading: dict, basis: str, record: Optional[dict]) -> List[Row]:
    by_key = {hazard["key"]: hazard for hazard in reading["hazards"]}
    rows = [
        _hazard_row(
            "flood",
            "川があふれる場合（洪水）",
            "川があふれる場合",
            [by_key["flood_planned"], by_key["flood_max"]],
            basis,
            _FLOOD_CONFIRM,
            [],
            "管理会社が市の洪水の図で",
        ),
        _hazard_row(
            "inland",
            "大雨で下水や水路があふれる場合（内水）",
            "大雨で下水や水路があふれる場合",
            [by_key["inland"]],
            basis,
            _INLAND_CONFIRM,
            [
                "この地図は地面の高さが基準で、色がなくても地下の部屋には水が入ることがあります。",
                "国の地図に載るのは、オープンデータの利用を認めた市町村の分だけです。",
            ],
            "管理会社が市区町村に照会",
        ),
        _hazard_row(
            "surge",
            "高潮",
            "高潮",
            [by_key["storm_surge"]],
            basis,
            _SURGE_CONFIRM,
            ["どんな条件の高潮を想定した色かは、地図の案内に書かれていません。"],
            "管理会社が県・市の高潮の図で",
        ),
    ]
    # 津波（2026-11-11：全国で使うために判定に入れた。高潮と同じ作り）。古い保存データには津波の層がないので、あるときだけ行を出す。
    if "tsunami" in by_key:
        rows.append(
            _hazard_row(
                "tsunami",
                "津波",
                "津波",
                [by_key["tsunami"]],
                basis,
                _TSUNAMI_CONFIRM,
                ["どんな地震の津波を想定した色かは、地図の案内に書かれていません。県の津波浸水想定で確かめます。"],
                "管理会社が県・市の津波の図で",
            )
        )
    rows += [
        _ground_row(reading, basis),
        _landform_row(reading),
        _rainband_row(reading),
    ]
    # 浸水の記録の行は、手元に記録がある町丁（見本）だけ。ない住所に「未収録」と出しても参考にならない（2026-11-06 本人の指示）。
    if record is not None:
        rows.append(_record_row(record))
    if _all_clear(reading, record, basis):
        for row in rows:
            row.verdict = CLEAR
            row.verdict_label = "問題なし"
            row.confirm_by = None
            row.confirm_short = None
            row.details.append("どの項目にも当たらなかったので、問題なしとしています。現地は見ていません。")
    return rows
