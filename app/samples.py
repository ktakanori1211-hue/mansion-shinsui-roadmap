"""架空の見本の建物 3 つ。実在の建物の図や記録は使わない。

図面の描画、ピンの位置、3D の模型、判定のもとになる設備を、ここ一か所に持つ。
"""

from __future__ import annotations

import copy
import re
import unicodedata
from typing import List, Optional

# 図面の用紙。部屋の x, y, w, h は、図の外周を 0〜1 とした割合で、3D の模型とピンも同じ値を使う。
PLAN_WIDTH = 1400
PLAN_HEIGHT = 990


def plan_point(sample: dict, view: int, x: float, y: float) -> tuple:
    """図の割合の座標を、用紙全体に対する 0〜1 の位置にする。"""
    left, top, width = sample["plan_frames"][view]
    height = width * sample["plan_size"][1] / sample["plan_size"][0]
    return (
        round((left + x * width) / PLAN_WIDTH, 4),
        round((top + y * height) / PLAN_HEIGHT, 4),
    )


def _rooms(size: tuple, *rows: tuple) -> list:
    """mm で書いた部屋を、割合にする。(種類, 名前, x0, y0, x1, y1, ほかの項目)"""
    rooms = []
    for row in rows:
        key, label, x0, y0, x1, y1 = row[:6]
        extra = row[6] if len(row) > 6 else {}
        rooms.append({"key": key, "label": label, "x": x0 / size[0], "y": y0 / size[1], "w": (x1 - x0) / size[0], "h": (y1 - y0) / size[1], "mm": [x0, y0, x1, y1], **extra})
    return rooms


def _door(side: str, at: float, kind: str = "door", width: int = 900) -> dict:
    return {"side": side, "at": at, "kind": kind, "w": width}


# 図面の語と部屋の種類の対応。語のゆれはここで吸収する。
# 2026-11-06 本人の指示：文字の間の空白（「電 気 室」）を無視し、「東電借室」「電力借室」「TR室」「自家用電気室」「高圧受電室」「増圧ポンプ」「受水槽室」も読む。
ROOM_WORDS = {
    "elec": ["電気室", "受変電室", "受電室", "キュービクル室", "自家用電気室", "高圧受電室"],
    "tr": ["借室", "東電借室", "電力借室", "TR室", "供給用変圧器室", "東京電力"],
    "panel_room": ["共用分電盤室", "盤室", "主開閉器盤室"],
    "pump": ["給水ポンプ室", "ポンプ室", "増圧ポンプ", "受水槽室"],
    "ev": ["EV", "エレベーター", "昇降機"],
    "park": ["機械式駐車場", "駐車場ピット"],
    "slope": ["車路スロープ", "スロープ"],
    "hh": ["HH", "ハンドホール"],
    "tank": ["雨水貯留槽", "地下貯留槽", "貯留槽"],
    "basin": ["雨水ます", "雨水桝"],
    "gen": ["発電機室", "非常用発電機"],
    "door": ["坂下側出入口", "足元換気口"],
}

def _plain_word(text: str) -> str:
    """全角・半角をそろえ、空白（全角の空白も）を除き、英字を大文字にする。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).upper()


def room_kind(text: str) -> Optional[str]:
    """図面の語から部屋の種類を返す。「電 気 室」「ＴＲ室」「tr室」も読む。"""
    plain = _plain_word(text)
    for kind, names in ROOM_WORDS.items():
        if any(_plain_word(name) in plain for name in names):
            return kind
    return None


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
    {"key": "hole", "tier": "今すぐ", "label": "ケーブルを通す壁の穴をふさぐ（マンション側の部屋の穴。施工は電気工事の業者が、主任技術者と停電の要否・離隔を決めてから。理事や管理員は部屋に入らない。東京電力の変圧器の部屋の穴には、だれも栓や止水材を入れない）", "decision": "理事会で決められる場合がある（建物の規約と予算による）", "account": "管理費", "range": "5万円（穴1か所）", "low": 4, "high": 5, "sample_yen": 50000, "tokyo": "with_plate", "chiba": "no"},
    {"key": "plate", "tier": "今すぐ", "label": "置くだけの止水板と吸水土のうを備える", "decision": "理事会で決められる場合がある（建物の規約と予算による）", "account": "管理費", "range": "35万円（幅1mの扉1か所）", "low": 5, "high": 5, "sample_yen": 350000, "tokyo": "yes", "chiba": "yes"},
    {"key": "procedure", "tier": "今すぐ", "label": "大雨の前とさなかの手順を決めておく", "decision": "理事会で決められる場合がある（建物の規約と予算による）", "account": "—", "range": "—（契約による）", "low": None, "high": None, "sample_yen": 0, "tokyo": "none", "chiba": "none"},
    {"key": "tepco", "tier": "今すぐ", "label": "東京電力の変圧器の部屋の扉と穴の浸水対策を、東京電力パワーグリッドに照会し、申し入れて話し合う", "decision": "理事会で申し入れる。工事になるときの決め方は内容が分かってから", "account": "話し合いの結果による", "range": "—（確認が要る）", "low": None, "high": None, "sample_yen": 0, "tokyo": "none", "chiba": "none"},
    {"key": "panel", "tier": "工事が要る", "label": "ポンプのスイッチ盤を高い位置に付け替える（盤の下の端が低いと分かった場合）", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "35万円（ケーブル延長ありは120万円）", "low": 5, "high": 6, "sample_yen": 350000, "tokyo": "unknown", "chiba": "no"},
    {"key": "pillar", "tier": "工事が要る", "label": "支柱式の止水板（アンカーで固定）", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "80万〜180万円（正面玄関〜地下車路）", "low": 5, "high": 6, "sample_yen": 800000, "tokyo": "yes", "chiba": "no"},
    {"key": "door", "tier": "工事が要る", "label": "マンション側の電気室の扉を防水扉にする（今の枠を使う場合。東京電力の変圧器の部屋の扉は含めない）", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "100〜300万円", "low": 6, "high": 6, "sample_yen": 2000000, "tokyo": "yes", "chiba": "no"},
    {"key": "vent", "tier": "工事が要る", "label": "足元の換気口を高くする", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "30万円（換気口1か所）", "low": 5, "high": 6, "sample_yen": 300000, "tokyo": "with_plate", "chiba": "no"},
    {"key": "power", "tier": "工事が要る", "label": "停電したとき外から電源車をつなげる受け口を 1 階につくる", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "数十万〜数百万円", "low": 5, "high": 6, "sample_yen": 1500000, "tokyo": "unknown", "chiba": "no"},
    {"key": "door_rebuild", "tier": "更新と一緒", "label": "壁を壊して枠ごと防水扉にする", "decision": "総会（特別決議）", "account": "修繕積立金", "range": "300万円〜", "low": None, "high": None, "open_ended": True, "sample_yen": 4000000, "tokyo": "yes", "chiba": "no"},
    # 「受電の箱を屋上へ移す」は、現実的でないため外した（2026-11-06 本人決定）。
    # ここから下は、ノートの「実現したい機能」から足した行。新しい金額は持たず、桁は見積りで確かめる。
    {"key": "pump_check", "tier": "今すぐ", "label": "排水ポンプ（地下の床、機械式駐車場の掘り込み、汚水の汲み上げ）が動くかを、保守会社の点検で確かめる", "decision": "理事会で決められる場合がある（建物の規約と予算による）", "account": "管理費（保守の契約に入っているかを確かめる）", "range": "—（契約による）", "low": None, "high": None, "sample_yen": 0, "tokyo": "none", "chiba": "none"},
    {"key": "backflow", "tier": "工事が要る", "label": "逆止弁を付ける", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "—（見積りで確かめる）", "low": None, "high": None, "sample_yen": 0, "tokyo": "with_plate", "chiba": "no"},
    {"key": "main_panel", "tier": "工事が要る", "label": "共用の主開閉器盤（低圧）を高い位置に付け替える（盤の下の端が低いと分かった場合）", "decision": "総会（普通決議）", "account": "修繕積立金", "range": "—（見積りで確かめる）", "low": None, "high": None, "sample_yen": 0, "tokyo": "unknown", "chiba": "no"},
    {"key": "gen_move", "tier": "更新と一緒", "label": "非常用発電機を上の階へ移す（設備の更新に合わせて）", "decision": "総会（特別決議）", "account": "修繕積立金", "range": "—（見積りで確かめる）", "low": None, "high": None, "sample_yen": 0, "tokyo": "unknown", "chiba": "no"},
]

# 処置ごとの「担当」の列（誰が動くか）。主任技術者のいない建物では、壁の穴の行の括弧を外す（building.visible_measures）。
MEASURE_OWNERS = {
    "hole": "管理会社→電気工事の業者（主任技術者と決める）",
    "plate": "理事会→管理会社",
    "procedure": "理事会",
    "tepco": "管理会社→東京電力パワーグリッド",
    "panel": "管理会社→ポンプの保守業者",
}
HOLE_OWNER_NO_ENGINEER = "管理会社→電気工事の業者"

# 壁の穴の行の折りたたみに出す、塞ぎ方の使い分け。施工時間や停電の要否は根拠が確かめられていないので書かない。
HOLE_NOTE = "使っていない予備の管の口は栓で塞ぎ、ケーブルが通った穴は固まらない（非硬化の）止水材で埋めます（ケーブルの通った穴に栓は使えません）。"
# 費用の単価（2026-11-06 本人＝電気主任技術者の実務の目安）。場所・サイズ別の単価×個数で、画面4の表と A4 と相談の文に使う。
# kind：plate は止水板（補助の対象の計算に使う）。default は、その建物で最初に入れておく個数の決め方。
COST_BASIS_NONE = "作者（電気主任技術者）の実務の目安です。見積りに置き換えます。"
UNIT_PRICES = [
    {"key": "door_plate", "label": "通用口・機械室の扉の止水板（幅1m）", "yen": 350000, "kind": "plate", "measure": "plate", "default": "one"},
    {"key": "front_plate", "label": "正面玄関の止水板（幅2.5m）", "yen": 800000, "kind": "plate", "measure": "pillar", "default": "one"},
    {"key": "slope_plate", "label": "地下車路スロープの止水板（幅4m）", "yen": 1800000, "kind": "plate", "measure": "pillar", "default": "slope"},
    {"key": "hole", "label": "壁の配管・ケーブル穴の穴埋め（1か所）", "yen": 50000, "kind": "hole", "measure": "hole", "default": "feed"},
    {"key": "vent", "label": "地下換気口のカバー（1か所）", "yen": 300000, "kind": "vent", "measure": "vent", "default": "zero"},
    {"key": "panel", "label": "ポンプ制御盤の壁掛け・かさ上げ", "yen": 350000, "kind": "panel", "measure": "panel", "default": "floor_panel"},
    {"key": "panel_cable", "label": "同上（ケーブル延長あり）", "yen": 1200000, "kind": "panel", "measure": "panel", "default": "zero"},
]
# 未対策で浸水したときの復旧費の目安（同じく作者の実務の目安）。
RECOVERY_COST_LINE = "未対策で浸水したときの復旧費の目安：約1,000万〜2,500万円（1〜4週間の断水・停電）"
for _measure in MEASURES:
    if not _measure["range"].startswith("—"):
        _measure["cost_basis"] = COST_BASIS_NONE
    if _measure["key"] in MEASURE_OWNERS:
        _measure["owner"] = MEASURE_OWNERS[_measure["key"]]
    if _measure["key"] == "hole":
        _measure["note"] = HOLE_NOTE

SUBSIDIES = {
    "tokyo": {
        "label": "東京都（2/3・上限833万円）",
        "rate_label": "補助対象経費の2/3、調査・企画と改修の合計で1棟あたり上限833万円、千円未満切り捨て",
        "cautions": [
            "交付決定の前に契約したものは対象になりません（東京都の手引き）。有料の現地調査の契約も、補助を使うなら交付決定の前にしません。",
            "受付は2026年6月5日から2027年1月15日までで、予算がなくなり次第終了です。調査・企画と改修は別々に申請します。",
            "壁の穴の止水、排気口のかさ上げ、逆流防止弁は、止水板などと併せる場合に限ります。壁の穴だけなら、それだけでは対象外になりえます。",
            "登録済みのマンション、浸水想定区域等にあること、非常用電源の条件があります。給水とエレベーターに必要な設備を守るもので、エントランスだけを守るものは対象外です。",
            "申請者は管理組合で、先に支払って事後に精算する形と読めます。区市の制度は、東京都の一覧（令和8年11月現在）にある区市のうち、原文を読めたものだけを載せています。",
        ],
        "url": "https://www.metro.tokyo.lg.jp/documents/d/tosei/20260605_08_07",
        "checked": "2026-11-06",
        "calc": {"rate": 2 / 3, "cap": 8330000, "unit": 1000},
    },
    "chiba": {
        "label": "千葉市（1/2・上限75万円）",
        "rate_label": "防水板の設置等の費用の1/2以内、一つの建物等につき75万円を限度、1回を限度、100円未満切り捨て",
        "cautions": [
            "防水板の工事着手・購入の前に交付決定を受ける必要があります（千葉市の案内）。対象になりうるのは、取り外しか移動ができる防水板です。",
            "「過去に浸水被害が発生した地域」が条件です。この町丁が当たるかは原文から読み取れないので、今年度の受付期間とあわせて市の下水道営業課に確かめます。",
            "共用部は理事長が申請者で、規約と理事会議事録の写しを付けると市の資料にあります。常設のものも対象になるかは、市に確かめます。",
        ],
        "url": "https://www.city.chiba.jp/kensetsu/gesuidokikaku/eigyo/youkou-youryou.html",
        "checked": "2026-11-06",
        "calc": {"rate": 1 / 2, "cap": 750000, "unit": 100},
    },
    "yokohama": {
        "label": "横浜市（工事の補助は見つかっていない）",
        "rate_label": "読んだ範囲では工事の補助は見つかっていませんが、ないとは言い切れないので市に確かめます。",
        "cautions": ["認定を目指す管理組合等へのアドバイザー派遣（費用は市の負担）があります。"],
    },
    "none": {
        "label": "この市区町村の制度は、まだ調べていません",
        "rate_label": "調べていないことは、補助がないという意味ではありません。市区町村の窓口（防災・下水道・住宅の担当）に確かめます。",
        "cautions": [],
    },
}

# 東京電力の区域の区市の止水板の助成（2026-11-06 調べ。自治体の公式ページ・要綱の原文で確かめたものだけ。率・上限は原文のまま）。
# covers は、計算例を出す対策ごとの率・上限（plate＝置くだけの止水板、pillar＝支柱式の止水板の工事）。
# 原文が簡易型の購入を含まない制度は pillar だけ。申請者の区分や受付が分からない制度は、計算しない（covers なし）。
# 東京都の区市は、都の補助と一緒に使えるかを区市に確かめる（ほかの公的補助と重ねて使えないと書く区がある）。
_TOKYO_TOO = "東京都の「東京とどまるマンション」（2/3・上限833万円。登録などの条件あり）もあります。区市の助成と一緒に使えるかは、区市に確かめます。"
MUNICIPAL_SUBSIDIES = [
    ("東京都", "中野区", "nakano", {
        "label": "中野区（止水板：1/2・工事は上限100万円）",
        "rate_label": "助成対象経費の1/2。工事は1棟100万円、簡易型止水板の購入は15万円まで。区内マンションの管理組合も申請できる",
        "cautions": ["着手・購入の前に申請します。管理組合は集会の決議の書類が要ります。", "ほかの公的補助を受けられる場合は対象外と要綱にあります。", "2026年7月6日施行。受付期間は要綱に書かれていないので区に確かめます。", _TOKYO_TOO],
        "url": "https://www.city.tokyo-nakano.lg.jp/bosai/suigai-sonae/shisuiban.files/youkou.pdf", "checked": "2026-11-06",
        "covers": {"plate": {"rate": 1 / 2, "cap": 150000, "unit": 1}, "pillar": {"rate": 1 / 2, "cap": 1000000, "unit": 1}}}),
    ("東京都", "練馬区", "nerima", {
        "label": "練馬区（止水板：1/2・上限100万円）",
        "rate_label": "工事・購入費用の1/2、上限100万円（100円未満切り捨て）。区内のマンション管理組合が対象",
        "cautions": ["集会の決議を示す議事録などが要ります。", "ほかの国・都・区の助成と重ねて使えません。", "令和8年7月に始まった制度です。", _TOKYO_TOO],
        "url": "https://www.city.nerima.tokyo.jp/kurashi/sumai/chisui/shisuiban.html", "checked": "2026-11-06",
        "covers": {"plate": {"rate": 1 / 2, "cap": 1000000, "unit": 100}, "pillar": {"rate": 1 / 2, "cap": 1000000, "unit": 100}}}),
    ("東京都", "北区", "kita", {
        "label": "北区（止水板：1/2・上限50万円）",
        "rate_label": "止水板設置工事（税込）の1/2、1建物50万円まで（千円未満切り捨て）、1建物1回。分譲マンションは管理組合の理事長が申請できる",
        "cautions": ["事前の相談が要ります。", "ほかの公的補助を受ける場合は対象外です。", _TOKYO_TOO],
        "url": "https://www.city.kita.lg.jp/safety/disaster/1018237/1018238/1002607.html", "checked": "2026-11-06",
        "covers": {"pillar": {"rate": 1 / 2, "cap": 500000, "unit": 1000}}}),
    ("東京都", "港区", "minato", {
        "label": "港区（止水板：工事費の4/5まで・上限150万円）",
        "rate_label": "上限150万円（助成率は工事費の4/5が限度）。マンションの管理組合も対象。令和8年4月1日〜令和11年3月31日",
        "cautions": ["工事の前に電話で相談し、交付の承認の前に着工しません。", _TOKYO_TOO],
        "url": "https://www.city.minato.tokyo.jp/dobokukeikaku/shisuiban/shisuiban.html", "checked": "2026-11-06",
        "covers": {"pillar": {"rate": 4 / 5, "cap": 1500000, "unit": 1}}}),
    ("東京都", "大田区", "ota", {
        "label": "大田区（止水板：法人3/5・上限150万円など）",
        "rate_label": "工事は個人4/5・法人3/5、上限は区内個人100万円・その他個人50万円・法人150万円。区内マンションの管理組合も申請できる",
        "cautions": ["管理組合が個人と法人のどちらの区分に当たるかは要綱に書かれていないので、区に確かめます（そのため計算例は出しません）。", "対象区域は区のハザードマップの浸水想定区域等です。令和9年3月31日まで。", _TOKYO_TOO],
        "url": "https://www.city.ota.tokyo.jp/seikatsu/sumaimachinami/sumai/j_josei/shisui-ban_josei.files/20251208_sisuibannyoukou.pdf", "checked": "2026-11-06"}),
    ("東京都", "世田谷区", "setagaya", {
        "label": "世田谷区（止水板：法人3/5・上限100万円など）",
        "rate_label": "個人4/5・法人3/5、工事は上限100万円、簡易型は16万円",
        "cautions": ["管理組合が申請できるかは要綱に書かれていないので、区に確かめます（そのため計算例は出しません）。", "ほかの国・都・区の補助を受ける場合は対象外です。", _TOKYO_TOO],
        "url": "https://www.city.setagaya.lg.jp/03666/31783.html", "checked": "2026-11-06"}),
    ("東京都", "品川区", "shinagawa", {
        "label": "品川区（止水板：法人3/5・上限150万円など）",
        "rate_label": "個人4/5・法人3/5。上限は住民登録のある個人100万円、1年以上区内登記の法人150万円など。令和8年度末までの時限措置",
        "cautions": ["管理組合が申請できるかは資料に書かれていないので、区に確かめます（そのため計算例は出しません）。", _TOKYO_TOO],
        "url": "https://gikai.city.shinagawa.tokyo.jp/wp-content/themes/shinagawakugikai/pdf/2025.11.05ken03.pdf", "checked": "2026-11-06"}),
    ("東京都", "目黒区", "meguro", {
        "label": "目黒区（止水板の工事：令和8年度の受付は終了）",
        "rate_label": "個人9/10・法人3/4（上限は個人100万円・法人150万円など）。令和8年度は受付終了、令和9年度は事前相談のみ",
        "cautions": ["管理組合の区分は書かれていないので、区に確かめます。", _TOKYO_TOO],
        "url": "https://www.city.meguro.tokyo.jp/douro/kurashi/sumai/sisuiban.html", "checked": "2026-11-06"}),
    ("東京都", "杉並区", "suginami", {
        "label": "杉並区（防水板：3/4・上限100万円。個人向けと読める）",
        "rate_label": "工事費の3/4、1棟100万円。区内で工事をする個人が対象と読め、分譲マンションの管理組合が使えるかは分からない",
        "cautions": ["JIS の止水性能 Ws-3 相当以上の書類が要ります。", _TOKYO_TOO],
        "url": "https://www.city.suginami.tokyo.jp/guide/machi/chisui/1005070.html", "checked": "2026-11-06"}),
    ("神奈川県", "川崎市", "kawasaki", {
        "label": "川崎市（簡易型止水板の購入：1/2・上限10万円）",
        "rate_label": "簡易型止水板（工事が要らず取り外せるもの）の購入費の1/2、上限10万円。共同住宅の管理組合も申請できる。設置工事費は対象外",
        "cautions": ["交付決定の通知の前に買ったものは対象外です。令和8年5月25日〜令和9年1月29日、予算に達したら終了。"],
        "url": "https://www.city.kawasaki.jp/templates/prs/cmsfiles/contents/0000186/186598/houdouhappyousiryou.pdf", "checked": "2026-11-06",
        "covers": {"plate": {"rate": 1 / 2, "cap": 100000, "unit": 1}}}),
    ("栃木県", "宇都宮市", "utsunomiya", {
        "label": "宇都宮市（止水板：1/2・上限50万円）",
        "rate_label": "止水板等の設置工事の費用の1/2（千円未満切り捨て）、1申請50万円まで。対象の施設に「マンション」が明記されている。簡易型止水板は対象外",
        "cautions": ["申請できるのは施設を所有・賃借・管理する者です。管理組合がこれに当たるかは市に確かめます。", "対象地域は浸水想定区域、過去の浸水被害地域などです。"],
        "url": "https://www.city.utsunomiya.lg.jp/_res/projects/default_project/_page_/001/045/688/youkou.pdf", "checked": "2026-11-06",
        "covers": {"pillar": {"rate": 1 / 2, "cap": 500000, "unit": 1000}}}),
]
for _pref, _city, _key, _item in MUNICIPAL_SUBSIDIES:
    SUBSIDIES[_key] = _item

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
        "plan": {"pdf": "samples/plan_a.pdf", "png": "samples/plan_a.png", "section_png": "samples/section_a.png", "section_pdf": "samples/section_a.pdf", "system_png": "samples/system_a.png", "system_pdf": "samples/system_a.pdf", "dxf": {"plan": "samples/plan_a.dxf", "section": "samples/section_a.dxf", "system": "samples/system_a.dxf"}},
        "report": "samples/report_a.txt",
        "title": "竣工図 地下1階・1階平面図 ※架空の見本",
        "plan_size": (42000, 15000),
        "plan_frames": {0: (90, 105, 900), 1: (90, 530, 900)},
        "grid": {"x": [0, 6000, 12000, 18000, 24000, 30000, 36000, 42000], "y": [0, 7200, 15000]},
        "views": [
            {
                "name": "地下1階平面図",
                "rooms": _rooms(
                    (42000, 15000),
                    ("park", "機械式駐車場ピット", 0, 0, 18000, 7200, {"symbol": "pit"}),
                    ("aisle", "車路", 18000, 0, 25200, 7200, {"openings": [_door("bottom", 21000, "open", 1800)]}),
                    ("water_tank", "受水槽室", 25200, 0, 33000, 7200, {"symbol": "water_tank", "openings": [_door("bottom", 27000)]}),
                    ("store", "倉庫", 33000, 0, 42000, 7200),
                    ("corridor_b", "地下廊下", 0, 7200, 30000, 9000),
                    ("elec", "電気室", 0, 9000, 9000, 15000, {"symbol": "cubicle", "openings": [_door("top", 7200, "double", 1800)]}),
                    ("tr", "借室（東京電力\n供給用変圧器室）", 9000, 9000, 15000, 15000, {"symbol": "transformer", "openings": [_door("top", 13200, "double", 1500)]}),
                    ("pump", "給水ポンプ室", 15000, 9000, 24000, 15000, {"symbol": "pump", "openings": [_door("top", 22800)]}),
                    ("ev", "EV", 24000, 9000, 27000, 12000, {"symbol": "ev", "openings": [_door("top", 25500, "open", 1000)]}),
                    ("stair", "階段", 27000, 9000, 30000, 15000, {"symbol": "stair", "openings": [_door("top", 28500)]}),
                    ("ev_pit_room", "PS", 24000, 12000, 27000, 15000),
                    ("soil", "（土の中）", 30000, 7200, 42000, 15000, {"hatch": True}),
                ),
                "marks": [
                    {"kind": "conduit_hole", "label": "ケーブルを通す壁の穴", "x": 3000 / 42000, "y": 1.0},
                ],
            },
            {
                "name": "1階平面図",
                "rooms": _rooms(
                    (42000, 15000),
                    ("park_1f", "機械式駐車場", 0, 0, 18000, 7200, {"symbol": "parking", "openings": [_door("right", 3600, "shutter", 3000)]}),
                    ("slope", "車路スロープ", 18000, 0, 25200, 7200, {"symbol": "slope", "openings": [_door("top", 21600, "shutter", 4500)]}),
                    ("garbage", "ごみ置場", 25200, 0, 29400, 7200, {"openings": [_door("top", 27300, "double", 1500)]}),
                    ("bike", "駐輪場", 29400, 0, 42000, 7200, {"symbol": "bike", "openings": [_door("top", 36000, "double", 1800)]}),
                    ("trunk", "トランクルーム", 0, 7200, 9000, 15000, {"openings": [_door("bottom", 4500)]}),
                    ("office", "管理員室", 9000, 7200, 15000, 15000, {"openings": [_door("right", 10800), _door("bottom", 12000, "window", 2400)]}),
                    ("hall", "エントランスホール", 15000, 7200, 24000, 12600, {"openings": [_door("bottom", 19500, "sliding", 2400)]}),
                    ("wind", "風除室", 15000, 12600, 24000, 15000, {"openings": [_door("bottom", 19500, "sliding", 2400)]}),
                    ("ev_1f", "EV", 24000, 7200, 27000, 10200, {"symbol": "ev", "openings": [_door("left", 8700, "open", 1000)]}),
                    ("stair_1f", "階段", 27000, 7200, 30000, 15000, {"symbol": "stair"}),
                    ("mail", "メールコーナー", 24000, 10200, 27000, 15000),
                    ("assembly", "集会室", 30000, 7200, 42000, 15000, {"openings": [_door("left", 12600), _door("bottom", 36000, "window", 3600)]}),
                ),
                "marks": [
                    {"kind": "road"},
                    {"kind": "hh", "label": "HH（東電・高圧）", "x": 3000 / 42000, "y": 1.145},
                    {"kind": "conduit", "label": "引込管路", "x": 3000 / 42000, "y": 1.145, "x2": 3000 / 42000, "y2": 1.0},
                ],
            },
        ],
        "pins": [
            {"key": "ア", "target": "elec", "view": 0, "x": 0.0714, "y": 0.95, "title": "ケーブルを通す壁の穴", "how_water": "道路の下の電線の管を通って、電気室の壁の穴から水が入ることがあります。玄関の止水板では防げない経路です。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。穴が止水されているかを見てもらいます。部屋の中の確認は主任技術者が立ち会い、業者はその指示に従い、盤に触れません。", "who": "管理会社から防水・設備業者へ現地調査を依頼（部屋の中の確認は、電気の月次点検のときに合わせて頼む）", "who_kind": "engineer", "memo": 2, "focus": "elec"},
            {"key": "イ", "target": "pump", "view": 0, "x": 0.46, "y": 0.8, "title": "ポンプのスイッチ盤", "how_water": "盤の下の端より水が上がると、ポンプが止まり全戸断水につながります。受電が生きていても水は止まります。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。盤の下の端の高さと、部屋の床の高さ（外の地面と比べて）を測ってもらいます。", "who": "管理会社から給水ポンプの保守業者へ", "who_kind": "contractor", "memo": 3, "focus": "pump"},
            {"key": "ウ", "target": "slope", "view": 1, "x": 0.5143, "y": 0.24, "title": "地下へ降りる車路スロープ", "how_water": "前の道路の水が、スロープを伝って地下へ流れ込みます。", "check": "スロープの入口の高さと、止水板を置けるか。外から見てかまいません。冠水中は近づかず、水に入りません。", "who": "外から見てよい（住民、管理会社）", "who_kind": "outside", "memo": 1, "focus": "slope"},
            {"key": "エ", "target": "tr", "view": 0, "x": 0.2857, "y": 0.8, "title": "東京電力の変圧器の部屋", "how_water": "ここが浸かると各戸の電気が止まります。部屋の中の機器の高さは建物の側から分かりません。", "check": "穴や管路に、だれも栓や止水材を入れません。扉は開けず、浸水時は近づきません。扉と穴の分担は管理会社から東京電力パワーグリッドへ照会します。", "who": "管理会社から東京電力パワーグリッドへ照会", "who_kind": "tepco", "memo": 1, "focus": "tr"},
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
        "plan": {"pdf": "samples/plan_b.pdf", "png": "samples/plan_b.png", "section_png": "samples/section_b.png", "section_pdf": "samples/section_b.pdf", "system_png": "samples/system_b.png", "system_pdf": "samples/system_b.pdf", "dxf": {"plan": "samples/plan_b.dxf", "section": "samples/section_b.dxf", "system": "samples/system_b.dxf"}},
        "report": "samples/report_b.txt",
        "title": "竣工図 1階平面図 ※架空の見本",
        "plan_size": (30000, 13200),
        "plan_frames": {0: (110, 140, 1150)},
        "grid": {"x": [0, 6000, 12000, 18000, 24000, 30000], "y": [0, 5400, 13200]},
        "views": [
            {
                "name": "1階平面図",
                "rooms": _rooms(
                    (30000, 13200),
                    ("parking_flat", "平置き駐車場", 0, 0, 15000, 5400, {"symbol": "parking_flat", "openings": [_door("top", 7500, "open", 6000)]}),
                    ("bike", "駐輪場", 15000, 0, 24000, 5400, {"symbol": "bike", "openings": [_door("top", 19500, "double", 1800)]}),
                    ("ev", "EV", 24000, 0, 27000, 2700, {"symbol": "ev", "openings": [_door("bottom", 25500, "open", 1000)]}),
                    ("stair", "階段", 27000, 0, 30000, 5400, {"symbol": "stair"}),
                    ("hall_back", "ホール", 24000, 2700, 27000, 5400, {"openings": [_door("right", 4900)]}),
                    ("panel_room", "共用分電盤室", 0, 5400, 8100, 13200, {"symbol": "panel_stand", "openings": [_door("bottom", 4050, "double", 1500)]}),
                    ("tr", "借室（東京電力\n供給用変圧器室）", 8100, 5400, 15600, 13200, {"symbol": "transformer", "openings": [_door("bottom", 11850, "double", 1500)]}),
                    ("pump", "給水ポンプ室", 15600, 5400, 22200, 13200, {"symbol": "pump_stand", "openings": [_door("bottom", 18900)]}),
                    ("hall", "エントランス", 22200, 5400, 30000, 13200, {"openings": [_door("bottom", 26100, "sliding", 2100), _door("top", 25500, "open", 2400)]}),
                ),
                "marks": [
                    {"kind": "door_low", "label": "坂下側出入口・足元換気口", "x": 4050 / 30000, "y": 1.0},
                    {"kind": "road", "label": "敷地内通路（坂の下の側）", "slope": True},
                    {"kind": "pole", "label": "電柱", "x": -0.022, "y": 1.1, "x2": 0, "y2": 0.86},
                ],
            },
        ],
        "pins": [
            {"key": "ア", "target": "panel_room", "view": 0, "x": 0.135, "y": 0.8, "title": "共用部のおおもとのスイッチ盤", "how_water": "地下はありませんが、床が通路より少し高いだけなら、浅い水でも盤の下の端に届くことがあります。", "check": "盤の下の端の高さを測ってもらいます。盤の扉を開けずに測ります。開ける必要があるかは電気工事の業者が判断します。防水業者や管理会社は扉を開けず、盤や電線に触れません。住民、理事、管理員は部屋に入りません。", "who": "管理会社から電気工事の業者へ（主任技術者はいない建物です）", "who_kind": "contractor", "memo": 2, "focus": "panel_room"},
            {"key": "イ", "target": "pump", "view": 0, "x": 0.63, "y": 0.8, "title": "ポンプのスイッチ盤", "how_water": "架台の上の盤でも、下の端より水が上がると、ポンプが止まり断水につながります。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。盤の下の端の高さと、部屋の床の高さを測ってもらいます。", "who": "管理会社から給水ポンプの保守業者へ", "who_kind": "contractor", "memo": 3, "focus": "pump"},
            {"key": "ウ", "target": "door", "view": 0, "x": 0.135, "y": 1.0, "title": "坂の下の側の扉と足元の換気口", "how_water": "丘と谷が入り組んだ土地では、坂の下の側に水が集まり、扉の下や足元の換気口から入ることがあります。", "check": "扉の下の段差と換気口の高さ。外から見てかまいません。冠水中は近づかず、水に入りません。", "who": "外から見てよい（住民、管理会社）", "who_kind": "outside", "memo": 1, "focus": "door"},
            {"key": "エ", "target": "tr", "view": 0, "x": 0.395, "y": 0.8, "title": "東京電力の変圧器の部屋", "how_water": "この建物では、ここが浸かると各戸と共用部の両方の電気が止まります。部屋の中の機器の高さは建物の側から分かりません。", "check": "穴や管路に、だれも栓や止水材を入れません。扉は開けず、浸水時は近づきません。扉と穴の分担は管理会社から東京電力パワーグリッドへ照会します。", "who": "管理会社から東京電力パワーグリッドへ照会", "who_kind": "tepco", "memo": 1, "focus": "tr"},
        ],
    },
    "c": {
        "id": "c",
        "name": "あおぞらタワー（架空）",
        "button": "見本C あおぞらタワー（架空）／東京都 大島2丁目",
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
        "plan": {"pdf": "samples/plan_c.pdf", "png": "samples/plan_c.png", "section_png": "samples/section_c.png", "section_pdf": "samples/section_c.pdf", "system_png": "samples/system_c.png", "system_pdf": "samples/system_c.pdf", "dxf": {"plan": "samples/plan_c.dxf", "section": "samples/section_c.dxf", "system": "samples/system_c.dxf"}},
        "report": "samples/report_c.txt",
        "title": "竣工図 地下1階・1階平面図 ※架空の見本",
        "plan_size": (36000, 36000),
        "plan_frames": {0: (80, 130, 580), 1: (770, 130, 580)},
        "grid": {"x": [0, 12000, 24000, 36000], "y": [0, 12000, 24000, 36000]},
        "views": [
            {
                "name": "地下1階平面図",
                "rooms": _rooms(
                    (36000, 36000),
                    ("park", "機械式駐車場ピット", 0, 0, 16000, 12000, {"symbol": "pit"}),
                    ("aisle", "車路", 16000, 0, 25000, 12000, {"openings": [_door("bottom", 20500, "open", 1800)]}),
                    ("tank", "雨水貯留槽（地下）", 25000, 0, 36000, 12000, {"hatch": True}),
                    ("store", "倉庫", 0, 12000, 12000, 21000, {"openings": [_door("bottom", 6000)]}),
                    ("ev", "EV", 12000, 12000, 18000, 21000, {"symbol": "ev_bank", "openings": [_door("bottom", 15000, "open", 2400)]}),
                    ("stair", "階段", 18000, 12000, 24000, 21000, {"symbol": "stair", "openings": [_door("bottom", 21000)]}),
                    ("water_tank", "受水槽室", 24000, 12000, 36000, 21000, {"symbol": "water_tank", "openings": [_door("bottom", 30000)]}),
                    ("corridor_b", "地下廊下", 0, 21000, 36000, 24000),
                    ("elec", "受変電室", 0, 24000, 11000, 36000, {"symbol": "cubicle", "openings": [_door("top", 8500, "double", 1800)]}),
                    ("tr", "借室（東京電力\n供給用変圧器室）", 11000, 24000, 18000, 36000, {"symbol": "transformer", "openings": [_door("top", 14500, "double", 1500)]}),
                    ("gen", "非常用\n発電機室", 18000, 24000, 25000, 36000, {"symbol": "generator", "openings": [_door("top", 21500, "double", 1500)]}),
                    ("pump", "給水ポンプ室", 25000, 24000, 36000, 36000, {"symbol": "pump", "openings": [_door("top", 30500)]}),
                ),
                "marks": [
                    {"kind": "conduit_hole", "label": "ケーブルを通す壁の穴", "x": 3000 / 36000, "y": 1.0},
                ],
            },
            {
                "name": "1階平面図",
                "rooms": _rooms(
                    (36000, 36000),
                    ("park_1f", "機械式駐車場", 0, 0, 16000, 12000, {"symbol": "parking"}),
                    ("slope", "車路スロープ", 16000, 0, 25000, 12000, {"symbol": "slope", "openings": [_door("top", 20500, "shutter", 5400)]}),
                    ("garden", "公開空地", 25000, 0, 36000, 12000),
                    ("bike", "駐輪場", 0, 12000, 12000, 24000, {"symbol": "bike", "openings": [_door("left", 18000, "double", 1800)]}),
                    ("ev_1f", "EV", 12000, 12000, 18000, 21000, {"symbol": "ev_bank", "openings": [_door("bottom", 15000, "open", 2400)]}),
                    ("stair_1f", "階段", 18000, 12000, 24000, 21000, {"symbol": "stair", "openings": [_door("bottom", 21000)]}),
                    ("lounge", "ラウンジ", 24000, 12000, 36000, 24000, {"openings": [_door("left", 22500, "open", 2400)]}),
                    ("office", "防災センター", 0, 24000, 12000, 36000, {"openings": [_door("right", 26000), _door("bottom", 6000)]}),
                    ("lobby", "エントランスホール", 12000, 21000, 24000, 32000),
                    ("wind", "風除室", 12000, 32000, 24000, 36000, {"openings": [_door("top", 18000, "sliding", 3000), _door("bottom", 18000, "sliding", 3000)]}),
                    ("mail", "メールコーナー", 24000, 24000, 36000, 36000, {"openings": [_door("left", 27000, "open", 2400)]}),
                ),
                "marks": [
                    {"kind": "basin", "label": "雨水ます", "x": 0.86, "y": 0.2},
                    {"kind": "road"},
                    {"kind": "hh", "label": "HH（東電・高圧）", "x": 3000 / 36000, "y": 1.055},
                    {"kind": "conduit", "label": "引込管路", "x": 3000 / 36000, "y": 1.055, "x2": 3000 / 36000, "y2": 1.0},
                ],
            },
        ],
        "pins": [
            {"key": "ア", "target": "elec", "view": 0, "x": 0.0833, "y": 0.975, "title": "ケーブルを通す壁の穴", "how_water": "道路の下の電線の管を通って、受電の箱の部屋の壁の穴から水が入ることがあります。玄関の止水板では防げない経路です。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。穴が止水されているかを見てもらいます。部屋の中の確認は主任技術者が立ち会い、業者はその指示に従い、盤に触れません。", "who": "管理会社から防水・設備業者へ現地調査を依頼（部屋の中の確認は、電気の月次点検のときに合わせて頼む）", "who_kind": "engineer", "memo": 2, "focus": "elec"},
            {"key": "イ", "target": "pump", "view": 0, "x": 0.85, "y": 0.85, "title": "ポンプのスイッチ盤", "how_water": "盤の下の端より水が上がると、ポンプが止まり全戸断水につながります。高層階ほど階段で水を運ぶのが難しくなります。", "check": "確かめるのは「確かめる人」の欄の人です。住民、理事、管理員は部屋に入りません。盤の下の端の高さと、部屋の床の高さを測ってもらいます。", "who": "管理会社から給水ポンプの保守業者へ", "who_kind": "contractor", "memo": 3, "focus": "pump"},
            {"key": "ウ", "target": "tank", "view": 0, "x": 0.85, "y": 0.2, "title": "雨水ますと地下の貯留タンク", "how_water": "敷地の水が雨水ますからタンクへ流れ込み、満水になると地下の蓋からあふれることがあります（武蔵小杉の例。建築設備技術者協会の調査など）。", "check": "蓋は開けません。導入管に止水バルブがあるか、タンクの蓋に耐水圧のロックがあるかを、竣工図で確かめ、現地は業者に見てもらいます。", "who": "管理会社が竣工図で確かめ、設備業者へ現地調査を依頼", "who_kind": "contractor", "memo": 2, "focus": "tank"},
            {"key": "エ", "target": "tr", "view": 0, "x": 0.4028, "y": 0.85, "title": "東京電力の変圧器の部屋", "how_water": "ここが浸かると各戸の電気が止まります。部屋の中の機器の高さは建物の側から分かりません。", "check": "穴や管路に、だれも栓や止水材を入れません。扉は開けず、浸水時は近づきません。水防ラインの協議は管理組合と管理会社が東京電力パワーグリッドと行います。", "who": "管理会社から東京電力パワーグリッドへ照会", "who_kind": "tepco", "memo": 1, "focus": "tr"},
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
    if answers.get("rooms_floor") in ("ground", "upper") or answers.get("basement") == "no":
        return "b"
    if (answers.get("floors") or 0) >= 20:
        return "c"
    # 画面で選んだ「近い形」は、質問の答えより弱い手がかりとして使う。
    if answers.get("type") in SAMPLES:
        return answers["type"]
    return fallback if fallback in ("a", "c") else "a"


def _in_prefecture(label: str, pref: str) -> bool:
    """「東京都」の書き方と、公開地図の「…, 東京, …」の書き方の両方を見る。"""
    short = pref[:-1] if pref.endswith(("都", "県")) else pref
    return pref in label or bool(re.search(rf"(^|[,、\s]){short}([,、\s]|$)", label))


def region_of(label: str) -> str:
    """住所の市区町村から、補助の欄を選ぶ。同じ名前の区がほかの市にもあるので、都県もそろったときだけ区市を選ぶ。"""
    for pref, city, key, _item in MUNICIPAL_SUBSIDIES:
        if city in label and _in_prefecture(label, pref):
            return key
    if "千葉市" in label:
        return "chiba"
    if "横浜市" in label:
        return "yokohama"
    if _in_prefecture(label, "東京都"):
        return "tokyo"
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
        px, py = plan_point(sample, pin["view"], pin["x"], pin["y"])
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
        "plan_focus": plan_focus(sample),
    }


def plan_focus(sample: dict) -> List[float]:
    """平面図の用紙のうち、図のある範囲（用紙に対する割合の左・上・右・下）。画面では、この範囲に寄せて図を大きく見せる。"""
    width, height = sample["plan_size"]
    boxes = [(left, top, left + w, top + w * height / width) for left, top, w in sample["plan_frames"].values()]
    x0 = max(0, min(b[0] for b in boxes) - 40)
    y0 = max(0, min(b[1] for b in boxes) - 40)
    x1 = min(PLAN_WIDTH, max(b[2] for b in boxes) + 40)
    y1 = min(PLAN_HEIGHT, max(b[3] for b in boxes) + 70)
    return [round(x0 / PLAN_WIDTH, 4), round(y0 / PLAN_HEIGHT, 4), round(x1 / PLAN_WIDTH, 4), round(y1 / PLAN_HEIGHT, 4)]
