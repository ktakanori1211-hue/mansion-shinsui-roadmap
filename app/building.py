"""見本の建物の設備を判定し、最上段の一行、処置、依頼メモ、水の位置ごとの想定を作る。

判定はここのルールだけで決める。Claude には書き換えさせない。
日数を建物ごとに計算しない。固定の cm の数字を置かない。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

from . import samples
from .state import DRAWING, DOCUMENT, QUESTION, RISK, UNCONFIRMED, Equipment

# 画面に出す固定の文。言い換えず、折りたたまない。
FIXED = {
    "disclaimer_1": "本シートは公開データと入力情報から作成したもので、現地の判定や安全を保証するものではない。浸水中は電気室・借室（東京電力の変圧器の部屋）・ポンプ室・EVピットに立ち入らず、復電の可否は電気主任技術者が判断する",
    "model": "説明用の模型で、部屋の位置と高さはあなたの建物のものではありません。",
    "ordinary": "ふだんも、主任技術者の同行なしに電気室に入りません。東京電力の変圧器の部屋には、東京電力パワーグリッドの許可と立会いなしにだれも入りません。",
    "ordinary_no_engineer": "ふだんも、電気工事の業者の立会いなしに、共用部のおおもとのスイッチ盤の部屋に入りません。東京電力の変圧器の部屋には、東京電力パワーグリッドの許可と立会いなしにだれも入りません。",
    "tank_outside": "雨水ますから貯留タンクへの経路は、この切り替えに含めていません。",
    "disclaimer_1_no_engineer": "本シートは公開データと入力情報から作成したもので、現地の判定や安全を保証するものではない。浸水中は電気室・借室（東京電力の変圧器の部屋）・ポンプ室・EVピットに立ち入らず、復電の可否は電気主任技術者が判断する（電気主任技術者を選任していない建物では、電気工事の業者の点検と測定の結果を見て管理組合が判断し、東京電力パワーグリッドに連絡する）",
    "water_not_entry": "水の位置は、立ち入ってよい高さではありません。水が残る部屋には、深さにかかわらず入りません。水が引いても、主任技術者（いない建物では電気工事業者）が安全を確かめ、入ってよいと指示するまで、住民、理事、管理員は入りません。",
    "timeline_top": "目安はほかの建物の実例と一般的な目安で、この建物の日数ではありません",
    "gone": "この位置では、この目安のもとになった設備（制御盤／受電の箱）は浸からない想定です。ポンプ本体やエレベーターなど、ほかの設備が浸かったときに戻るまでの期間は確かめていません",
    "nothing_wet": "この位置で浸かる設備はない想定です。戻るまでの期間の目安は出しません",
    "tr_outside": "東京電力の変圧器の部屋（借室）は、対策の切り替えに含めていません（東京電力パワーグリッドに確かめる）",
    "tr_box": "この切り替えに含めていません（東京電力パワーグリッドに確かめる）",
    "hole": "壁の穴を塞いだのは、この図の入り道一つだけです。ほかの入り道は現地調査で確かめます",
    "raise": "付け替えた制御盤は、この図では浸からない想定で描いています。付け替える高さは見積りと現地調査で決めるもので、実際にどの高さの水まで浸からずに済むかは、この図では示していません。付け替えたのは制御盤だけで、ほかの設備の高さは変わりません。",
    "chain": "遮断や引込みの停止をすると、塗っていない箱も止まります。塗っていない箱も、浸かった部分があれば点検が要ります",
    "no_stop": "この位置と対策では、図の入り道から止まる設備はない想定",
    "tr_inside": "中は建物側から分からない",
}

WATER_LEVELS = [
    {"key": 1, "label": "①", "text": "前の道路・スロープ・地下の壁の穴に達した"},
    {"key": 2, "label": "②", "text": "一番低い床（エレベーターの底の部分、床置きの機器の下端）に達した"},
    {"key": 3, "label": "③", "text": "壁掛けや架台の上の盤、受電の箱、東京電力の変圧器の部屋の下端に達した"},
]

ACTIONS_MORNING = "電気室などに水が残っていたら、電気室・借室・ポンプ室・EV ピットに立ち入りません。東京電力パワーグリッドが電気を切り離し、主任技術者が、水に触れずに近づけて安全と判断したときに、マンション側の受電の箱の、電気の入口側で最初のスイッチを切ります。管理員か理事長は、その二つを主任技術者に確かめてから排水を始めます。マンション側の電気を戻すかは、点検と電気の安全確認のあとで主任技術者が判断します。東京電力の設備の送電の再開は東京電力パワーグリッドが行います"
ACTIONS_MORNING_NO_ENGINEER = "部屋などに水が残っていたら、東京電力の変圧器の部屋・盤の部屋・ポンプ室・エレベーターの底の部分に立ち入りません。管理員か理事長は、東京電力パワーグリッドに電話で切り離しを確かめます。盤の部屋を見に行って確かめません。電気工事の業者に電気が切れていて排水を始めてよいと確かめたうえで、管理組合が排水を始めます。マンション側の盤に電気を戻すかは、点検のあとで電気工事の業者と決めます。東京電力の設備の送電の再開は東京電力パワーグリッドが行います"
ACTIONS_DAY = "管理員か理事長が主任技術者に連絡します。遮断するかは主任技術者が判断し、操作は主任技術者の指示で、電気室の外から、または水に触れずにできるときだけ行います。扉を開けて中に入って操作しません。外から切れないときは電気室に入らず、主任技術者と東京電力パワーグリッドに連絡し、引込みの停止を頼みます。遮断は、在宅で医療機器を使う住民への配慮と、全戸の排水禁止の連絡とあわせて行います。浸水中は電気室・借室・ポンプ室・EV ピットに立ち入りません"
ACTIONS_DAY_NO_ENGINEER = "管理員か理事長が東京電力パワーグリッドと管理会社に連絡します。この建物に主任技術者はいません。盤の部屋に入って電気を切りません。在宅で医療機器を使う住民への配慮と、全戸の排水禁止の連絡をあわせて行います。浸水中は東京電力の変圧器の部屋・盤の部屋・ポンプ室・エレベーターの底の部分に立ち入りません"
ACTIONS_BEFORE = "警戒レベル3で車を上へ、レベル4で止水板と土のうを出します。合図は自治体や気象庁が出す警戒レベルです"


ACTIONS_DAY_UNSURE = "管理員か理事長が、東京電力パワーグリッドと管理会社と、いれば主任技術者に連絡します。電気の部屋に入って電気を切りません。扉を開けて中に入って操作しません。在宅で医療機器を使う住民への配慮と、全戸の排水禁止の連絡をあわせて行います。浸水中は電気の部屋・東京電力の変圧器の部屋・ポンプ室・エレベーターの底の部分に立ち入りません"
ACTIONS_MORNING_UNSURE = "部屋などに水が残っていたら、電気の部屋・東京電力の変圧器の部屋・ポンプ室・エレベーターの底の部分に立ち入りません。管理員か理事長は、東京電力パワーグリッドの切り離しと、主任技術者（いない建物では電気工事の業者）の確認を確かめてから排水を始めます。電気を戻すかは、点検のあとで主任技術者（いない建物では電気工事の業者）と決めます。東京電力の設備の送電の再開は東京電力パワーグリッドが行います"


def actions_for(sample: dict) -> tuple:
    """当日と翌朝の文。主任技術者の有無が書類で分かっていないときは、有無を決めつけない。"""
    if sample.get("engineer_unsure"):
        return ACTIONS_DAY_UNSURE, ACTIONS_MORNING_UNSURE
    if sample["has_chief_engineer"]:
        return ACTIONS_DAY, ACTIONS_MORNING
    return ACTIONS_DAY_NO_ENGINEER, ACTIONS_MORNING_NO_ENGINEER


def rooms_in_basement(sample: dict) -> Optional[bool]:
    """電気と水の部屋が地下か。分からないときは None で、地下と決めつけない。"""
    answers = sample.get("answers") or {}
    floor = answers.get("rooms_floor")
    if floor == "basement":
        return True
    if floor == "ground":
        return False
    if floor == "unknown":
        return None
    return sample["archetype"] in ("basement", "tower")


def _room_on_floor(sample: dict, key: str) -> Optional[str]:
    for index, view in enumerate(sample["views"]):
        if any(room["key"] == key for room in view["rooms"]):
            return view["name"].replace("平面図", "")
    return None


def _item(key, label, verdict, headline, summary, confirm_by, confirm_short, memo, **extra) -> dict:
    item = Equipment(
        key=key,
        label=label,
        verdict=verdict,
        headline=headline,
        confirm_by=confirm_by if verdict != RISK or extra.get("always_confirm") else None,
        memo_section=memo,
        floor=extra.get("floor"),
        evidence=extra.get("evidence"),
        confirmed_by_person=extra.get("confirmed", False),
        details=extra.get("details", []),
    )
    data = asdict(item)
    data["summary"] = summary
    data["confirm_short"] = confirm_short if data["confirm_by"] else None
    return data


def judge_equipment(sample: dict, confirmed: List[str], location_risk: bool, document_read: bool = False) -> List[dict]:
    """confirmed は、図面の読み取りのあとで人が確かめた部屋の種類。

    document_read は、点検報告書などの書類で受電の箱が地下にあると読めたこと。
    """
    rows = []
    answers = sample.get("answers") or {}
    in_basement_known = rooms_in_basement(sample)
    place_word = {True: "地下", False: "1階", None: "階が未確認"}[in_basement_known]
    unsure = sample.get("engineer_unsure")
    drawing = lambda key: key in confirmed  # noqa: E731
    evidence = lambda key, fallback: DRAWING if drawing(key) else fallback  # noqa: E731
    mount = sample["panel_mount"]

    rows.append(
        _item(
            "water",
            "水（全戸）",
            UNCONFIRMED,
            f"ポンプのスイッチ盤の場所（{place_word}）と高さが確かめられていません（盤の形：{mount}）。盤の下の端より水が上がると、ポンプが止まり全戸断水につながります。" + ("床に近い位置にある盤は、浅い浸水でも浸かるおそれがあると考えられます。" if mount == "床置き" else ""),
            f"ポンプの部屋（{place_word}）の盤（{mount}）。高さは未確認",
            "管理会社が、給水ポンプの保守業者に、スイッチ盤の下の端の高さと部屋の床の高さを測ってもらいます。",
            "管理会社→ポンプの保守業者",
            3,
            floor=_room_on_floor(sample, "pump") if in_basement_known is not None else None,
            evidence=evidence("pump", DOCUMENT if not sample.get("custom") else QUESTION),
            confirmed=drawing("pump"),
        )
    )

    if unsure:
        rows.append(
            _item(
                "power",
                "電気（共用部）",
                UNCONFIRMED,
                "マンション側で電気を受ける部屋があるか、主任技術者がいるかが、書類で確かめられていません。受電の箱か、おおもとのスイッチ盤が浸かると、共用部が停電し、給水ポンプも止まって断水します。",
                "受電の部屋と主任技術者の有無が未確認",
                "管理会社が、点検報告書か保安規程、竣工図、共用部の電気代の明細で確かめます。",
                "管理会社（書類）",
                1,
                evidence=QUESTION,
            )
        )
    elif sample["has_chief_engineer"]:
        # 書類か図面で地下と分かり、立地のリスクが確定していれば確定にする。確定するのは水が来ることまで。
        known = (document_read or drawing("elec")) and in_basement_known is True
        verdict = RISK if known and location_risk else UNCONFIRMED
        source = "図面で確かめました" if drawing("elec") else "書類で読めました" if document_read else "聞いていますが、書類や図面ではまだ確かめていません"
        where = f"{place_word}にあると{source}" if in_basement_known is not None else "どの階にあるか確かめられていません"
        rows.append(
            _item(
                "power",
                "電気（共用部）",
                verdict,
                f"エレベーター、給水ポンプ、廊下の照明の電気を受ける箱は、{where}。浸かると共用部が停電し、給水ポンプも止まって断水します。",
                f"受電の箱は{place_word}。浸かると共用部が停電し断水も" if known else f"受電の箱の階（{place_word}）は書類で未確認",
                "床からの盤や箱の高さは未確認なので、依頼メモで確かめます。盤の下の端は主任技術者が月次点検の立会いで測ります。",
                "管理会社、主任技術者（高さ）",
                1,
                floor=_room_on_floor(sample, "elec") if in_basement_known is not None else None,
                evidence=DRAWING if drawing("elec") else DOCUMENT if document_read else QUESTION,
                confirmed=drawing("elec"),
                always_confirm=True,
                details=["確定とするのは立地で水が来ることまでで、床からの盤や箱の高さは別に確かめます。"] if verdict == RISK else [],
            )
        )
    else:
        rows.append(
            _item(
                "power",
                "電気（共用部のおおもとのスイッチ盤）",
                UNCONFIRMED,
                f"共用部の電気は、{place_word}の盤の部屋から来ています。床が通路より少し高いだけなら、浅い水でも盤の下の端に届くことがあります。",
                f"{place_word}の盤の部屋。下の端の高さは未確認",
                "管理会社から電気工事の業者に、盤の下の端の高さを測ってもらいます。",
                "管理会社→電気工事の業者",
                2,
                floor=_room_on_floor(sample, "panel_room"),
                evidence=evidence("panel_room", DOCUMENT),
                confirmed=drawing("panel_room"),
            )
        )

    if answers.get("tr") == "no":
        rows.append(
            _item(
                "tr",
                "各戸の電気（東京電力の設備の位置）",
                UNCONFIRMED,
                "東京電力の変圧器だけの部屋はないとの答えですが、図面で確かめるまで「なし」とはしません。" + ("各戸の電気がマンション側の受電設備から来るか、東京電力から直接来るかも分かっていません。" if answers.get("hv") == "yes" else "各戸へ電気を送る東京電力の設備がどこにあるかも分かっていません。"),
                "部屋はないとの答え。図面と設備の位置は未確認",
                "管理会社が竣工図と単線結線図で確かめ、各戸へ電気を送る設備の種類と位置を東京電力パワーグリッドに照会します。",
                "管理会社→東京電力PG",
                1,
                evidence=QUESTION,
            )
        )
        tr_handled = True
    elif answers.get("tr") == "unknown":
        rows.append(
            _item(
                "tr",
                "各戸の電気（東京電力の変圧器の部屋）",
                UNCONFIRMED,
                "東京電力の変圧器の部屋があるかどうかが分かっていません。あれば、そこが浸かると各戸の電気が止まります。",
                "部屋があるか未確認",
                "管理会社が竣工図の電気設備図と共用部の電気代の明細で、部屋の有無と階を確かめます。",
                "管理会社（竣工図）",
                1,
            )
        )
        tr_handled = True
    else:
        tr_handled = False
    if not tr_handled:
        tr_floor = _room_on_floor(sample, "tr")
        in_basement = tr_floor and "地下" in tr_floor
        tr_risk = in_basement and drawing("tr") and location_risk
        scope = "各戸と共用部の両方の電気" if not sample["has_chief_engineer"] else "各戸の電気"
        place = "地下" if in_basement else "1階"
        if sample.get("custom") and in_basement_known is None:
            place = "階が未確認の場所"
        rows.append(
            _item(
                "tr",
                "各戸の電気（東京電力の変圧器の部屋）",
                RISK if tr_risk else UNCONFIRMED,
                f"東京電力の変圧器の部屋は{place}にあると{'図面で確かめました' if drawing('tr') else ('聞いていますが、図面ではまだ確かめていません' if sample['id'] == 'a' else '見込まれますが、図面ではまだ確かめていません')}。浸かると{scope}が止まります。部屋の中の機器の高さは建物の側から分かりません。",
                f"{place}。浸かると{scope}が止まる{'（図面で確認）' if drawing('tr') else '（図面は未確認）'}",
                "管理会社が竣工図で部屋の有無と階を確かめ、部屋の中と穴・扉の分担は管理会社から東京電力パワーグリッドに問い合わせます。",
                "管理会社→東京電力PG",
                1,
                always_confirm=True,
                floor=tr_floor,
                evidence=evidence("tr", QUESTION),
                confirmed=drawing("tr"),
                details=["確定するのは部屋まで水が来るおそれがあることまでです。"] if tr_risk else [],
            )
        )

    built = sample.get("built")
    before_guideline = ""
    if built and built <= 2019:
        before_guideline = f"{built}年築で、2020年6月の国のガイドラインより前の建物なので、ケーブルを通す壁の穴の止水処理は要確認です。"
    elif built == 2020:
        before_guideline = "2020年築で、2020年6月の国のガイドラインの前か後かは築年だけでは決まりません。壁の穴の止水処理を確かめます。"
    if sample.get("feed_unknown"):
        rows.append(
            _item(
                "entry",
                "水の入り道（壁や床の穴）",
                UNCONFIRMED,
                "電気の引込みが地中か空中かが書類で分かっていません。マンション側の部屋のケーブルを通す穴と、給排水管などが通る穴の止水を確かめます。東京電力の変圧器の部屋の穴は、この行に含めません。" + before_guideline,
                "引込みの形と穴の止水が未確認",
                "管理会社が単線結線図で引込みの形を確かめ、防水・設備業者へ現地調査を依頼します。",
                "管理会社→防水・設備業者",
                2,
            )
        )
    elif sample["underground_feed"]:
        rows.append(
            _item(
                "entry",
                "水の入り道（ケーブルを通す壁の穴）",
                UNCONFIRMED,
                "マンション側の電気の部屋のケーブルを通す壁の穴が止水されているか分かっていません。東京電力の変圧器の部屋の穴は、この行に含めません。" + before_guideline,
                "マンション側の壁の穴の止水が未確認",
                "管理会社から防水・設備業者へ現地調査を依頼します（部屋の中の確認は電気の月次点検の立会いに合わせます）。",
                "管理会社→防水・設備業者",
                2,
            )
        )
    else:
        rows.append(
            _item(
                "entry",
                "水の入り道（壁や床の穴、坂の下の側の扉）",
                UNCONFIRMED,
                "受電の電線は空中から入りますが、給排水管などが壁や床を通る穴と、坂の下の側の扉と足元の換気口が入り道の候補です。",
                "配管の穴、扉の下、足元の換気口が未確認",
                "管理会社から防水・設備業者へ現地調査を依頼します（盤の部屋では電気工事の業者が立ち会い、防水業者は目で見るだけです）。",
                "管理会社→防水・設備業者",
                2,
            )
        )

    outside = []
    if answers.get("slope") == "yes":
        outside.append("地下へ降りるスロープか半地下の駐輪場")
    if answers.get("vent") == "yes":
        outside.append("1階の足元の換気口")
    if answers.get("door_step") == "no":
        outside.append("段差のない電気の部屋の扉")
    if outside:
        rows.append(
            _item(
                "outside",
                "外から見える入口",
                UNCONFIRMED,
                "、".join(outside) + "があるとの答えです。道路の水がここから入ることがあります。",
                "、".join(outside),
                "管理会社が外から見える所を見て、部屋の中は竣工図で、入口の高さと止水板を置けるかを確かめます。冠水中は近づきません。",
                "管理会社（外から）",
                1,
                evidence=QUESTION,
            )
        )
    if sample["id"] == "a" and not sample.get("custom"):
        rows.append(
            _item(
                "damp",
                "地下の電気の部屋の床の湿気（点検で指摘済み）",
                UNCONFIRMED,
                "すでにどこかから水気が入っているサインの可能性があります。",
                "点検で湿気の指摘あり",
                "管理会社から建物・防水の業者へ現地調査を依頼します。",
                "管理会社→防水の業者",
                2,
                evidence=DOCUMENT,
            )
        )
    if sample["id"] == "c" and not sample.get("custom"):
        rows.append(
            _item(
                "tank",
                "雨水ますから地下の貯留タンク",
                UNCONFIRMED,
                "敷地の水が雨水ますからタンクへ流れ込み、満水になると地下の蓋からあふれる経路があります。導入管の止水バルブと蓋のロックが分かっていません。",
                "止水バルブと蓋のロックが未確認",
                "管理会社が竣工図で確かめ、設備業者へ現地調査を依頼します。",
                "管理会社→設備業者",
                2,
                floor=_room_on_floor(sample, "tank"),
                evidence=evidence("tank", DOCUMENT),
                confirmed=drawing("tank"),
            )
        )
        rows.append(
            _item(
                "gen",
                "非常用発電機",
                UNCONFIRMED,
                "火災のときのための設備で、水害の長い停電に足りるとは言えません。地下にあるので、浸かれば使えません。",
                "地下。水害の長い停電に足りるとは言えない",
                "管理会社から設備業者に、部屋の床の高さと燃料の持ち時間を確かめてもらいます。",
                "管理会社→設備業者",
                3,
                floor=_room_on_floor(sample, "gen"),
                evidence=evidence("gen", DOCUMENT),
                confirmed=drawing("gen"),
            )
        )

    rows.append(
        _item(
            "ev",
            "エレベーター",
            UNCONFIRMED,
            "エレベーターの通り道の底に水が入ると止まり、再開には保守会社の点検が要ります（東芝エレベータと三菱電機ビルソリューションズの公式ページの説明）。",
            "底の部分に水が入ると止まる",
            "エレベーターの保守会社に、どの深さで止まり再開に何が要るかを確認します。",
            "エレベーターの保守会社",
            3,
        )
    )
    if in_basement_known is not False:
        rows.append(
            _item(
                "drain",
                "トイレ・排水",
                UNCONFIRMED,
                "汚水を汲み上げるポンプがあるか、どの階にあるかが確かめられていません。止まるとトイレや生活排水が使えなくなり、低い階へ逆流することがあります。",
                "汲み上げポンプの有無と階が未確認",
                "管理会社が竣工図で確かめます。",
                "管理会社（竣工図）",
                1,
            )
        )
    if sample["archetype"] != "ground":
        rows.append(
            _item(
                "park",
                "機械式駐車場",
                UNCONFIRMED,
                "装置の下の掘り込みに水がたまると車が水没します。" if not sample.get("custom") else "機械式駐車場があるか確かめられていません。あれば、装置の下の掘り込みに水がたまると車が水没します。",
                "掘り込みの深さと排水ポンプが未確認",
                "駐車場の保守会社に、掘り込みの深さと排水ポンプの有無を確認します。",
                "駐車場の保守会社",
                3,
            )
        )
    return rows


def top_line(sample: dict, equipment: List[dict], location_rows: List[dict], confirmed: List[str]) -> dict:
    """最上段の一行は、決まった順に当てはめ、最初に当たった書き出しを出す。"""
    location_risk = any(row["verdict"] == "risk" for row in location_rows)
    location_clear = bool(location_rows) and all(row["verdict"] == "clear" for row in location_rows)
    is_basement = rooms_in_basement(sample) is True
    notes = []
    if location_clear or all(item["verdict"] == "clear" for item in equipment):
        lead = "今の情報では、浸水で水が止まるおそれは小さい（または対策済み）。"
    elif any(item["verdict"] == "risk" for item in equipment) or is_basement:
        lead = "このままなら、長引くおそれがある。"
        if not location_risk:
            notes.append("建物の位置まで水が来るかは、まだ確かめていない。管理会社が立地の表の確認先で確かめる。")
        basement_keys = {"elec", "tr", "pump"}
        if not basement_keys.issubset(confirmed):
            notes.append("地下にあるのは書類や聞き取りによるもので、図面ではまだ確かめていない。管理会社が竣工図で確かめる。")
        notes.append("給水・排水のスイッチ盤は製作に約2か月（建築設備技術者協会の報告書）。武蔵小杉は断水8日・トイレ11日（ほかの建物の例）。一番安い手は数万円から。")
    else:
        lead = "まだ分からない。"
        notes.append("どこまで水が来るかと盤の高さが未確認。もし浸かれば制御盤の製作に約2か月（建築設備技術者協会の報告書）など長引くおそれがあるので、まず依頼メモで高さを確かめる。")
    return {"lead": lead, "notes": notes}


def visible_measures(sample: dict, equipment: List[dict]) -> List[dict]:
    tr_risk = any(item["key"] == "tr" and item["verdict"] == RISK for item in equipment)
    keys = {
        "door": sample["archetype"] != "ground",
        "move": sample["has_chief_engineer"],
        "door_rebuild": sample["archetype"] != "ground",
        "tepco": tr_risk,
    }
    rows = []
    for measure in samples.MEASURES:
        if not keys.get(measure["key"], True):
            continue
        row = dict(measure)
        if measure["key"] == "panel" and sample["panel_mount"] != "壁掛け":
            row["label"] = "ポンプのスイッチ盤をさらに高い位置に付け替える（盤の下の端が低いと分かった場合）"
        if measure["key"] == "hole" and not sample["underground_feed"]:
            row["label"] = "盤の部屋の壁や床の穴（給排水管などが通る穴）をふさぐ（施工は電気工事の業者が、停電の要否・離隔を決めてから。理事や管理員は部屋に入らない。東京電力の変圧器の部屋の穴には、だれも栓や止水材を入れない）"
        rows.append(row)
    return rows


def memos(sample: dict, equipment: List[dict], location_rows: List[dict], statements: Optional[List[str]] = None) -> List[dict]:
    """未確認を、確認する先ごとの依頼メモにする。"""
    sections = {
        1: {"key": 1, "label": "①", "title": "管理会社が書類・問い合わせで確かめること", "items": []},
        2: {"key": 2, "label": "②", "title": "管理会社から業者へ（現地調査の見積りと手配）", "items": []},
        3: {"key": 3, "label": "③", "title": "保守会社への照会・測定", "items": []},
    }
    for row in location_rows:
        if row.get("confirm_by"):
            sections[1]["items"].append({"from": row["label"], "text": row["confirm_by"]})
    for item in equipment:
        if item.get("confirm_by") and item.get("memo_section"):
            sections[item["memo_section"]]["items"].append({"from": item["label"], "text": item["confirm_by"]})
    first = sections[1]["items"]
    for statement in statements or []:
        first.append({"from": "聞き取り", "text": f"「{statement}」との話を、管理会社が竣工図で確かめます（図面で確かめるまで未確認です）。"})
    first.append({"from": "決める場", "text": "管理会社が規約・予算書・総会の議事録で、壁の穴の止水と置くだけの止水板を理事会で決められるかを確かめます。"})
    if sample["has_chief_engineer"]:
        first.append({"from": "電気を切る手段", "text": "主任技術者に、単線結線図で受電設備側の最初の開閉器の位置と、電気室に入らずに切れる手段があるかを確かめてもらいます。"})
    else:
        first.append({"from": "受電の形", "text": "管理会社が、共用部の電気代の明細で契約種別が低圧であることと、同じ敷地に発電設備がないことを確かめます。"})
    if sample["underground_feed"]:
        first.append({"from": "地中の高圧ケーブル", "text": "管理会社を通じて電気主任技術者に、高圧ケーブルの敷設年と点検の記録、大雨や浸水のあとに行う確認を聞きます。歩道ぎわの蓋は開けません。"})
    return list(sections.values())


# 停電の連鎖の図の箱とつながり。
def chain_nodes(sample: dict) -> dict:
    result = _chain_nodes(sample)
    if (sample.get("answers") or {}).get("tr") in ("no", "unknown"):
        for node in result["nodes"]:
            if node["key"] == "tr":
                node["label"] = "東京電力の設備（位置は未確認）"
    if sample.get("engineer_unsure"):
        for node in result["nodes"]:
            if node["key"] == "hv":
                node["label"] = "マンション側の受電設備（有無は未確認）"
    return result


def _chain_nodes(sample: dict) -> dict:
    if sample["has_chief_engineer"]:
        nodes = [
            {"key": "line", "label": "外の電線"},
            {"key": "hv", "label": "受電の箱"},
            {"key": "panel", "label": "給水ポンプの制御盤"},
            {"key": "pump", "label": "給水ポンプ（全戸の水）"},
            {"key": "ev", "label": "エレベーター"},
            {"key": "light", "label": "廊下の照明"},
            {"key": "tr", "label": "東京電力の変圧器の部屋"},
            {"key": "homes", "label": "各戸の電気"},
        ]
        edges = [("line", "hv"), ("hv", "panel"), ("panel", "pump"), ("hv", "ev"), ("hv", "light"), ("line", "tr"), ("tr", "homes")]
    else:
        nodes = [
            {"key": "line", "label": "外の電線"},
            {"key": "tr", "label": "東京電力の変圧器の部屋"},
            {"key": "homes", "label": "各戸の電気"},
            {"key": "hv", "label": "共用部のおおもとのスイッチ盤"},
            {"key": "panel", "label": "給水ポンプの制御盤"},
            {"key": "pump", "label": "給水ポンプ（全戸の水）"},
            {"key": "ev", "label": "エレベーター"},
            {"key": "light", "label": "廊下の照明"},
        ]
        edges = [("line", "tr"), ("tr", "homes"), ("tr", "hv"), ("hv", "panel"), ("panel", "pump"), ("hv", "ev"), ("hv", "light")]
    return {"nodes": nodes, "edges": edges}


def measures_for_model(sample: dict) -> List[dict]:
    raised = "制御盤を高い位置に付け替える" if sample["panel_mount"] == "壁掛け" else "制御盤をさらに高い位置に付け替える"
    hole = (
        "マンション側の電気室の、ケーブルを通す壁の穴を塞ぐ（借室の穴は含めない）"
        if sample["underground_feed"]
        else "マンション側の盤の部屋の、壁や床の穴を塞ぐ（借室の穴は含めない）"
    )
    return [
        {"key": "plate", "short": "止水板だけ", "label": "玄関の止水板だけ（地中の壁の穴からの経路は残る）" if sample["underground_feed"] else "玄関の止水板だけ（壁や床の穴からの経路は残る）"},
        {"key": "hole", "short": "壁の穴を塞ぐ" if sample["underground_feed"] else "穴を塞ぐ", "label": hole},
        {"key": "raise", "short": "盤を高くする", "label": raised},
    ]


# 「止まる設備の数」で数えるのは、住民が使えなくなるものだけ。受電の箱や制御盤は止まる原因として別に見せる。
SERVICES = [
    ("pump", "給水（全戸の水）"),
    ("ev", "エレベーター"),
    ("light", "廊下の照明"),
    ("homes", "各戸の電気"),
]


def services(stopped: set) -> List[dict]:
    """各戸の電気は東京電力の設備しだいで、止まらない想定のときも建物側からは分からない。"""
    result = []
    for key, label in SERVICES:
        if key in stopped:
            state = "stopped"
        elif key == "homes":
            state = "unknown"
        else:
            state = "running"
        result.append({"key": key, "label": label, "state": state})
    return result


def scenario(sample: dict, water: int, measure: str) -> dict:
    """水の位置と対策の組合せごとに、浸かる想定、止まる想定、表のマス、固定の文を作る。"""
    answers = sample.get("answers") or {}
    tr_unseen = answers.get("tr") in ("no", "unknown")
    wet = set()
    if water >= 2:
        wet.add("ev")
        if sample["panel_mount"] == "床置き" and measure != "raise":
            wet.add("panel")
    if water >= 3:
        if not tr_unseen:
            wet.add("tr")
        if measure != "hole":
            wet.add("hv")
        if measure != "raise":
            wet.add("panel")

    chain = chain_nodes(sample)
    stopped = set(wet)
    changed = True
    while changed:
        changed = False
        for start, end in chain["edges"]:
            if start in stopped and end not in stopped:
                stopped.add(end)
                changed = True

    notes = [FIXED["timeline_top"]]
    if measure == "hole":
        notes.append(FIXED["hole"])
    if measure == "raise":
        notes.append(FIXED["raise"])
    if sample["archetype"] == "tower":
        notes.append(FIXED["tank_outside"])
    if answers.get("panel_foot") == "unknown":
        notes.append("盤の足元の形が分からないので、水の位置②で盤が浸かるかどうかは未確認です。")
    if tr_unseen:
        notes.append("東京電力の設備の位置は未確認です（東京電力パワーグリッドに確かめる）。")
    below = []
    gone = False

    hv_wet = "hv" in wet
    tr_wet = "tr" in wet
    panel_wet = "panel" in wet
    no_stop = not stopped

    def mark(key):
        return "止まる想定" if key in stopped else "—"

    checker = "主任技術者か電気工事の業者" if sample.get("engineer_unsure") else "主任技術者" if sample["has_chief_engineer"] else "電気工事の業者"
    hv_name = "共用部の電気（受電の箱）" if sample["has_chief_engineer"] else "共用部の電気（おおもとのスイッチ盤）"
    guide_days = "排水開始から仮復旧まで4〜7日程度（受電設備・供給用変圧器が浸かった場合。経産省の検討会資料、一般的な目安）"
    table = [
        {
            "key": "water",
            "label": "水（給水ポンプ）",
            "cells": [
                "—",
                mark("pump"),
                (f"止まる想定のまま、{checker}が確かめるまで戻さない") if "pump" in stopped else "—",
                "—",
                "制御盤の製作に約2か月（給水・排水の制御盤が浸かった場合。建築設備技術者協会の報告書、一般的な目安）" if panel_wet else "目安なし＊",
            ],
            "stopped": "pump" in stopped,
        },
        {
            "key": "ev",
            "label": "エレベーター",
            "cells": ["—", mark("ev"), "再開には保守会社の点検が要る" if "ev" in wet else "—", "—", "—"],
            "stopped": "ev" in stopped,
        },
        {
            "key": "hv",
            "label": hv_name,
            "cells": [
                "—",
                mark("hv"),
                (f"止まる想定のまま、{checker}が確かめるまで戻さない") if "hv" in stopped else "—",
                (guide_days if sample["has_chief_engineer"] else "—") if hv_wet else "目安なし＊",
                ("特注品は復旧に1年以上の場合も（受変電の特注品が浸かった場合。建築設備技術者協会の報告書、一般的な目安）" if sample["has_chief_engineer"] else "—") if hv_wet else "目安なし＊",
            ],
            "stopped": "hv" in stopped,
        },
        {
            "key": "tr",
            "label": "各戸の電気（東京電力の設備の位置は未確認）" if tr_unseen else "各戸の電気（東京電力の変圧器の部屋）",
            "cells": [
                "—",
                mark("tr") if tr_wet else "建物側から分からない",
                "東京電力パワーグリッドが判断" if tr_wet else "—",
                guide_days if tr_wet else "目安なし＊",
                "—",
            ],
            "stopped": tr_wet,
            "note": FIXED["tr_box"],
        },
    ]
    if any("目安なし＊" in row["cells"] for row in table):
        gone = True
    if wet:
        table.append(
            {
                "key": "others",
                "label": "ほかの建物の例",
                "cells": ["—", "—", "—", "武蔵小杉は断水8日・トイレ11日（建築設備技術者協会の調査など。ほかの建物の例）", "武蔵小杉の本復旧は6〜8か月（同。ほかの建物の例）"],
                "stopped": False,
            }
        )
    day_text, morning_text = actions_for(sample)
    day = FIXED["no_stop"] if no_stop else day_text
    before = ACTIONS_BEFORE
    if measure == "plate" and sample["underground_feed"]:
        before += "。止水板だけのときは、地中の壁の穴からの経路が残ります"
    table.append(
        {
            "key": "actions",
            "label": "人がすること",
            "cells": [before, day, morning_text, "—", "—"],
            "stopped": False,
        }
    )

    if not wet:
        below.append("＊" + FIXED["nothing_wet"])
        below.append(FIXED["tr_outside"])
    elif gone:
        # 同じ表で止まる想定の設備を「浸からない」と読ませないよう、目安が消えた設備の名前だけを出す。
        names = []
        if not panel_wet:
            names.append("制御盤")
        if not hv_wet:
            names.append("受電の箱" if sample["has_chief_engineer"] else "おおもとのスイッチ盤")
        below.append("＊" + FIXED["gone"].replace("制御盤／受電の箱", "／".join(names)))

    return {
        "water": water,
        "measure": measure,
        "wet": sorted(wet),
        "stopped": sorted(stopped),
        "services": services(stopped),
        "tr_state": "stopped" if tr_wet else "unknown",
        "notes": notes,
        "below": below,
        "table": table,
    }


def scenarios(sample: dict) -> dict:
    return {
        f"{water}:{item['key']}": scenario(sample, water, item["key"])
        for water in (1, 2, 3)
        for item in measures_for_model(sample)
    }


def direction_line(directions: dict, low: List[str], sample: dict, high: Optional[List[str]] = None, basin: bool = False) -> str:
    """土地の低い向きと建物の入口を掛け合わせる一文。向きは答えと地図の目安で、測ったものではない。"""
    parts = []
    lead = ""
    if basin and high:
        lead = f"周囲（{'・'.join(high)}）の方が高く、この場所に向かって水が集まりやすい凹み（低い土地）の形です（地図の標高データの目安）。"
    if low:
        parts.append(f"周囲より低い向きの目安は{'・'.join(low)}")
    if directions.get("water"):
        parts.append(f"水が来そうな側は{directions['water']}（指定）")
    if directions.get("door"):
        parts.append(f"電気室の扉の側は{directions['door']}（指定）")
    entrances = "スロープ、扉、歩道ぎわの蓋" if sample["underground_feed"] else "坂の下の側の扉、足元の換気口"
    if not parts:
        return f"{lead}{entrances}の高さを先に確かめます。" if lead else ""
    return lead + "、".join(parts) + f"。その向きに{entrances}があれば、先に確かめます。"


def building_payload(
    sample: dict,
    confirmed: List[str],
    location_rows: List[dict],
    document_read: bool = False,
    directions: Optional[dict] = None,
    low_directions: Optional[List[str]] = None,
    statements: Optional[List[str]] = None,
    high_directions: Optional[List[str]] = None,
    basin: bool = False,
) -> dict:
    location_risk = any(row["verdict"] == "risk" for row in location_rows)
    equipment = judge_equipment(sample, confirmed, location_risk, document_read)
    return {
        "sample": samples.client_view(sample),
        "confirmed": confirmed,
        "document_read": document_read,
        "equipment": equipment,
        "top_line": top_line(sample, equipment, location_rows, confirmed),
        "measures": visible_measures(sample, equipment),
        "subsidies": samples.SUBSIDIES,
        "memos": memos(sample, equipment, location_rows, statements or []),
        "direction_line": direction_line(directions or {}, low_directions or [], sample, high_directions, basin),
        "statements": statements or [],
        "chain": chain_nodes(sample),
        "water_levels": WATER_LEVELS,
        "model_measures": measures_for_model(sample),
        "scenarios": scenarios(sample),
        "fixed": FIXED,
    }
