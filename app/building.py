"""見本の建物の設備を判定し、最上段の一行、処置、依頼メモ、水の位置ごとの想定を作る。

判定はここのルールだけで決める。Claude には書き換えさせない。
日数を建物ごとに計算しない。固定の cm の数字を置かない。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

from . import samples
from .state import CLEAR, DRAWING, DOCUMENT, QUESTION, RISK, UNCONFIRMED, VERDICT_LABELS, Equipment

# 画面に出す固定の文。言い換えず、折りたたまない。
FIXED = {
    "disclaimer_1": "本シートは公開データと入力情報から作成したもので、現地の判定や安全を保証するものではない。浸水中は電気室・借室（東京電力の変圧器の部屋）・ポンプ室・EVピットに立ち入らず、復電の可否は電気主任技術者が判断する",
    "model": "説明用の模型で、部屋の位置と高さはあなたの建物のものではありません。",
    "ordinary": "ふだんも、主任技術者の同行なしに電気室に入りません。東京電力の変圧器の部屋には、東京電力パワーグリッドの許可と立会いなしにだれも入りません。",
    "ordinary_no_engineer": "ふだんも、電気工事の業者の立会いなしに、共用部のおおもとのスイッチ盤の部屋に入りません。東京電力の変圧器の部屋には、東京電力パワーグリッドの許可と立会いなしにだれも入りません。",
    "tank_outside": "雨水ますから貯留タンクへの経路は、この切り替えに含めていません。",
    "disclaimer_1_no_engineer": "本シートは公開データと入力情報から作成したもので、現地の判定や安全を保証するものではない。浸水中は電気室・借室（東京電力の変圧器の部屋）・ポンプ室・EVピットに立ち入らず、復電の可否は電気主任技術者が判断する（電気主任技術者を選任していない建物では、借室は東京電力パワーグリッドの確認を待ち、マンション側は電気工事の業者が点検・測定した結果を書面で受けて管理組合が判断する。どちらも済むまで電気を戻さない）",
    "water_not_entry": "水の位置は、立ち入ってよい高さではありません。水が残る部屋には、深さにかかわらず入りません。水が引いても、借室（東京電力の変圧器の部屋）は東京電力パワーグリッド、マンション側の部屋は主任技術者（いない建物では電気工事業者）が安全を確かめて入ってよいと指示するまで、住民、理事、管理員は入りません。",
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

# ここから下は、ノートの「実現したい機能」から足した固定の文。上の承認済みの文は変えない。
# 依頼メモに足す項目。
MEMO_WATER_SUPPLY = "管理会社が竣工図の給水設備図で、給水の方式と、ポンプ・制御盤がどの階にあるかを確かめます。"
MEMO_DAMP_LOOK = "現地調査のときに、盤の底の錆、水滴や結露の跡、ケーブルを通す壁の穴の充填材の劣化、ケーブルの端末と接続部の防水処理を見てもらいます。床下の点検口（ピット）の蓋や扉の隙間もあわせて見てもらいます（判定には使いません）。盤の扉を開けるかは主任技術者が決め、防水業者や管理会社は盤に触れません。"
MEMO_DAMP_LOOK_NO_ENGINEER = "現地調査のときに、盤の底の錆、水滴や結露の跡、ケーブルや配管を通す穴の充填材の劣化、ケーブルの端末と接続部の防水処理を見てもらいます。床下の点検口（ピット）の蓋や扉の隙間もあわせて見てもらいます（判定には使いません）。盤の扉を開けるかは電気工事の業者が決め、防水業者や管理会社は盤に触れません。"
MEMO_PUMP_CHECK = "管理会社が保守会社に、排水ポンプ（地下の床、機械式駐車場の掘り込み、汚水の汲み上げ）の動作と点検の記録を聞きます。"
MEMO_FREE_SURVEY = "止水板メーカーの中には、無料の現地診断を受け付けているところがあります。受付の枠が限られ、受けるかはメーカーが決めるので、業者の現地調査の代わりではなく、補助として使います。"
# 水（全戸）の行の二段目に添える一文。階数の閾値は置かない。
WATER_SUPPLY_NOTE = "給水がポンプによる方式なら、ポンプと制御盤は低い階にあることがあり、一番低い盤が床の近くにある可能性があります。方式は竣工図の給水設備図で確かめます。"
# オートロック・インターホンの行。機種によるので決めつけない。
LOCK_HEADLINE = "共用部の電気が止まったとき、オートロックの扉とインターホンがどう動くかは、まだ分かっていません。"
# 「長引くおそれ」の注記に足す目安（経産省の検討会資料、facts の済の行。一般的な目安で、特定の建物の実績ではない）。
TOP_NOTE_GUIDE_DAYS = "供給用変圧器や受電設備が浸かった場合、排水開始から仮復旧まで4〜7日程度（経産省の検討会資料。一般的な目安で、特定の建物の実績ではない）。"
# A4 だけに出す千葉の見通し（共同通信 2026/8/22。見通しで実績ではないので「かかった」とは書かない）。
A4_NOTE_CHIBA = "2026年8月の千葉では断水が1週間以上続き、復旧まで1か月以上の見通しを示すところもあると報じられた（共同通信 2026/8/22。見通しで、実績ではない）。"
STREET_VIEW_NOTE = "スロープや出入口の段差は、敷地の外からの写真（ストリートビューなど）でも見られます。"
DAMP_CONFIRM = "管理会社から建物・防水の業者へ現地調査を依頼します（部屋の中の確認は主任技術者が立ち会い、業者は盤に触れません）。"
DAMP_CONFIRM_NO_ENGINEER = "管理会社から防水の業者へ現地調査を依頼します（盤の部屋では電気工事の業者が立ち会い、防水業者は目で見るだけです）。"
GEN_HEADLINE_ANSWERED = "非常用発電機があるとの答えです。置き場所の階と床の高さは、まだ分かっていません。火災のときのための設備で、水害の長い停電に足りるとは言えません。"
# 地中引込の高圧ケーブルの確認先。主任技術者のいない建物（借室のみ型）は東京電力パワーグリッドへの照会にする。
MEMO_CABLE_NO_ENGINEER = "管理会社から東京電力パワーグリッドに、引込みの高圧ケーブルと管路がどちらの持ち物か、大雨や浸水のあとにどんな確認をするかを照会します。歩道ぎわの蓋は開けません。"
MEMO_FEED_FORM = "管理会社が単線結線図で、電気の引込みが地中か空中かを確かめます。"
# くぼ地の目安に当たるときに、トイレ・排水の行と依頼メモに添える理由。
HOLLOW_REASON = "くぼ地の目安に当たり、排水口や雨水ますから水が上がる経路もありうるため。逆流が起きるかは判定していません。"
HOLLOW_BADGES = ("くぼ地の目安", "周囲より低い凹み（目安）")
# 警戒レベル4の満潮の分岐に、貯留槽と止水弁がともに「あり」の建物だけ添える文。誰がいつ閉めるかを事前に決める項目で、浸水中の操作は誘導しない。
RAIN_TANK_VALVE = "雨水の導入管の止水弁も、事前に決めた担当が閉めます（誰がいつ閉めるかは理事会で先に決めておきます。水が来てからは近づきません）。"
# 設備の行を「問題なし」にする道（図面で不在／2階以上／止水施工済み）。三分類のまま、「分からない＝危険」にしない。
CLEAR_NOT_ENTRY = "「問題なし」は、部屋への立ち入りを許すという意味ではありません。"
ABSENT_HEADLINE = "該当する設備図に描かれていないことを、図面の読み取りのあとに人が確かめました。"
UPPER_HEADLINE = "想定の深さより明確に上の階（2階以上・屋上）にあることを、図面の読み取りのあとに人が確かめました。"
SEALED_HEADLINE = "修繕履歴か竣工図に、この穴の止水施工済みと明記されています。対策済みとみるのはこの穴だけで、部屋全体ではありません。後の点検報告書に湿気や漏水の指摘があれば、未確認に戻します。"
TR_ABSENT_HEADLINE = "東京電力の変圧器の部屋は、電気設備図に描かれていないことを人が確かめました。各戸へ電気を送る東京電力の設備がどこにあるかは分かっていません。"
TR_ABSENT_CONFIRM = "管理会社が、各戸へ電気を送る設備の種類と位置を東京電力パワーグリッドに照会します。"
# 高圧一括受電の建物（借室なし。各戸もマンション側の受電設備から）。書類と図面で分かったときだけ。
BULK_LABEL = "各戸の電気（マンション側の受電設備から）"
BULK_HEADLINE = "東京電力の変圧器の部屋は図面に描かれておらず、各戸の電気もマンション側の受電設備から来ると書類で確かめた建物です。受電設備が浸かると全館が止まり、主遮断器を開放した場合も全館が止まります。"
CHAIN_NOTE_BULK = "受電設備が浸かると全館が止まり、主遮断器を開放した場合も全館が止まる建物です（高圧一括受電。書類と図面で確認）。"
CHAIN_NOTE_TR = "借室のある建物では、マンション側の受電設備が浸かって止まるのは共用部だけです。各戸の電気は東京電力の変圧器の部屋しだいです。"
CHAIN_NOTE_NO_ENGINEER = "共用部のおおもとのスイッチ盤が浸かって止まるのは共用部だけです。東京電力の変圧器の部屋が浸かると、各戸と共用部の両方が止まります。"
# 高さの入力。本人が入れた値をそのまま出すだけで、浸かる・浸からないは計算しない。
HEIGHT_SOURCES = {"drawing": "竣工図", "measured": "実測", "hearing": "聞き取り"}
HEIGHT_FIELDS = {
    "panel_bottom": ("給水ポンプの制御盤の下の端（床から）", "床から"),
    "pump_floor": ("ポンプの部屋の床（外の地面との差）", "外の地面との差"),
    "elec_floor": ("電気の部屋の床（外の地面との差）", "外の地面との差"),
}
WATER_MEASURED_CONFIRM = "盤の下の端と部屋の床の高さは、実測の入力値があります。付け替えが要るかは、管理会社がポンプの保守業者と見積りで確かめます。"
TOP_NOTE_LOCATION_CLEAR = "立地の五項目を、建物の位置の公開データで確かめました（出典は別紙）。"
# 規模（総戸数の区分）ごとの重点。戸数の区切りは仮の目安で済の出典がないので、画面に数字を出さない。
# 戸数から受電の形や主任技術者の有無は推定しない。重点は確かめる候補で、網羅ではない。
SCALE_LABELS = {"small": "小さめ", "mid": "中くらい", "large": "大きめ", "unknown": "分からない"}
SCALE_TAG = "この規模で重点"
SCALE_NOTE = "規模の区切りは仮の目安です。重点は確かめる候補で、全部ではありません。規模から受電の形や主任技術者の有無は決めません。ポンプの確認は設備業者（ポンプの保守業者）の担当です。"
SCALE_OUT_OF_SCOPE = "低圧で受電する小さな建物は、この道具の対象の外です（拡張の想定）。"
MEMO_SCALE_UNKNOWN = "管理会社が、総戸数と受電の形を点検報告書で確かめます。"
_SCALE_MID = [("entry", "ケーブルを通す壁の穴"), ("outside", "建物の周りの掘り下げた部分の足元の換気口"), ("water", "床置きのポンプ制御盤")]
SCALE_FOCUS = {
    "small": [("power", "受電設備の基礎の高さ"), ("water", "直結増圧の給水ポンプ"), ("ev", "エレベーターの底"), ("outside", "出入口と足元の換気口")],
    "mid": _SCALE_MID,
    "large": _SCALE_MID + [("tank", "雨水ますから地下の貯留槽への導入管の止水バルブ"), ("tank", "マンホールの蓋のロック"), ("tr", "水防ラインの東京電力パワーグリッドとの協議")],
}
SCALE_OUTSIDE_CONFIRM = "管理会社が外から見える所を見て、入口や換気口の高さと止水板を置けるかを確かめます。冠水中は近づきません。"
SCALE_TANK_HEADLINE = "この規模の建物で重点に確かめる候補です。雨水を地下にためる槽があるか、あれば導入管の止水バルブとマンホールの蓋のロックがどうなっているかは、まだ分かっていません。"
# 大雨が近づいたときの手順の三行目。A4（web/panels.js の rain[2]）と同じ文を、ここに写して両方で使う（文は変えない）。
RAIN_THIRD = {
    "unsure": "電気の部屋や変圧器の部屋に水が来そうになったら：管理員か理事長が東京電力パワーグリッドと管理会社と、いれば主任技術者に連絡します。部屋に入りません。在宅で医療機器を使う人へ先に知らせ、全戸へ排水しないよう放送します。",
    "engineer": "電気の部屋に水が来そうになったら：管理員か理事長が主任技術者に連絡します。操作は主任技術者の指示で行い、電気の部屋には、水が来る前も後も、主任技術者の同行なしに入りません。在宅で医療機器を使う人へ先に知らせ、止めると同時に全戸へ排水しないよう放送します。",
    "no_engineer": "盤の部屋や変圧器の部屋に水が来そうになったら：管理員か理事長が東京電力パワーグリッドと管理会社に連絡します。部屋に入りません。在宅で医療機器を使う人へ先に知らせ、全戸へ排水しないよう放送します。",
}
# 三行目の後ろに足す文。盤下端の手前で遮断する仮の cm は置かない。
RAIN_CUT_PUMP = {
    "engineer": "遮断すると排水ポンプも止まるので、遮断するかは主任技術者が排水への影響もあわせて判断し、遮断だけを単独で決めません。",
    "unsure": "電気を止めると排水ポンプも止まるので、止めるかは主任技術者（いない建物では東京電力パワーグリッドと電気工事の業者）と、排水への影響もあわせて決めます。",
    "no_engineer": "電気を止めると排水ポンプも止まるので、止めるかは東京電力パワーグリッドと電気工事の業者に相談し、排水への影響もあわせて決めます。",
}
RAIN_TR_SCOPE = "借室のある建物では、主遮断器を開放した場合に止まるのは共用部だけで、各戸の電気は東京電力パワーグリッドの領分です。"
RAIN_TR_CALL = "借室の扉の前まで水が来たら、管理員か理事長が東京電力パワーグリッドに連絡します。扉は開けず、近づきません。連絡先と、連絡してから来てもらうまでの時間は、事前に確かめておきます。"
RAIN_DRAIN_BAN = "排水の禁止は、館内放送とSNSで全戸に知らせ、携帯トイレに切り替えてもらいます。"
RAIN_SET_OF_THREE = {
    "engineer": "手順には、在宅で医療機器を使う住民への配慮（本人の同意を得た事前の把握）、全戸への排水禁止の連絡、前もって電気を止めるかの判断（主任技術者が判断）の三つを組にして決めておきます。",
    "unsure": "手順には、在宅で医療機器を使う住民への配慮（本人の同意を得た事前の把握）、全戸への排水禁止の連絡、前もって電気を止めるかの判断（主任技術者がいれば主任技術者、いない建物では東京電力パワーグリッドと電気工事の業者に相談）の三つを組にして決めておきます。",
    "no_engineer": "手順には、在宅で医療機器を使う住民への配慮（本人の同意を得た事前の把握）、全戸への排水禁止の連絡、前もって電気を止めるかの判断（東京電力パワーグリッドと電気工事の業者に相談）の三つを組にして決めておきます。",
}
# 下水の逆流の行。書類（竣工図）で確かめる行の形だけにする。止まる設備の数には入れない。
BACKFLOW_HEADLINE = "下水の水位が上がったとき、低い階のトイレや排水口から水が逆流するかは、まだ分かっていません。"
BACKFLOW_CONFIRM = "管理会社が竣工図で、下水道が雨水と汚水を一緒に流す方式（合流式）か、排水管に逆止弁があるか、あれば平時に動作を確かめたかを確かめます。"
LOCK_CONFIRM = "管理会社が、オートロックの保守会社に、停電のときの扉の動き（開いたままか、閉じたままか）と、電池で動く時間を確かめます。"


def _engineer_kind(sample: dict) -> str:
    if sample.get("engineer_unsure"):
        return "unsure"
    return "engineer" if sample["has_chief_engineer"] else "no_engineer"


def rain_lines(sample: dict, confirmed: Optional[List[str]] = None) -> dict:
    """大雨が近づいたときの手順の三行目と、その後ろに足す文。警戒レベル3と4の行はここに持たない。"""
    kind = _engineer_kind(sample)
    answers = sample.get("answers") or {}
    has_tr = answers.get("tr") not in ("no", "unknown") and "absent:tr" not in (confirmed or []) and not is_bulk(sample, confirmed)
    extra = [RAIN_CUT_PUMP[kind]]
    if has_tr and kind == "engineer":
        # 主遮断器の話は、マンション側に受電設備がある建物だけ。
        extra.append(RAIN_TR_SCOPE)
    if has_tr:
        extra.append(RAIN_TR_CALL)
    extra.append(RAIN_DRAIN_BAN)
    return {"third": RAIN_THIRD[kind], "extra": extra, "set_of_three": RAIN_SET_OF_THREE[kind]}


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
    if floor in ("ground", "upper"):
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


def heights(sample: dict) -> dict:
    """高さの入力を読む。数でないもの、あり得ない大きさのものは捨てる。"""
    given = (sample.get("answers") or {}).get("heights") or {}
    result = {}
    if not isinstance(given, dict):
        return result
    for key, (label, lead) in HEIGHT_FIELDS.items():
        item = given.get(key)
        if not isinstance(item, dict):
            continue
        value = item.get("cm")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not -10000 <= value <= 10000:
            continue
        number = int(value) if float(value).is_integer() else round(float(value), 1)
        raw = item.get("source")
        # 出どころは決まった語（drawing／measured／hearing）か、入力した人や書類の名前の短い文。
        if raw in HEIGHT_SOURCES:
            source = HEIGHT_SOURCES[raw]
        elif isinstance(raw, str) and raw.strip():
            source = raw.strip()[:30]
        else:
            source = "出どころ未選択"
        measured = raw == "measured" or source == "実測"
        result[key] = {"key": key, "label": label, "cm": number, "source": source, "measured": measured, "text": f"入力値：{lead} {number}cm（{source}）"}
    return result


def is_bulk(sample: dict, confirmed: Optional[List[str]] = None) -> bool:
    """高圧一括受電（借室なし＋受電設備あり＋各戸もマンション側から）。図面と書類の両方で分かったときだけ。"""
    answers = sample.get("answers") or {}
    return (
        bool(sample.get("has_chief_engineer"))
        and not sample.get("engineer_unsure")
        and "absent:tr" in (confirmed or [])
        and answers.get("homes_feed") == "mansion"
        and bool(answers.get("homes_feed_documented"))
    )


def _make_clear(row: dict, headline: str, summary: str, label: Optional[str] = None, verdict_label: str = "問題なし", evidence: str = DRAWING) -> None:
    row.update(
        verdict=CLEAR,
        verdict_label=verdict_label,
        headline=headline,
        summary=summary,
        confirm_by=None,
        confirm_short=None,
        evidence=evidence,
        confirmed_by_person=evidence == DRAWING,
        details=[CLEAR_NOT_ENTRY],
    )
    if label:
        row["label"] = label


# 「2階以上」と図面で確かめられる部屋と、その行。
_UPPER_ROWS = {"pump": "water", "elec": "power", "panel_room": "power", "tr": "tr"}
# 「描かれていない」と図面で確かめられる設備と、その行。借室は別に扱う。
_ABSENT_ROWS = {"tank": "tank", "gen": "gen", "park": "park", "ev": "ev", "drain": "drain", "pump": "water"}
# 電気の部屋が描かれていなくても、共用部の電気はどこかから来るので、行は「問題なし」にしない。
ABSENT_POWER_NOTE = "この部屋は図面に描かれていないと人が確かめました。共用部の電気がどこから来るかは、別に確かめます。"


def _clear_paths(rows: List[dict], sample: dict, confirmed: List[str]) -> None:
    answers = sample.get("answers") or {}
    by_key = {row["key"]: row for row in rows}
    for room, key in _UPPER_ROWS.items():
        if f"upper:{room}" in confirmed and key in by_key:
            # 高圧か低圧かが分からない建物でも、2階以上と図面で確かめた部屋は問題なし（2026-11-06）。
            if key == "power" and not sample.get("engineer_unsure") and (room == "elec") != bool(sample["has_chief_engineer"]):
                continue
            _make_clear(by_key[key], UPPER_HEADLINE, "2階以上と図面で確認")
    for room, key in _ABSENT_ROWS.items():
        if f"absent:{room}" in confirmed and key in by_key:
            _make_clear(by_key[key], ABSENT_HEADLINE, "図面に描かれていないと確認")
    power = by_key.get("power")
    if power and power["verdict"] != CLEAR and ("absent:elec" in confirmed or "absent:panel_room" in confirmed):
        power["details"].append(ABSENT_POWER_NOTE)
    tr = by_key.get("tr")
    if tr and "absent:tr" in confirmed and "upper:tr" not in confirmed:
        if is_bulk(sample, confirmed):
            power = by_key.get("power") or {}
            tr.update(
                label=BULK_LABEL,
                verdict=power.get("verdict", UNCONFIRMED),
                verdict_label=power.get("verdict_label", tr["verdict_label"]),
                headline=BULK_HEADLINE,
                summary="受電設備が浸かると全館が止まる",
                confirm_by=power.get("confirm_by"),
                confirm_short=power.get("confirm_short"),
                memo_section=None,
                evidence=DOCUMENT,
                details=[],
            )
        else:
            tr.update(
                verdict=UNCONFIRMED,
                verdict_label=VERDICT_LABELS[UNCONFIRMED],
                headline=TR_ABSENT_HEADLINE,
                summary="部屋は図面になし。東京電力の設備の位置は未確認",
                confirm_by=TR_ABSENT_CONFIRM,
                confirm_short="管理会社→東京電力PG",
                memo_section=1,
                evidence=DRAWING,
                details=[],
            )
    entry = by_key.get("entry")
    # 湿気の行が出ている（後の点検で指摘がある）建物では、止水施工済みの記載があっても未確認のまま。
    if entry and answers.get("sealed") == "yes" and answers.get("damp") != "yes" and "damp" not in by_key:
        _make_clear(entry, SEALED_HEADLINE, "止水施工済みと記載あり（この穴だけ）", verdict_label="問題なし（対策済）", evidence=DOCUMENT)


_LEVEL_WORDS = {"basement": "地下", "ground": "1階", "upper": "2階以上", "absent": "図面にない"}


def room_level(sample: dict, key: str, confirmed: Optional[List[str]]) -> Optional[str]:
    """部屋ごとの階（2026-11-06 本人の指示「部屋ごとに階を見る」）。

    図面で確かめた（confirmed）ときだけ basement / ground / upper / absent を返す。確かめていなければ None。
    階は、画面の答え（answers.room_floors）→ 借りた見本の図面の階 → 全体の答え（rooms_floor）の順に見る。
    """
    confirmed = confirmed or []
    if f"upper:{key}" in confirmed:
        return "upper"
    if f"absent:{key}" in confirmed:
        return "absent"
    if key not in confirmed:
        return None
    answers = sample.get("answers") or {}
    given = (answers.get("room_floors") or {}).get(key)
    if given in ("basement", "ground"):
        return given
    floor = _room_on_floor(sample, key)
    if floor:
        return "basement" if "地下" in floor else "ground"
    return answers.get("rooms_floor") if answers.get("rooms_floor") in ("basement", "ground") else None


def judge_equipment(sample: dict, confirmed: List[str], location_risk: bool, document_read: bool = False, hollow: bool = False, location_clear: bool = False) -> List[dict]:
    """confirmed は、図面の読み取りのあとで人が確かめた部屋の種類。

    判定の決まり（2026-11-06 本人の決定）：図面で地下と確かめた部屋は、立地が「問題なし」でない限り「確定」。
    1階の部屋は、盤の下端の高さが分かるまで「未確認」。2階以上・図面にないと確かめた部屋は「問題なし」。
    location_clear は、立地の5項目がすべて問題なし（建物の位置で確かめた）のとき。

    document_read は、点検報告書などの書類で受電の箱が地下にあると読めたこと。
    hollow は、立地の敷地の高低差の行に「くぼ地の目安」か「周囲より低い凹み」の札があること。
    """
    rows = []
    answers = sample.get("answers") or {}
    in_basement_known = rooms_in_basement(sample)
    upper = answers.get("rooms_floor") == "upper"
    place_word = "2階以上" if upper else {True: "地下", False: "1階", None: "階が未確認"}[in_basement_known]
    # 2階以上の答えでは、借りた見本の図面の階を出さない。
    floor_known = in_basement_known is not None and not upper
    unsure = sample.get("engineer_unsure")
    drawing = lambda key: key in confirmed  # noqa: E731
    evidence = lambda key, fallback: DRAWING if drawing(key) else fallback  # noqa: E731
    mount = sample["panel_mount"]
    given = heights(sample)

    pump_level = room_level(sample, "pump", confirmed)
    pump_word = _LEVEL_WORDS.get(pump_level, place_word)
    # 図面でポンプ室が地下と分かれば確定。床置きの盤は、立地にリスクがあれば階を問わず確定（浅い水で盤の下端に届く）。
    water_risk = (pump_level == "basement" and not location_clear) or (mount == "床置き" and location_risk)
    rows.append(
        _item(
            "water",
            "水（全戸）",
            RISK if water_risk else UNCONFIRMED,
            (f"ポンプ室は{pump_word}と{'図面で確かめました' if drawing('pump') else '聞いています'}（盤の形：{mount}）。浸かるとポンプが止まり、全戸断水になります。" if water_risk else f"ポンプのスイッチ盤の場所（{pump_word}）と高さは、まだ確かめていません（盤の形：{mount}）。盤の下の端より水が上がると、ポンプが止まり全戸断水につながります。")
            + ("床に近い位置にある盤は、浅い浸水でも浸かるおそれがあると考えられます。" if mount == "床置き" else ""),
            f"ポンプ室は{pump_word}（図面で確認）。浸かると全戸断水" if water_risk else f"ポンプの部屋（{pump_word}）の盤（{mount}）。高さは未確認",
            "管理会社が、給水ポンプの保守業者に、スイッチ盤の下の端の高さと部屋の床の高さを測ってもらいます。",
            "管理会社→ポンプの保守業者",
            3,
            floor=_room_on_floor(sample, "pump") if floor_known else None,
            evidence=evidence("pump", DOCUMENT if not sample.get("custom") else QUESTION),
            confirmed=drawing("pump"),
            always_confirm=True,
            details=[WATER_SUPPLY_NOTE] + (["確定とするのは水が来ることまでで、盤の下の端の高さは別に測ります。"] if water_risk else []),
        )
    )

    elec_level = room_level(sample, "elec", confirmed) or room_level(sample, "panel_room", confirmed)
    elec_word = _LEVEL_WORDS.get(elec_level, place_word)
    if unsure and elec_level == "basement" and not location_clear:
        # 高圧か低圧かが分かる前でも、図面で電気室が地下なら、地下が浸水すれば停電する（2026-11-06 本人の決定）。
        rows.append(
            _item(
                "power",
                "電気（共用部）",
                RISK,
                "電気室は地下と図面で確かめました。高圧か低圧か（保安会社の契約があるか）は未確認ですが、地下が浸水すれば共用部は停電し、給水ポンプも止まって断水します。",
                "電気室は地下（図面で確認）。浸かると共用部が停電し断水も",
                "高圧か低圧かは、管理会社が点検の記録か共用部の電気代の明細で確かめます。床からの盤の高さは電気工事の業者が測ります。",
                "管理会社（書類・高さ）",
                1,
                floor=_room_on_floor(sample, "elec") if floor_known else None,
                evidence=DRAWING,
                confirmed=True,
                always_confirm=True,
                details=["確定とするのは立地で水が来ることまでで、床からの盤や箱の高さは別に確かめます。"],
            )
        )
    elif unsure:
        rows.append(
            _item(
                "power",
                "電気（共用部）",
                UNCONFIRMED,
                "マンション側で電気を受ける部屋があるか、高圧か低圧か（保安会社の契約があるか）は、まだ確かめていません。受電の箱か、おおもとのスイッチ盤が浸かると、共用部が停電し、給水ポンプも止まって断水します。",
                "受電の部屋と、高圧か低圧かが未確認",
                "管理会社が、点検の記録か保安規程、竣工図、共用部の電気代の明細で確かめます。電気室の扉や盤の保安会社の連絡先シール・高圧の表示も手がかりになります。",
                "管理会社（書類）",
                1,
                evidence=QUESTION,
            )
        )
    elif sample["has_chief_engineer"]:
        # 図面で地下と分かれば確定（立地が問題なしでない限り）。書類で地下と読めたときも同じ。確定するのは水が来ることまで。
        known = elec_level == "basement" or (document_read and in_basement_known is True and elec_level is None)
        verdict = RISK if known and not location_clear else UNCONFIRMED
        source = "図面で確かめました" if drawing("elec") else "書類で読めました" if document_read else "聞いていますが、書類や図面ではまだ確かめていません"
        where = f"{elec_word}にあると{source}" if (elec_level or in_basement_known is not None) else "どの階にあるかは、まだ分かっていません"
        rows.append(
            _item(
                "power",
                "電気（共用部）",
                verdict,
                f"エレベーター、給水ポンプ、廊下の照明の電気を受ける箱は、{where}。浸かると共用部が停電し、給水ポンプも止まって断水します。",
                f"受電の箱は{elec_word}。浸かると共用部が停電し断水も" if known else f"受電の箱の階（{elec_word}）は{'図面で確認。高さは未確認' if elec_level else '書類で未確認'}",
                "床からの盤や箱の高さは未確認です。管理会社か電気工事の業者が巻き尺で測り、依頼メモに書きます。主任技術者がいる建物では、月次点検のときに高さの確認と記録を頼めます（契約の範囲は要確認）。",
                "管理会社、主任技術者（高さ）",
                1,
                floor=_room_on_floor(sample, "elec") if floor_known else None,
                evidence=DRAWING if drawing("elec") else DOCUMENT if document_read else QUESTION,
                confirmed=drawing("elec"),
                always_confirm=True,
                details=["確定とするのは立地で水が来ることまでで、床からの盤や箱の高さは別に確かめます。"] if verdict == RISK else [],
            )
        )
    else:
        panel_risk = elec_level == "basement" and not location_clear
        rows.append(
            _item(
                "power",
                "電気（共用部のおおもとのスイッチ盤）",
                RISK if panel_risk else UNCONFIRMED,
                (f"共用部の盤の部屋は地下と図面で確かめました。浸かると共用部が停電し、給水ポンプも止まります。" if panel_risk else f"共用部の電気は、{elec_word}の盤の部屋から来ています。床が通路より少し高いだけなら、浅い水でも盤の下の端に届くことがあります。"),
                f"盤の部屋は地下（図面で確認）。浸かると共用部が停電" if panel_risk else f"{elec_word}の盤の部屋。下の端の高さは未確認",
                "管理会社から電気工事の業者に、盤の下の端の高さを測ってもらいます。",
                "管理会社→電気工事の業者",
                2,
                floor=_room_on_floor(sample, "panel_room") if not upper else None,
                evidence=evidence("panel_room", DOCUMENT),
                confirmed=drawing("panel_room"),
                always_confirm=True,
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
        tr_level = room_level(sample, "tr", confirmed)
        in_basement = (tr_level == "basement") if tr_level else bool(tr_floor and "地下" in tr_floor)
        tr_risk = tr_level == "basement" and not location_clear
        scope = "各戸と共用部の両方の電気" if not sample["has_chief_engineer"] else "各戸の電気"
        place = _LEVEL_WORDS.get(tr_level) or ("地下" if in_basement else "1階")
        if sample.get("custom") and in_basement_known is None and not tr_level:
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
                "管理会社から防水・設備業者へ現地調査を依頼します（部屋の中の確認は、電気の月次点検のときに合わせて頼みます）。",
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
    if answers.get("entrance_step") == "no":
        outside.append("道路からの段差がない1階の出入口・搬入口")
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
                details=[STREET_VIEW_NOTE] if answers.get("slope") == "yes" or answers.get("entrance_step") == "no" else [],
            )
        )
    damp = answers.get("damp")
    if sample["id"] == "a" and not sample.get("custom") and damp != "no":
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
    elif damp == "yes":
        # 点検報告書の指摘（書類）から出す。見本Aの文は変えない。
        room = "電気の部屋・ポンプの部屋" if sample["has_chief_engineer"] else "盤の部屋・ポンプの部屋"
        rows.append(
            _item(
                "damp",
                f"{place_word if in_basement_known is not None else '地下（または1階）'}の{room}の床の湿気（点検で指摘済み）",
                UNCONFIRMED,
                "すでにどこかから水気が入っているサインの可能性があります。どの部屋の指摘かは、点検報告書で確かめます。",
                "点検で湿気の指摘あり",
                DAMP_CONFIRM if sample["has_chief_engineer"] and not sample.get("engineer_unsure") else DAMP_CONFIRM_NO_ENGINEER,
                "管理会社→防水の業者",
                2,
                evidence=DOCUMENT,
            )
        )
    tower_sample = sample["id"] == "c" and not sample.get("custom")
    # 答えがないときは今の見本Cの扱いのまま。答えが「あり」のときだけ未確認で出す。
    has_tank = answers.get("tank", "yes" if tower_sample else None) == "yes"
    has_gen = answers.get("generator", "yes" if tower_sample else None) == "yes"
    if has_tank:
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
                evidence=evidence("tank", DOCUMENT if tower_sample else QUESTION),
                confirmed=drawing("tank"),
            )
        )
    if has_gen and tower_sample:
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
    elif has_gen:
        # 答えや書類で「あり」と分かっただけでは、置き場所の階は決めない。
        rows.append(
            _item(
                "gen",
                "非常用発電機",
                UNCONFIRMED,
                GEN_HEADLINE_ANSWERED,
                "置き場所の階が未確認。水害の長い停電に足りるとは言えない",
                "管理会社から設備業者に、部屋の床の高さと燃料の持ち時間を確かめてもらいます。",
                "管理会社→設備業者",
                3,
                evidence=QUESTION,
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
    rows.append(
        _item(
            "lock",
            "オートロック・インターホン",
            UNCONFIRMED,
            LOCK_HEADLINE,
            "停電のときの扉の動きが未確認",
            LOCK_CONFIRM,
            "管理会社→オートロックの保守会社",
            3,
        )
    )
    if in_basement_known is not False or hollow:
        rows.append(
            _item(
                "drain",
                "トイレ・排水",
                UNCONFIRMED,
                "汚水を汲み上げるポンプがあるか、どの階にあるかは、まだ分かっていません。止まるとトイレや生活排水が使えなくなり、低い階へ逆流することがあります。",
                "汲み上げポンプの有無と階が未確認",
                "管理会社が竣工図で確かめます。",
                "管理会社（竣工図）",
                1,
                details=[HOLLOW_REASON] if hollow else [],
            )
        )
    rows.append(
        _item(
            "backflow",
            "下水の逆流（低い階のトイレ・排水口）",
            UNCONFIRMED,
            BACKFLOW_HEADLINE,
            "合流式か、逆止弁の有無と動作の確認が未確認",
            BACKFLOW_CONFIRM,
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
                "装置の下の掘り込みに水がたまると車が水没します。" if not sample.get("custom") else "機械式駐車場があるかは、まだ分かっていません。あれば、装置の下の掘り込みに水がたまると車が水没します。",
                "掘り込みの深さと排水ポンプが未確認",
                "駐車場の保守会社に、掘り込みの深さと排水ポンプの有無を確認します。",
                "駐車場の保守会社",
                3,
            )
        )
    _apply_heights(rows, given, mount)
    _clear_paths(rows, sample, confirmed)
    return rows


def _apply_heights(rows: List[dict], given: dict, mount: str) -> None:
    """入力された高さを、水の行と電気の行の文に入れる。計算はしない。"""
    by_key = {row["key"]: row for row in rows}
    water = by_key.get("water")
    if water and "panel_bottom" in given:
        text = given["panel_bottom"]["text"]
        water["headline"] = water["headline"].replace(f"と高さは、まだ確かめていません（盤の形：{mount}）。", f"は、まだ確かめていません（盤の形：{mount}。盤の下の端の高さは{text}）。")
        water["summary"] = water["summary"].replace("高さは未確認", f"高さは{text}")
    if water and "pump_floor" in given:
        water["details"].append(f"ポンプの部屋の床：{given['pump_floor']['text']}")
    if water and all(key in given and given[key]["measured"] for key in ("panel_bottom", "pump_floor")):
        water["confirm_by"] = WATER_MEASURED_CONFIRM
    power = by_key.get("power")
    if power and "elec_floor" in given:
        power["details"].append(f"電気の部屋の床：{given['elec_floor']['text']}")


def top_line(sample: dict, equipment: List[dict], location_rows: List[dict], confirmed: List[str]) -> dict:
    """最上段の一行は、決まった順に当てはめ、最初に当たった書き出しを出す。"""
    location_risk = any(row["verdict"] == "risk" for row in location_rows)
    location_clear = bool(location_rows) and all(row["verdict"] == "clear" for row in location_rows)
    is_basement = rooms_in_basement(sample) is True
    notes = []
    # A4 だけで使う注記。Claude の整形と模型の上の帯には渡さない。
    a4_notes = []
    # 水・共用部の電気・各戸の電気の3行が問題なし（2階以上・図面にない）なら、おそれは小さい（2026-11-06 本人の決定）。
    main = [item for item in equipment if item.get("key") in ("water", "power", "tr")]
    main_clear = bool(main) and all(item["verdict"] == "clear" for item in main)
    all_clear = bool(equipment) and all(item["verdict"] == "clear" for item in equipment)
    if location_clear or main_clear or all_clear:
        lead = "今の情報では、浸水で水が止まるおそれは小さい（または対策済み）。"
        # 何で確かめたかを添える。lead の文は変えない。
        if location_clear:
            notes.append(TOP_NOTE_LOCATION_CLEAR)
        if all_clear or main_clear:
            listed = equipment if all_clear else main
            by_drawing = [item["label"] for item in listed if item.get("evidence") == DRAWING]
            by_document = [item["label"] for item in listed if item.get("evidence") == DOCUMENT]
            parts = []
            if by_drawing:
                parts.append(f"図面で確かめた設備：{'、'.join(by_drawing)}")
            if by_document:
                parts.append(f"書類で確かめた設備：{'、'.join(by_document)}")
            if parts:
                notes.append("／".join(parts) + "。")
    elif any(item["verdict"] == "risk" for item in equipment) or is_basement:
        lead = "このままなら、長引くおそれがある。"
        if not location_risk:
            notes.append("建物の位置まで水が来るかは、まだ確かめていない。立地の表に書いた確認先に、管理会社が確かめる。")
        basement_keys = {"elec", "tr", "pump"}
        if not basement_keys.issubset(confirmed):
            notes.append("地下にあるのは書類や聞き取りによるもので、図面ではまだ確かめていない。管理会社が竣工図で確かめる。")
        notes.append("給水・排水のスイッチ盤は製作に約2か月（建築設備技術者協会の報告書）。武蔵小杉は断水8日・トイレ11日（ほかの建物の例）。一番安い手は数万円から。")
        notes.append(TOP_NOTE_GUIDE_DAYS)
        a4_notes.append(A4_NOTE_CHIBA)
    else:
        steps = answer_steps(equipment)
        lead = f"確認待ち {len(steps)}件（図面で階を確かめる）。" if steps else "確認待ち（依頼メモの項目）。"
        notes.append("どこまで水が来るかと盤の高さが未確認。もし浸かれば制御盤の製作に約2か月（建築設備技術者協会の報告書）など長引くおそれがあるので、まず依頼メモで高さを確かめる。")
    return {"lead": lead, "notes": notes, "a4_notes": a4_notes, "steps": answer_steps(equipment)}


# 「何日で水が出るか」の答えに効く順。暮らしに近い水と電気から。
_STEP_ORDER = ["water", "power", "tr", "entry", "ev", "drain", "backflow", "lock", "park"]
# 何が分かれば答えが出るかを、住民や理事が読める言葉で一行にする。判定は言わない。
_STEP_WHAT = {
    "water": "ポンプの盤が床から何cmにあるか",
    "power": "電気を受ける部屋の階と、高圧か低圧か",
    "tr": "東京電力の変圧器の部屋があるか・どの階か",
    "entry": "電気の部屋の壁の穴がふさがれているか",
    "ev": "エレベーターの底に水が入ったときの手順",
    "drain": "トイレの水を汲み上げるポンプがあるか・どの階か",
    "backflow": "下水の逆流を止める弁があるか",
    "lock": "停電のとき玄関の扉がどう動くか",
    "park": "機械式駐車場の掘り込みの深さと排水",
}
STEPS_MAX = 3


def _step_what(row: dict) -> str:
    """部屋の有無がもう分かっている建物では、次に要るのは高さや照会なので、言い方を替える。"""
    summary = row.get("summary") or ""
    if row["key"] == "power" and "主任技術者の有無" not in summary:
        return "電気を受ける盤が床から何cmにあるか"
    if row["key"] == "tr" and "部屋があるか" not in summary:
        return "東京電力の変圧器の部屋の浸水対策（東京電力に照会）"
    return _STEP_WHAT[row["key"]]


def answer_steps(equipment: List[dict]) -> List[dict]:
    """未確認の行のうち、答えに効く順に最大3つ。誰に頼むか（依頼メモの番号）を添える。文は作らず、行の確認先のまま。"""
    open_rows = [row for row in equipment if row["verdict"] == UNCONFIRMED and row.get("confirm_short") and row["key"] in _STEP_WHAT]
    open_rows.sort(key=lambda row: _STEP_ORDER.index(row["key"]))
    return [
        {"key": row["key"], "what": _step_what(row), "who": row["confirm_short"], "memo_no": row.get("memo_no")}
        for row in open_rows[:STEPS_MAX]
    ]


def unit_prices(sample: dict) -> List[dict]:
    """画面4の単価の表の行。個数の初期値は建物の形から決める（人が ＋− で変える）。"""
    answers = sample.get("answers") or {}
    has_slope = answers.get("slope") == "yes" or any(room["key"] == "slope" for view in sample["views"] for room in view["rooms"])
    rule = {
        "one": 1,
        "zero": 0,
        "slope": 1 if has_slope else 0,
        "feed": 1 if sample.get("underground_feed") else 0,
        "floor_panel": 1 if sample.get("panel_mount") == "床置き" else 0,
    }
    return [{**item, "count": rule[item["default"]]} for item in samples.UNIT_PRICES]


def visible_measures(sample: dict, equipment: List[dict]) -> List[dict]:
    tr_risk = any(item["key"] == "tr" and item["verdict"] == RISK for item in equipment)
    keys = {
        "door": sample["archetype"] != "ground",
        "door_rebuild": sample["archetype"] != "ground",
        "tepco": tr_risk,
        # 共用の主開閉器盤の付け替えは、主任技術者のいない建物（借室のみ型・全低圧受電型）だけ。
        "main_panel": not sample["has_chief_engineer"],
        # 発電機の上階移設は、発電機の行がある建物だけ。
        # 非常用発電機を上の階へ移すは、メインの画面から外した（2026-11-06 本人の指示）。
        "gen_move": False,
    }
    rows = []
    for measure in samples.MEASURES:
        if not keys.get(measure["key"], True):
            continue
        row = dict(measure)
        if measure["key"] == "hole" and not sample["has_chief_engineer"]:
            row["owner"] = samples.HOLE_OWNER_NO_ENGINEER
        if measure["key"] == "panel" and sample["panel_mount"] != "壁掛け":
            row["label"] = "ポンプのスイッチ盤をさらに高い位置に付け替える（盤の下の端が低いと分かった場合）"
        if measure["key"] == "hole" and not sample["underground_feed"]:
            row["label"] = "盤の部屋の壁や床の穴（給排水管などが通る穴）をふさぐ（施工は電気工事の業者が、停電の要否・離隔を決めてから。理事や管理員は部屋に入らない。東京電力の変圧器の部屋の穴には、だれも栓や止水材を入れない）"
        rows.append(row)
    return rows


def is_hollow(location_rows: List[dict], basin: bool = False) -> bool:
    """敷地の高低差の行に、くぼ地か周囲より低い凹みの札があるか。札は地図の目安で、判定ではない。"""
    if basin:
        return True
    for row in location_rows:
        if row.get("key") == "ground":
            badges = (row.get("accent") or {}).get("badges") or []
            if any(badge in HOLLOW_BADGES for badge in badges):
                return True
    return False


def memos(sample: dict, equipment: List[dict], location_rows: List[dict], statements: Optional[List[str]] = None, hollow: bool = False, scale_unknown: bool = False) -> List[dict]:
    """未確認を、確認する先ごとの依頼メモにする。"""
    sections = {
        1: {"key": 1, "label": "①", "title": "管理会社が書類・問い合わせで確かめること", "items": []},
        2: {"key": 2, "label": "②", "title": "管理会社から業者へ（現地調査の見積りと手配）", "items": []},
        3: {"key": 3, "label": "③", "title": "保守会社への照会・測定", "items": []},
    }
    for row in location_rows:
        if row.get("confirm_by"):
            text = row["confirm_by"]
            if hollow and row.get("key") == "ground":
                text = f"{text}（{HOLLOW_REASON}）"
            sections[1]["items"].append({"from": row["label"], "text": text})
    for item in equipment:
        if item.get("confirm_by") and item.get("memo_section"):
            text = item["confirm_by"]
            if hollow and item["key"] == "drain":
                text = f"{text}汚水を汲み上げるポンプがあるか、どの階かも確かめます（{HOLLOW_REASON}）"
            sections[item["memo_section"]]["items"].append({"from": item["label"], "text": text})
    first = sections[1]["items"]
    for statement in statements or []:
        first.append({"from": "聞き取り", "text": f"「{statement}」との話を、管理会社が竣工図で確かめます（図面で確かめるまで未確認です）。"})
    first.append({"from": "決める場", "text": "管理会社が規約・予算書・総会の議事録で、壁の穴の止水と置くだけの止水板を理事会で決められるかを確かめます。"})
    if sample["has_chief_engineer"]:
        first.append({"from": "電気を切る手段", "text": "主任技術者に、単線結線図で受電設備側の最初の開閉器の位置と、電気室に入らずに切れる手段があるかを確かめてもらいます。"})
    else:
        first.append({"from": "受電の形", "text": "管理会社が、共用部の電気代の明細で契約種別が低圧であることと、同じ敷地に発電設備がないことを確かめます。"})
    if sample.get("feed_unknown"):
        first.append({"from": "引込みの形", "text": MEMO_FEED_FORM})
    if sample["underground_feed"] and not sample["has_chief_engineer"]:
        first.append({"from": "地中の高圧ケーブル", "text": MEMO_CABLE_NO_ENGINEER})
    elif sample["underground_feed"]:
        first.append({"from": "地中の高圧ケーブル", "text": "管理会社を通じて電気主任技術者に、高圧ケーブルの敷設年と点検の記録、大雨や浸水のあとに行う確認を聞きます。歩道ぎわの蓋は開けません。"})
    first.append({"from": "給水の方式", "text": MEMO_WATER_SUPPLY})
    if scale_unknown:
        first.append({"from": "規模", "text": MEMO_SCALE_UNKNOWN})
    sections[2]["items"].append({"from": "盤の中の湿気", "text": MEMO_DAMP_LOOK if sample["has_chief_engineer"] and not sample.get("engineer_unsure") else MEMO_DAMP_LOOK_NO_ENGINEER})
    sections[3]["items"].append({"from": "排水ポンプ", "text": MEMO_PUMP_CHECK})
    # 補助の一行は区分②の最後に置く。
    sections[2]["items"].append({"from": "補助", "text": MEMO_FREE_SURVEY})
    return _number_memos(list(sections.values()), equipment)


def _number_memos(sections: List[dict], equipment: List[dict]) -> List[dict]:
    """同じ文を一つにまとめ、元の行の名前を sources に持たせ、区分の中で ①-1 から番号を振る。文は変えない。"""
    index = {}
    for section in sections:
        merged: List[dict] = []
        by_text = {}
        for item in section["items"]:
            if item["text"] in by_text:
                by_text[item["text"]]["sources"].append(item["from"])
                continue
            item = {**item, "sources": [item["from"]]}
            by_text[item["text"]] = item
            merged.append(item)
        for number, item in enumerate(merged, start=1):
            item["no"] = f"{section['label']}-{number}"
            for source in item["sources"]:
                index.setdefault(source, item["no"])
        section["items"] = merged
        section["index"] = {source: item["no"] for item in merged for source in item["sources"]}
    for row in equipment:
        if row["label"] in index and row.get("confirm_by") and row.get("memo_section"):
            row["memo_no"] = index[row["label"]]
    return sections


# 停電の連鎖の図の箱とつながり。
def has_room(sample: dict, key: str) -> bool:
    return any(room.get("key") == key for view in sample.get("views") or [] for room in view.get("rooms") or [])


# 分電盤室が浸かると、各戸の電気も止まる想定にする（2026-11-05 本人決定。電気主任技術者としての実務の判断）。
# 部屋で決める：図に「分電盤室」（共用部のおおもとのスイッチ盤の部屋）がある建物では、その盤から各戸へ電気が行くとみる。
# 高圧受電の電気室（受電の箱）が浸かったときの各戸は、今のまま（各戸は借室から）。
PANEL_ROOM_HOMES_NOTE = "分電盤室が浸かると、共用部だけでなく各戸の電気も止まる想定です（分電盤室から各戸へ電気が行く建物の想定）。"


def chain_nodes(sample: dict, confirmed: Optional[List[str]] = None) -> dict:
    result = _chain_with_room(sample, confirmed)
    if not is_bulk(sample, confirmed) and has_room(sample, "panel_room") and ("hv", "homes") not in result["edges"]:
        result["edges"] = [*result["edges"], ("hv", "homes")]
        result["note"] = PANEL_ROOM_HOMES_NOTE
    return result


def _chain_with_room(sample: dict, confirmed: Optional[List[str]] = None) -> dict:
    answers = sample.get("answers") or {}
    if is_bulk(sample, confirmed):
        nodes = [
            {"key": "line", "label": "外の電線"},
            {"key": "hv", "label": "受電の箱"},
            {"key": "panel", "label": "給水ポンプの制御盤"},
            {"key": "pump", "label": "給水ポンプ（全戸の水）"},
            {"key": "ev", "label": "エレベーター"},
            {"key": "light", "label": "廊下の照明"},
            {"key": "homes", "label": "各戸の電気"},
        ]
        edges = [("line", "hv"), ("hv", "panel"), ("panel", "pump"), ("hv", "ev"), ("hv", "light"), ("hv", "homes")]
        return {"nodes": nodes, "edges": edges, "note": CHAIN_NOTE_BULK}
    result = _chain_nodes(sample)
    if not sample.get("engineer_unsure") and answers.get("tr") not in ("no", "unknown") and "absent:tr" not in (confirmed or []):
        result["note"] = CHAIN_NOTE_TR if sample["has_chief_engineer"] else CHAIN_NOTE_NO_ENGINEER
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


def services(stopped: set, homes_safe: bool = False) -> List[dict]:
    """各戸の電気は東京電力の設備しだいで、止まらない想定のときも建物側からは分からない（借室が2階以上と図面で分かったときだけ running）。"""
    result = []
    for key, label in SERVICES:
        if key in stopped:
            state = "stopped"
        elif key == "homes":
            state = "running" if homes_safe else "unknown"
        else:
            state = "running"
        result.append({"key": key, "label": label, "state": state})
    return result


def scenario(sample: dict, water: int, measure: str, confirmed: Optional[List[str]] = None) -> dict:
    """水の位置と対策の組合せごとに、浸かる想定、止まる想定、表のマス、固定の文を作る。"""
    answers = sample.get("answers") or {}
    confirmed = confirmed or []
    bulk = is_bulk(sample, confirmed)
    tr_unseen = answers.get("tr") in ("no", "unknown") or "absent:tr" in confirmed
    # 図面で2階以上・描かれていないと確かめた部屋は、水の位置③でも浸からない（2026-11-06 本人の決定）。
    safe = lambda *keys: any(key in confirmed for key in keys)  # noqa: E731
    wet = set()
    if water >= 2:
        if not safe("absent:ev"):
            wet.add("ev")
        if sample["panel_mount"] == "床置き" and measure != "raise" and not safe("upper:pump", "absent:pump"):
            wet.add("panel")
    if water >= 3:
        if not tr_unseen and not bulk and not safe("upper:tr"):
            wet.add("tr")
        if measure != "hole" and not safe("upper:elec", "upper:panel_room"):
            wet.add("hv")
        if measure != "raise" and not safe("upper:pump", "absent:pump"):
            wet.add("panel")
    tr_safe = safe("upper:tr") and not bulk

    chain = chain_nodes(sample, confirmed)
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
    if tr_unseen and not bulk:
        notes.append("東京電力の設備の位置は未確認です（東京電力パワーグリッドに確かめる）。")
    below = []
    gone = False

    hv_wet = "hv" in wet
    tr_wet = "tr" in wet
    homes_by_panel = "homes" in stopped and not tr_wet and ("hv", "homes") in chain["edges"]
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
                mark("tr") if tr_wet else "止まる想定（分電盤室が浸かるため）" if homes_by_panel else "浸からない想定（2階以上と図面で確認）" if tr_safe else "建物側から分からない",
                "東京電力パワーグリッドが判断" if tr_wet else f"止まる想定のまま、{checker}が確かめるまで戻さない" if homes_by_panel else "—",
                guide_days if tr_wet else "目安なし＊",
                "—",
            ],
            "stopped": tr_wet or homes_by_panel,
            "note": FIXED["tr_box"],
        },
    ]
    if bulk:
        # 各戸の電気もマンション側の受電設備から来る建物。東京電力の変圧器の部屋の行を、各戸の電気の行にする。
        table[3] = {
            "key": "tr",
            "label": BULK_LABEL,
            "cells": [
                "—",
                mark("homes"),
                (f"止まる想定のまま、{checker}が確かめるまで戻さない") if "homes" in stopped else "—",
                guide_days if hv_wet else "目安なし＊",
                "—",
            ],
            "stopped": "homes" in stopped,
        }
    _tag_rows(table, sample, confirmed)
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
    rain = rain_lines(sample, confirmed)
    before += "。" + rain["third"] + "".join(rain["extra"])
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
        "services": services(stopped, homes_safe=tr_safe),
        "tr_state": "stopped" if tr_wet else "unknown",
        "notes": notes,
        "below": below,
        "table": table,
    }


def _tag_rows(table: List[dict], sample: dict, confirmed: List[str]) -> None:
    """時間の流れの表の行に、位置と高さを確かめたかの札を付ける。"""
    given = heights(sample)
    power_room = "elec" if sample["has_chief_engineer"] else "panel_room"
    rooms = {"water": "pump", "hv": power_room, "tr": "tr", "ev": "ev"}
    height_keys = {"water": "panel_bottom", "hv": "elec_floor"}
    for row in table:
        room = rooms.get(row["key"])
        if not room:
            continue
        tags = []
        if room not in confirmed:
            tags.append("位置は図面で未確認")
        if height_keys.get(row["key"]) not in given:
            tags.append("高さは未確認")
        row["tags"] = tags


def scenarios(sample: dict, confirmed: Optional[List[str]] = None) -> dict:
    return {
        f"{water}:{item['key']}": scenario(sample, water, item["key"], confirmed)
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


def scale_focus(sample: dict, equipment: List[dict], location_rows: List[dict]) -> dict:
    """規模の区分ごとの重点を、今ある行の札にし、重ならないものだけ未確認の行として足す。"""
    answers = sample.get("answers") or {}
    value = answers.get("scale")
    location_clear = bool(location_rows) and all(row.get("verdict") == "clear" for row in location_rows)
    info = {"value": value, "label": SCALE_LABELS.get(value, ""), "shown": False, "focus": [], "note": SCALE_NOTE, "out_of_scope": SCALE_OUT_OF_SCOPE, "memo": value == "unknown" and not location_clear}
    if value not in SCALE_FOCUS or location_clear:
        return info
    no_engineer = not sample["has_chief_engineer"]
    by_key = {row["key"]: row for row in equipment}
    for key, focus in SCALE_FOCUS[value]:
        if key == "power" and no_engineer:
            focus = "共用部のおおもとのスイッチ盤の下の端の高さ"
        if key == "tr" and sample["has_chief_engineer"] and not sample.get("engineer_unsure"):
            focus += "（主任技術者は技術面で同席）"
        row = by_key.get(key)
        if row is None and key == "outside":
            row = _item("outside", "外から見える入口", UNCONFIRMED, f"この規模の建物で重点に確かめる候補です。{focus}の高さと止水板を置けるかは、まだ分かっていません。", focus, SCALE_OUTSIDE_CONFIRM, "管理会社（外から）", 1, evidence=QUESTION)
            equipment.append(row)
            by_key[key] = row
        elif row is None and key == "tank" and answers.get("tank") != "no":
            row = _item("tank", "雨水ますから地下の貯留タンク", UNCONFIRMED, SCALE_TANK_HEADLINE, "貯留槽の有無、止水バルブと蓋のロックが未確認", "管理会社が竣工図で確かめ、設備業者へ現地調査を依頼します。", "管理会社→設備業者", 2, evidence=QUESTION)
            equipment.append(row)
            by_key[key] = row
        if row is None:
            continue
        if SCALE_TAG not in row.setdefault("badges", []):
            row["badges"].append(SCALE_TAG)
        row.setdefault("scale_focus", []).append(focus)
        info["focus"].append({"row": key, "text": focus})
    info["shown"] = True
    return info


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
    location_clear = bool(location_rows) and all(row["verdict"] == "clear" for row in location_rows)
    hollow = is_hollow(location_rows, basin)
    equipment = judge_equipment(sample, confirmed, location_risk, document_read, hollow=hollow, location_clear=location_clear)
    answers = sample.get("answers") or {}
    scale = scale_focus(sample, equipment, location_rows)
    # 依頼メモの番号（memo_no）を行に振ってから、最上段の「誰に頼むか」を作る。
    memo_list = memos(sample, equipment, location_rows, statements or [], hollow=hollow, scale_unknown=scale["memo"])
    return {
        "sample": samples.client_view(sample),
        "confirmed": confirmed,
        "document_read": document_read,
        "equipment": equipment,
        "top_line": top_line(sample, equipment, location_rows, confirmed),
        "measures": visible_measures(sample, equipment),
        "unit_prices": unit_prices(sample),
        "recovery_cost_line": samples.RECOVERY_COST_LINE,
        "subsidies": samples.SUBSIDIES,
        "memos": memo_list,
        "scale": scale,
        "direction_line": direction_line(directions or {}, low_directions or [], sample, high_directions, basin),
        "statements": statements or [],
        "chain": chain_nodes(sample, confirmed),
        "water_levels": WATER_LEVELS,
        "model_measures": measures_for_model(sample),
        "scenarios": scenarios(sample, confirmed),
        "heights": list(heights(sample).values()),
        "rain": rain_lines(sample, confirmed),
        "fixed": FIXED,
        # 警戒レベル4の満潮の分岐に足す文の材料。表示は A4 の担当が決める。
        "rain_tank_valve": {
            "tank": "yes" if any(item["key"] == "tank" for item in equipment) and answers.get("tank") != "no" else answers.get("tank", "unknown"),
            "tank_valve": answers.get("tank_valve", "unknown"),
            "show": answers.get("tank") == "yes" and answers.get("tank_valve") == "yes",
            "text": RAIN_TANK_VALVE,
        },
    }
