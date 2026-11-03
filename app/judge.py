"""読み取った立地の値を、三分類の行にする。

分からないことを危険とは言わない。未確認には、誰が確かめれば確定するかを添える。
地図の値を確定にできるのは建物の位置で読めたときだけで、町丁の代表点では未確認のままにする。
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
}

HAZARD_SOURCE = "出典：「ハザードマップポータルサイト」を加工して作成"
ELEVATION_SOURCE = "出典：国土地理院 標高API、地形分類（提供実験）を加工して作成"
# 別紙の出典の欄に、二文に分けて添える。上の文は変えない。
ELEVATION_SOURCE_MORE = [
    "出典：国土地理院ウェブサイト（https://www.gsi.go.jp/bousaichiri/lfc_index.html、標高 API）",
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
_INLAND_CONFIRM = (
    "管理会社が市区町村に、大雨で下水や水路があふれる場合の浸水想定区域図があるか、"
    "あればこの住所に色があるかを確かめます。"
)
_SURGE_CONFIRM = (
    "管理会社が、県の高潮浸水想定区域図か市の高潮ハザードマップで、"
    "建物の位置の想定の深さと、その想定の条件を確かめます。"
)
_GROUND_CONFIRM = "管理会社が、自治体の浸水履歴と内水の想定、管理員の記録で、敷地のまわりが冠水したことがあるかを確かめます。"
_RECORD_CONFIRM = "管理会社から市区町村の窓口へ、この町丁と隣の町丁で過去に浸水や道路冠水の記録があるかを問い合わせます。"


def _place(basis: str) -> str:
    return "町丁の代表点" if basis == REPRESENTATIVE else "ピンの位置"


def basis_note(basis: str) -> str:
    """どの点で読んだ値かの一文。全部の行に当たるので、行ごとには持たない。"""
    return _REPRESENTATIVE_NOTE if basis == REPRESENTATIVE else _BUILDING_NOTE


def _status_text(hazard: dict) -> str:
    status = hazard["status"]
    if status == "color":
        return f"凡例の「{hazard['legend']}」の色"
    if status == "no_color":
        if hazard.get("nearby_legend"):
            return f"色がない（すぐ近く（数m先）に「{hazard['nearby_legend']}」の色）"
        return "色がない"
    if status == "no_tile":
        return "地図のデータが取れていない"
    if status == "unknown_color":
        return "凡例にない色で、読み取れていない"
    return "地図のデータが取れていない（接続できず）"


def _short_status(hazard: dict) -> str:
    status = hazard["status"]
    if status == "color":
        return f"色あり（{hazard['legend']}）"
    if status == "no_color":
        return f"色なし（数m先に{hazard['nearby_legend']}）" if hazard.get("nearby_legend") else "色なし"
    if status == "unknown_color":
        return "読み取れず"
    return "データが取れず"


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
    if any(h["status"] == "no_color" for h in hazards):
        return "一部データなし", "色があるかどうかを確かめます", None
    return "データなし", "色があるかどうかも分かりません", None


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
    else:
        headline = f"{place}では、{what}の地図のデータが取れておらず、色があるかどうかも分かりません。"

    verdict = RISK if colored and basis == BUILDING else UNCONFIRMED
    details = [f"{h['label']}：{_status_text(h)}" for h in hazards]
    if colored and _legend_band(_deepest([h["legend"] for h in colored])) == "shallow":
        details.append(BAND_SHALLOW_NOTE)
    details.extend(extra)
    details.append(HAZARD_SOURCE)
    open_item = verdict != RISK
    value, conclusion, accent = _hazard_face(hazards)
    return Row(
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
            names.append(name or f"分類番号 {code}")
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
    conclusion = "標高のデータが一部取れていません"
    badges = []
    if center is None or None in around:
        headline = f"{place}と周囲の標高のデータが、一部取れていません。"
        details.append("標高が取れないので、くぼ地の目安を当てられません。")
    else:
        shape = _ground_shape(center, around)
        value = f"標高{center}m"
        if shape == "depression":
            headline = f"{place}の標高は{center}mで、周囲より低く、水がたまるくぼ地の仮の目安に当たります。"
            summary = f"標高{center}m。くぼ地の仮の目安に当たる"
            conclusion = "くぼ地の仮の目安に当たる"
            badges.append("くぼ地の目安")
            details.append("くぼ地では、地表から入る水だけでなく、建物の排水口や雨水ますから水が上がってくる経路もありえます。起きるかどうかは判定していません。")
        elif shape == "flat_low":
            headline = f"{place}の標高は{center}mで、低く平らな土地の仮の目安に当たります。"
            summary = f"標高{center}m。低く平らな土地の仮の目安に当たる"
            conclusion = "低く平らな土地の仮の目安に当たる"
            badges.append("低く平らな土地の目安")
            details.append("水の逃げ場がなく、放流先の海や川の水位が高いと排水できなくなることがあります。")
        else:
            headline = f"{place}の標高は{center}mで、くぼ地や低く平らな土地の仮の目安には当たりません。"
            summary = f"標高{center}m。くぼ地の仮の目安に当たらず"
            conclusion = "くぼ地の仮の目安に当たらず"
        if reading.get("basin"):
            high = "・".join(reading.get("high_directions") or [])
            summary = f"{summary}。周囲（{high}）より低い形"
            conclusion = f"周囲（{high}）より低い形"
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
    return Row(
        "ground", "敷地の高低差", UNCONFIRMED, headline, details, _GROUND_CONFIRM,
        summary=summary, confirm_short="管理会社が履歴と管理員の記録で",
        value=value, conclusion=conclusion,
        accent={"kind": "terrain", "level": "mid", "badges": badges} if badges else None,
    )


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


def _all_clear(reading: dict, record: Optional[dict], basis: str) -> bool:
    """一つの層だけでは問題なしにしない。五つの項目がそろったときだけ問題なしにする。"""
    return (
        basis == BUILDING
        and all(hazard["status"] == "no_color" and not hazard.get("nearby_legend") for hazard in reading["hazards"])
        and _ground_clean(reading)
        and record is not None
        and not record["rows"]
        and not any(neighbor.get("rows") is None or neighbor["rows"] for neighbor in record.get("neighbors") or [])
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
        _ground_row(reading, basis),
        _record_row(record),
    ]
    if _all_clear(reading, record, basis):
        for row in rows:
            row.verdict = CLEAR
            row.verdict_label = "問題なし"
            row.confirm_by = None
            row.confirm_short = None
            row.details.append("五つの項目がそろって当たらなかったので問題なしとしています。現地を確かめたものではありません。")
    return rows
