"""架空の見本の建物 3 つ。実在の建物の図や記録は使わない。

図面の描画、ピンの位置、3D の模型、判定のもとになる設備を、ここ一か所に持つ。
"""

from __future__ import annotations

import copy
from typing import Optional

# 図面の座標。部屋の x, y, w, h は通り芯 X1〜X4, Y1〜Y3 の範囲を 0〜1 とした割合。
PLAN_WIDTH = 1400
PLAN_HEIGHT = 990
VIEW_ORIGINS = [(120, 190), (770, 190)]
VIEW_SIZE = (500, 500)


def plan_point(view: int, x: float, y: float) -> tuple:
    """図面の割合の座標を、図面全体に対する 0〜1 の位置にする。"""
    left, top = VIEW_ORIGINS[view]
    return (
        round((left + x * VIEW_SIZE[0]) / PLAN_WIDTH, 4),
        round((top + y * VIEW_SIZE[1]) / PLAN_HEIGHT, 4),
    )


# 図面の語と部屋の種類の対応。語のゆれはここで吸収する。
ROOM_WORDS = {
    "elec": ["電気室", "受変電室", "受電室", "キュービクル室"],
    "tr": ["借室", "供給用変圧器室", "東京電力"],
    "panel_room": ["共用分電盤室", "盤室", "主開閉器盤室"],
    "pump": ["給水ポンプ室", "ポンプ室"],
    "ev": ["EV", "エレベーター", "昇降機"],
    "park": ["機械式駐車場", "駐車場ピット"],
    "slope": ["車路スロープ", "スロープ"],
    "hh": ["HH", "ハンドホール"],
    "tank": ["雨水貯留槽", "地下貯留槽", "貯留槽"],
    "basin": ["雨水ます", "雨水桝"],
    "gen": ["発電機室", "非常用発電機"],
    "door": ["坂下側出入口", "足元換気口"],
}

ROOM_NAMES = {
    "elec": "電気室（マンション側の受電の箱の部屋）",
    "tr": "東京電力の変圧器の部屋（借室）",
    "panel_room": "共用部のおおもとのスイッチ盤の部屋",
    "pump": "ポンプの部屋",
    "ev": "エレベーターの通り道",
    "park": "機械式駐車場",
    "slope": "地下へ降りる車路スロープ",
    "hh": "歩道ぎわの「東電」「高圧」の蓋",
    "tank": "地下の貯留タンク",
    "basin": "敷地の雨水ます",
    "gen": "非常用発電機の部屋",
    "door": "坂の下の側の扉と足元の換気口",
}

# 11/8 までの費用は判定表の桁だけを使う。band は 4=数万 5=数十万 6=数百万 7=数千万 8=1億円超。
MEASURES = [
    {"key": "hole", "tier": "今すぐ", "label": "ケーブルを通す壁の穴をふさぐ（マンション側の部屋の穴。施工は電気工事の業者が、主任技術者と停電の要否・離隔を決めてから。理事や管理員は部屋に入らない。東京電力の変圧器の部屋の穴には、だれも栓や止水材を入れない）", "decision": "理事会で決められる場合がある（建物の規約と予算による）", "account": "管理費", "range": "数万〜十数万円", "low": 4, "high": 5, "sample_yen": 100000, "tokyo": "with_plate", "chiba": "no"},
    {"key": "plate", "tier": "今すぐ", "label": "置くだけの止水板と吸水土のうを備える", "decision": "理事会で決められる場合がある（建物の規約と予算による）", "account": "管理費", "range": "数万〜数十万円", "low": 4, "high": 5, "sample_yen": 300000, "tokyo": "yes", "chiba": "yes"},
    {"key": "procedure", "tier": "今すぐ", "label": "大雨の前とさなかの手順を決めておく", "decision": "理事会で決められる場合がある（建物の規約と予算による）", "account": "—", "range": "—（契約による）", "low": None, "high": None, "sample_yen": 0, "tokyo": "none", "chiba": "none"},
    {"key": "tepco", "tier": "今すぐ", "label": "東京電力の変圧器の部屋の扉と穴の浸水対策を、東京電力パワーグリッドに照会し、申し入れて話し合う", "decision": "理事会で申し入れる。工事になるときの決め方は内容が分かってから", "account": "話し合いの結果による", "range": "—（確認が要る）", "low": None, "high": None, "sample_yen": 0, "tokyo": "none", "chiba": "none"},
    {"key": "panel", "tier": "工事が要る", "label": "ポンプのスイッチ盤を高い位置に付け替える（盤の下の端が低いと分かった場合）", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "数十万〜150万円", "low": 5, "high": 6, "sample_yen": 1000000, "tokyo": "unknown", "chiba": "no"},
    {"key": "pillar", "tier": "工事が要る", "label": "支柱式の止水板（アンカーで固定）", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "数十万〜200万円", "low": 5, "high": 6, "sample_yen": 1500000, "tokyo": "yes", "chiba": "no"},
    {"key": "door", "tier": "工事が要る", "label": "マンション側の電気室の扉を防水扉にする（今の枠を使う場合。東京電力の変圧器の部屋の扉は含めない）", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "100〜300万円", "low": 6, "high": 6, "sample_yen": 2000000, "tokyo": "yes", "chiba": "no"},
    {"key": "vent", "tier": "工事が要る", "label": "足元の換気口を高くする", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "数十万〜数百万円", "low": 5, "high": 6, "sample_yen": 1000000, "tokyo": "with_plate", "chiba": "no"},
    {"key": "power", "tier": "工事が要る", "label": "停電したとき外から電源車をつなげる受け口を 1 階につくる", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "数十万〜数百万円", "low": 5, "high": 6, "sample_yen": 1500000, "tokyo": "unknown", "chiba": "no"},
    {"key": "door_rebuild", "tier": "更新と一緒", "label": "壁を壊して枠ごと防水扉にする", "decision": "総会（特別決議）", "account": "修繕積立金", "range": "300万円〜", "low": None, "high": None, "open_ended": True, "sample_yen": 4000000, "tokyo": "yes", "chiba": "no"},
    {"key": "move", "tier": "更新と一緒", "label": "共用部の受電の箱を屋上に移す（設備の更新に合わせて）", "decision": "総会（特別決議）＋最上階の住戸の承諾", "account": "修繕積立金", "range": "数千万〜1億円超", "low": 7, "high": 8, "sample_yen": 60000000, "tokyo": "unknown", "chiba": "no"},
]

SUBSIDIES = {
    "tokyo": {
        "label": "東京都（2/3・上限833万円）",
        "rate_label": "補助対象経費の2/3、調査・企画と改修の合計で1棟あたり上限833万円、千円未満切り捨て",
        "cautions": [
            "交付決定の前に契約したものは対象になりません（東京都の手引き）。有料の現地調査の契約も、補助を使うなら交付決定の前にしません。",
            "受付は2026年6月5日から2027年1月15日までで、予算がなくなり次第終了です。調査・企画と改修は別々に申請します。",
            "壁の穴の止水、排気口のかさ上げ、逆流防止弁は、止水板などと併せる場合に限ります。壁の穴だけなら、それだけでは対象外になりえます。",
            "登録済みのマンション、浸水想定区域等にあること、非常用電源の条件があります。給水とエレベーターに必要な設備を守るもので、エントランスだけを守るものは対象外です。",
            "申請者は管理組合で、先に支払って事後に精算する形と読めます。都内各区の制度は確かめていません。",
        ],
    },
    "chiba": {
        "label": "千葉市（1/2・上限75万円）",
        "rate_label": "防水板の設置等の費用の1/2以内、一つの建物等につき75万円を限度、1回を限度、100円未満切り捨て",
        "cautions": [
            "防水板の工事着手・購入の前に交付決定を受ける必要があります（千葉市の案内）。対象になりうるのは、取り外しか移動ができる防水板です。",
            "「過去に浸水被害が発生した地域」が条件で、この町丁が当たるかは原文から分かりません。市の下水道営業課に確かめます。今年度の受付期間も確かめていません。",
            "共用部は理事長が申請者で、規約と理事会議事録の写しを付けると市の資料にあります。常設のものが対象かは市に確かめていません。",
        ],
    },
    "yokohama": {
        "label": "横浜市（工事の補助は見つかっていない）",
        "rate_label": "読んだ範囲では工事の補助が見つかっていません。「ない」とは言えないので市に確かめます。",
        "cautions": ["認定を目指す管理組合等へのアドバイザー派遣（費用は市の負担）があります。"],
    },
    "none": {
        "label": "それ以外（確かめていない）",
        "rate_label": "この地域の制度は確かめていません。市区町村の窓口に問い合わせます。",
        "cautions": [],
    },
}

_COMMON_DOC_NOTE = "架空の見本です。実在の建物の記録ではありません。"

SAMPLES = {
    "a": {
        "id": "a",
        "name": "うみかぜコート（架空）",
        "button": "見本A うみかぜコート（架空）／千葉市 幸町2丁目",
        "kind": "中〜大規模・埋立地・地下の電気室と借室",
        "archetype": "basement",
        "demo_point": "saiwaicho",
        "subsidy": "chiba",
        "floors": 11,
        "units": 96,
        "built": 1998,
        "has_chief_engineer": True,
        "panel_mount": "壁掛け",
        "underground_feed": True,
        "plan": {"pdf": "samples/plan_a.pdf", "png": "samples/plan_a.png"},
        "report": "samples/report_a.txt",
        "title": "竣工図 地下1階・1階平面図 ※架空の見本",
        "views": [
            {
                "name": "地下1階平面図",
                "rooms": [
                    {"key": "park", "label": "機械式駐車場ピット", "x": 0, "y": 0, "w": 0.62, "h": 0.5},
                    {"key": "aisle", "label": "車路", "x": 0.62, "y": 0, "w": 0.38, "h": 0.5},
                    {"key": "elec", "label": "電気室", "x": 0, "y": 0.5, "w": 0.3, "h": 0.5, "door": "top"},
                    {"key": "tr", "label": "借室（東京電力\n供給用変圧器室）", "x": 0.3, "y": 0.5, "w": 0.24, "h": 0.5, "door": "top"},
                    {"key": "pump", "label": "給水ポンプ室", "x": 0.54, "y": 0.5, "w": 0.24, "h": 0.5, "door": "top"},
                    {"key": "ev", "label": "EV", "x": 0.78, "y": 0.5, "w": 0.11, "h": 0.25, "symbol": "ev"},
                    {"key": "stair", "label": "階段", "x": 0.89, "y": 0.5, "w": 0.11, "h": 0.5, "symbol": "stair"},
                ],
                "marks": [
                    {"kind": "conduit_hole", "label": "ケーブルを通す壁の穴", "x": 0.1, "y": 1.0},
                ],
                "wall_label": "外壁（地下）",
            },
            {
                "name": "1階平面図",
                "rooms": [
                    {"key": "park_1f", "label": "機械式駐車場", "x": 0, "y": 0, "w": 0.62, "h": 0.5},
                    {"key": "slope", "label": "車路スロープ", "x": 0.62, "y": 0, "w": 0.38, "h": 0.5, "symbol": "slope"},
                    {"key": "bike", "label": "駐輪場", "x": 0, "y": 0.5, "w": 0.3, "h": 0.5},
                    {"key": "office", "label": "管理員室", "x": 0.3, "y": 0.5, "w": 0.24, "h": 0.5, "door": "bottom"},
                    {"key": "hall", "label": "エントランス", "x": 0.54, "y": 0.5, "w": 0.24, "h": 0.5, "door": "bottom"},
                    {"key": "ev_1f", "label": "EV", "x": 0.78, "y": 0.5, "w": 0.11, "h": 0.25, "symbol": "ev"},
                    {"key": "stair_1f", "label": "階段", "x": 0.89, "y": 0.5, "w": 0.11, "h": 0.5, "symbol": "stair"},
                ],
                "marks": [
                    {"kind": "hh", "label": "HH（東電・高圧）", "x": 0.14, "y": 1.13},
                    {"kind": "conduit", "label": "引込管路", "x": 0.14, "y": 1.13, "x2": 0.14, "y2": 1.0},
                    {"kind": "sidewalk", "label": "歩道"},
                ],
            },
        ],
        "pins": [
            {"key": "ア", "target": "elec", "view": 0, "x": 0.1, "y": 0.96, "title": "ケーブルを通す壁の穴", "how_water": "道路の下の電線の管を通って、電気室の壁の穴から水が入ることがあります。玄関の止水板では防げない経路です。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。穴が止水されているか、盤の底に錆や水滴の跡がないかを見てもらいます。", "who": "管理会社から防水・設備業者へ現地調査を依頼（部屋の中の確認は電気の月次点検の立会いに合わせる）", "who_kind": "engineer", "memo": 2, "focus": "elec"},
            {"key": "イ", "target": "pump", "view": 0, "x": 0.66, "y": 0.75, "title": "ポンプのスイッチ盤", "how_water": "盤の下の端より水が上がると、ポンプが止まり全戸断水につながります。受電が生きていても水は止まります。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。盤の下の端の高さと、部屋の床の高さ（外の地面と比べて）を測ってもらいます。", "who": "管理会社から給水ポンプの保守業者へ", "who_kind": "contractor", "memo": 3, "focus": "pump"},
            {"key": "ウ", "target": "slope", "view": 1, "x": 0.81, "y": 0.25, "title": "地下へ降りる車路スロープ", "how_water": "前の道路の水が、スロープを伝って地下へ流れ込みます。", "check": "スロープの入口の高さと、止水板を置けるか。外から見てかまいません。冠水中は近づかず、水に入りません。", "who": "外から見てよい（住民、管理会社）", "who_kind": "outside", "memo": 1, "focus": "slope"},
            {"key": "エ", "target": "tr", "view": 0, "x": 0.42, "y": 0.75, "title": "東京電力の変圧器の部屋", "how_water": "ここが浸かると各戸の電気が止まります。部屋の中の機器の高さは建物の側から分かりません。", "check": "穴や管路に、だれも栓や止水材を入れません。扉は開けず、浸水時は近づきません。扉と穴の分担は管理会社から東京電力パワーグリッドへ照会します。", "who": "管理会社から東京電力パワーグリッドへ照会", "who_kind": "tepco", "memo": 1, "focus": "tr"},
        ],
    },
    "b": {
        "id": "b",
        "name": "たにとハイム（架空）",
        "button": "見本B たにとハイム（架空）／横浜市 緑園3丁目",
        "kind": "小〜中規模・谷戸・借室のみ、設備は1階",
        "archetype": "ground",
        "demo_point": "ryokuen",
        "subsidy": "yokohama",
        "floors": 5,
        "units": 38,
        "built": 2006,
        "has_chief_engineer": False,
        "panel_mount": "架台の上",
        "underground_feed": False,
        "plan": {"pdf": "samples/plan_b.pdf", "png": "samples/plan_b.png"},
        "report": "samples/report_b.txt",
        "title": "竣工図 1階・基準階平面図 ※架空の見本",
        "views": [
            {
                "name": "1階平面図",
                "rooms": [
                    {"key": "parking_flat", "label": "平置き駐車場", "x": 0, "y": 0, "w": 0.5, "h": 0.42},
                    {"key": "bike", "label": "駐輪場", "x": 0.5, "y": 0, "w": 0.28, "h": 0.42},
                    {"key": "ev", "label": "EV", "x": 0.78, "y": 0, "w": 0.11, "h": 0.21, "symbol": "ev"},
                    {"key": "stair", "label": "階段", "x": 0.89, "y": 0, "w": 0.11, "h": 0.42, "symbol": "stair"},
                    {"key": "panel_room", "label": "共用分電盤室", "x": 0, "y": 0.42, "w": 0.26, "h": 0.58, "door": "bottom"},
                    {"key": "tr", "label": "借室（東京電力\n供給用変圧器室）", "x": 0.26, "y": 0.42, "w": 0.26, "h": 0.58, "door": "bottom"},
                    {"key": "pump", "label": "給水ポンプ室", "x": 0.52, "y": 0.42, "w": 0.22, "h": 0.58, "door": "bottom"},
                    {"key": "hall", "label": "エントランス", "x": 0.74, "y": 0.42, "w": 0.26, "h": 0.58, "door": "bottom"},
                ],
                "marks": [
                    {"kind": "door_low", "label": "坂下側出入口・足元換気口", "x": 0.13, "y": 1.0},
                    {"kind": "sidewalk", "label": "敷地内通路"},
                ],
            },
            {
                "name": "基準階平面図",
                "rooms": [
                    {"key": "unit_1", "label": "住戸", "x": 0, "y": 0.2, "w": 0.26, "h": 0.8},
                    {"key": "unit_2", "label": "住戸", "x": 0.26, "y": 0.2, "w": 0.26, "h": 0.8},
                    {"key": "unit_3", "label": "住戸", "x": 0.52, "y": 0.2, "w": 0.26, "h": 0.8},
                    {"key": "corridor", "label": "共用廊下", "x": 0, "y": 0, "w": 0.78, "h": 0.2},
                    {"key": "ev_u", "label": "EV", "x": 0.78, "y": 0, "w": 0.11, "h": 0.21, "symbol": "ev"},
                    {"key": "stair_u", "label": "階段", "x": 0.89, "y": 0, "w": 0.11, "h": 0.42, "symbol": "stair"},
                ],
                "marks": [],
            },
        ],
        "pins": [
            {"key": "ア", "target": "panel_room", "view": 0, "x": 0.13, "y": 0.72, "title": "共用部のおおもとのスイッチ盤", "how_water": "地下はありませんが、床が通路より少し高いだけなら、浅い水でも盤の下の端に届くことがあります。", "check": "盤の下の端の高さを測ってもらいます。扉を開けて盤に近づくのは電気工事の業者だけです。防水業者や管理会社は扉を開けず、盤や電線に触れません。住民、理事、管理員は部屋に入りません。", "who": "管理会社から電気工事の業者へ（主任技術者はいない建物です）", "who_kind": "contractor", "memo": 2, "focus": "panel_room"},
            {"key": "イ", "target": "pump", "view": 0, "x": 0.63, "y": 0.72, "title": "ポンプのスイッチ盤", "how_water": "架台の上の盤でも、下の端より水が上がると、ポンプが止まり断水につながります。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。盤の下の端の高さと、部屋の床の高さを測ってもらいます。", "who": "管理会社から給水ポンプの保守業者へ", "who_kind": "contractor", "memo": 3, "focus": "pump"},
            {"key": "ウ", "target": "door", "view": 0, "x": 0.13, "y": 1.0, "title": "坂の下の側の扉と足元の換気口", "how_water": "丘と谷が入り組んだ土地では、坂の下の側に水が集まり、扉の下や足元の換気口から入ることがあります。", "check": "扉の下の段差と換気口の高さ。外から見てかまいません。冠水中は近づかず、水に入りません。", "who": "外から見てよい（住民、管理会社）", "who_kind": "outside", "memo": 1, "focus": "door"},
            {"key": "エ", "target": "tr", "view": 0, "x": 0.39, "y": 0.72, "title": "東京電力の変圧器の部屋", "how_water": "この建物では、ここが浸かると各戸と共用部の両方の電気が止まります。部屋の中の機器の高さは建物の側から分かりません。", "check": "穴や管路に、だれも栓や止水材を入れません。扉は開けず、浸水時は近づきません。扉と穴の分担は管理会社から東京電力パワーグリッドへ照会します。", "who": "管理会社から東京電力パワーグリッドへ照会", "who_kind": "tepco", "memo": 1, "focus": "tr"},
        ],
    },
    "c": {
        "id": "c",
        "name": "あおぞらタワー（架空）",
        "button": "見本C あおぞらタワー（架空）／東京都 江東区大島2丁目",
        "kind": "タワーマンション・地下設備、雨水ますと地下貯留槽、非常用発電機",
        "archetype": "tower",
        "demo_point": "oshima",
        "subsidy": "tokyo",
        "floors": 38,
        "units": 420,
        "built": 2009,
        "has_chief_engineer": True,
        "panel_mount": "壁掛け",
        "underground_feed": True,
        "plan": {"pdf": "samples/plan_c.pdf", "png": "samples/plan_c.png"},
        "report": "samples/report_c.txt",
        "title": "竣工図 地下1階・1階平面図 ※架空の見本",
        "views": [
            {
                "name": "地下1階平面図",
                "rooms": [
                    {"key": "park", "label": "機械式駐車場ピット", "x": 0, "y": 0, "w": 0.46, "h": 0.42},
                    {"key": "aisle", "label": "車路", "x": 0.46, "y": 0, "w": 0.26, "h": 0.42},
                    {"key": "tank", "label": "雨水貯留槽（地下）", "x": 0.72, "y": 0, "w": 0.28, "h": 0.42, "hatch": True},
                    {"key": "elec", "label": "受変電室", "x": 0, "y": 0.42, "w": 0.26, "h": 0.58, "door": "top"},
                    {"key": "tr", "label": "借室（東京電力\n供給用変圧器室）", "x": 0.26, "y": 0.42, "w": 0.2, "h": 0.58, "door": "top"},
                    {"key": "gen", "label": "非常用\n発電機室", "x": 0.46, "y": 0.42, "w": 0.14, "h": 0.58, "door": "top"},
                    {"key": "pump", "label": "給水ポンプ室", "x": 0.6, "y": 0.42, "w": 0.18, "h": 0.58, "door": "top"},
                    {"key": "ev", "label": "EV", "x": 0.78, "y": 0.42, "w": 0.11, "h": 0.29, "symbol": "ev"},
                    {"key": "stair", "label": "階段", "x": 0.89, "y": 0.42, "w": 0.11, "h": 0.58, "symbol": "stair"},
                ],
                "marks": [
                    {"kind": "conduit_hole", "label": "ケーブルを通す壁の穴", "x": 0.09, "y": 1.0},
                ],
            },
            {
                "name": "1階平面図",
                "rooms": [
                    {"key": "park_1f", "label": "機械式駐車場", "x": 0, "y": 0, "w": 0.46, "h": 0.42},
                    {"key": "slope", "label": "車路スロープ", "x": 0.46, "y": 0, "w": 0.26, "h": 0.42, "symbol": "slope"},
                    {"key": "garden", "label": "公開空地", "x": 0.72, "y": 0, "w": 0.28, "h": 0.42},
                    {"key": "office", "label": "防災センター", "x": 0, "y": 0.42, "w": 0.26, "h": 0.58, "door": "bottom"},
                    {"key": "lobby", "label": "エントランスホール", "x": 0.26, "y": 0.42, "w": 0.52, "h": 0.58, "door": "bottom"},
                    {"key": "ev_1f", "label": "EV", "x": 0.78, "y": 0.42, "w": 0.11, "h": 0.29, "symbol": "ev"},
                    {"key": "stair_1f", "label": "階段", "x": 0.89, "y": 0.42, "w": 0.11, "h": 0.58, "symbol": "stair"},
                ],
                "marks": [
                    {"kind": "basin", "label": "雨水ます", "x": 0.92, "y": 0.33},
                    {"kind": "hh", "label": "HH（東電・高圧）", "x": 0.1, "y": 1.13},
                    {"kind": "conduit", "label": "引込管路", "x": 0.1, "y": 1.13, "x2": 0.1, "y2": 1.0},
                    {"kind": "sidewalk", "label": "歩道"},
                ],
            },
        ],
        "pins": [
            {"key": "ア", "target": "elec", "view": 0, "x": 0.09, "y": 0.96, "title": "ケーブルを通す壁の穴", "how_water": "道路の下の電線の管を通って、受電の箱の部屋の壁の穴から水が入ることがあります。玄関の止水板では防げない経路です。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。穴が止水されているか、盤の底に錆や水滴の跡がないかを見てもらいます。", "who": "管理会社から防水・設備業者へ現地調査を依頼（部屋の中の確認は電気の月次点検の立会いに合わせる）", "who_kind": "engineer", "memo": 2, "focus": "elec"},
            {"key": "イ", "target": "pump", "view": 0, "x": 0.69, "y": 0.71, "title": "ポンプのスイッチ盤", "how_water": "盤の下の端より水が上がると、ポンプが止まり全戸断水につながります。高層階ほど階段で水を運ぶのが難しくなります。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。盤の下の端の高さと、部屋の床の高さを測ってもらいます。", "who": "管理会社から給水ポンプの保守業者へ", "who_kind": "contractor", "memo": 3, "focus": "pump"},
            {"key": "ウ", "target": "tank", "view": 0, "x": 0.86, "y": 0.21, "title": "雨水ますと地下の貯留タンク", "how_water": "敷地の水が雨水ますからタンクへ流れ込み、満水になると地下の蓋からあふれることがあります（武蔵小杉の例。建築設備技術者協会の調査など）。", "check": "蓋は開けません。導入管に止水バルブがあるか、タンクの蓋に耐水圧のロックがあるかを、竣工図で確かめ、現地は業者に見てもらいます。", "who": "管理会社が竣工図で確かめ、設備業者へ現地調査を依頼", "who_kind": "contractor", "memo": 2, "focus": "tank"},
            {"key": "エ", "target": "tr", "view": 0, "x": 0.36, "y": 0.71, "title": "東京電力の変圧器の部屋", "how_water": "ここが浸かると各戸の電気が止まります。部屋の中の機器の高さは建物の側から分かりません。", "check": "穴や管路に、だれも栓や止水材を入れません。扉は開けず、浸水時は近づきません。水防ラインの協議は管理組合と管理会社が東京電力パワーグリッドと行います。", "who": "管理会社から東京電力パワーグリッドへ照会", "who_kind": "tepco", "memo": 1, "focus": "tr"},
        ],
    },
}

REPORTS = {
    "a": """月次点検結果報告書（架空の見本）

建物名：うみかぜコート（架空）
受電設備：地下1階 電気室（キュービクル式）
点検結果：良
指摘事項：電気室床に湿気あり。経過を観察する。
給水：受水槽とポンプによる。給水ポンプ制御盤は地下1階 給水ポンプ室の壁掛け。下端の高さは記載なし。
引込み：地中（高圧）。
管路口の止水処理：点検項目になく、記載なし。
借室：地下1階にあると管理員から聞いている。

※架空の見本です。実在の建物の記録ではありません。
""",
    "b": """共用設備点検結果報告書（架空の見本）

建物名：たにとハイム（架空）
受電：マンション側の受電設備なし。電気主任技術者を選任していない。
共用部の電気：1階 共用分電盤室の主開閉器盤。東京電力の変圧器の部屋（借室）から低圧で受電。
給水：増圧ポンプ。1階 給水ポンプ室、制御盤は架台の上。下端の高さは記載なし。
指摘事項：なし（良）。
引込み：架空（敷地内の電柱から）。

※架空の見本です。実在の建物の記録ではありません。
""",
    "c": """月次点検結果報告書（架空の見本）

建物名：あおぞらタワー（架空）
受電設備：地下1階 受変電室。
非常用発電機：地下1階 発電機室。火災時用。
給水：受水槽とポンプによる。給水ポンプ制御盤は地下1階 給水ポンプ室の壁掛け。下端の高さは記載なし。
雨水：雨水ますから地下の雨水貯留槽へ導入。導入管の止水バルブは記載なし。
指摘事項：なし（良）。
引込み：地中（高圧）。
管路口の止水処理：点検項目になく、記載なし。

※架空の見本です。実在の建物の記録ではありません。
""",
}


# 見本の設定を質問の答えの形にしたもの。見本を手直しするときの初めの値。
DEFAULT_ANSWERS = {
    "a": {"built_year": 1998, "floors": 11, "basement": "yes", "rooms_floor": "basement", "slope": "yes", "vent": "unknown", "cover": "yes", "panel_foot": "raised", "door_step": "unknown", "tr": "yes", "hv": "yes"},
    "b": {"built_year": 2006, "floors": 5, "basement": "no", "rooms_floor": "ground", "slope": "no", "vent": "yes", "cover": "no", "panel_foot": "raised", "door_step": "yes", "tr": "yes", "hv": "no", "hv_documented": True},
    "c": {"built_year": 2009, "floors": 38, "basement": "yes", "rooms_floor": "basement", "slope": "yes", "vent": "unknown", "cover": "yes", "panel_foot": "raised", "door_step": "unknown", "tr": "yes", "hv": "yes"},
}
EMPTY_ANSWERS = {"built_year": None, "floors": None, "basement": "unknown", "rooms_floor": "unknown", "slope": "unknown", "vent": "unknown", "cover": "unknown", "panel_foot": "unknown", "door_step": "unknown", "tr": "unknown", "hv": "unknown"}


def base_for_answers(answers: dict, fallback: Optional[str] = None) -> str:
    """答えに一番近い形の見本を選ぶ。模型と図面の形を借りるだけで、建物の事実にはしない。"""
    if answers.get("rooms_floor") == "ground" or answers.get("basement") == "no":
        return "b"
    if (answers.get("floors") or 0) >= 20:
        return "c"
    return fallback if fallback in ("a", "c") else "a"


def region_of(label: str) -> str:
    for word, region in (("東京都", "tokyo"), ("千葉市", "chiba"), ("横浜市", "yokohama")):
        if word in label:
            return region
    return "none"


def apply_answers(sample_id: Optional[str], answers: Optional[dict], label: str = "") -> Optional[dict]:
    """質問の答えを見本の形に重ねる。見本の id がないときは、自分の建物として近い形を借りる。"""
    custom = not sample_id
    if custom and not answers:
        return None
    answers = {**EMPTY_ANSWERS, **DEFAULT_ANSWERS.get(sample_id or "", {}), **(answers or {})}
    original = get(sample_id)
    base = get(base_for_answers(answers, sample_id))
    sample = copy.deepcopy(base)
    sample["answers"] = answers
    sample["custom"] = custom
    if custom:
        sample["name"] = "あなたの建物（見本の形を借りて説明）"
        sample["subsidy"] = region_of(label)
        sample["units"] = None
        sample["kind"] = "質問の答えから、近い形の見本を借りています"
    else:
        # 見本を手直ししても、名前と住所の地域は元の見本のまま。借りるのは設備の形だけ。
        sample["name"] = original["name"]
        sample["subsidy"] = original["subsidy"]
        sample["units"] = original["units"]
    sample["floors"] = answers.get("floors") or sample["floors"]
    sample["built"] = answers.get("built_year") or (None if custom else sample["built"])
    # 受電設備の「なし」は、書類に明記があるときだけ読む。答えだけなら主任技術者の有無は未確認。
    documented_none = answers.get("hv") == "no" and answers.get("hv_documented")
    sample["has_chief_engineer"] = not documented_none
    sample["engineer_unsure"] = answers.get("hv") in ("no", "unknown") and not documented_none
    sample["hv_unknown"] = sample["engineer_unsure"]
    # 引込みは書類で分かったときだけ決める。蓋の答えは代理の手がかりにとどめる。
    feed = answers.get("feed")
    sample["feed_unknown"] = False
    if feed in ("underground", "overhead"):
        sample["underground_feed"] = feed == "underground"
    elif custom:
        sample["feed_unknown"] = True
        sample["underground_feed"] = answers.get("cover") == "yes" or base["underground_feed"]
    sample["panel_mount"] = {"floor": "床置き", "raised": base["panel_mount"], "unknown": "形は未確認"}[answers.get("panel_foot", "raised")]
    return sample


def get(sample_id: Optional[str]) -> Optional[dict]:
    return SAMPLES.get(sample_id or "")


def client_view(sample: dict) -> dict:
    """画面へ渡す形。ピンに図面全体に対する位置を添える。"""
    pins = []
    for pin in sample["pins"]:
        px, py = plan_point(pin["view"], pin["x"], pin["y"])
        pins.append({**pin, "px": px, "py": py})
    keys = {
        room["key"] for view in sample["views"] for room in view["rooms"]
    }
    return {
        **{k: sample[k] for k in ("id", "name", "button", "kind", "archetype", "subsidy", "floors", "units", "built", "has_chief_engineer", "panel_mount", "underground_feed", "plan", "report", "title")},
        "answers": sample.get("answers") or DEFAULT_ANSWERS.get(sample["id"], {}),
        "custom": bool(sample.get("custom")),
        "engineer_unsure": bool(sample.get("engineer_unsure")),
        "pins": pins,
        "rooms": sorted(keys),
        "views": sample["views"],
    }
