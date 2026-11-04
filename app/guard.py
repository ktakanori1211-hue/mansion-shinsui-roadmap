"""チャットと Claude の文の囲い。感電や立入につながる答えを出さないための、プログラムの決まり。

水、立入、電気の操作に触れる質問は、AI を通さず固定の文を出す。取りこぼしより出しすぎを許す。
Claude の文は、数字と禁止の語を事後に確かめる。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional

DISCLAIMER_1 = "本シートは公開データと入力情報から作成したもので、現地の判定や安全を保証するものではない。浸水中は電気室・借室（東京電力の変圧器の部屋）・ポンプ室・EVピットに立ち入らず、復電の可否は電気主任技術者が判断する"

NO_ENGINEER_NOTE = "（電気主任技術者を選任していない建物では、借室は東京電力パワーグリッドの確認を待ち、マンション側は電気工事の業者が点検・測定した結果を書面で受けて管理組合が判断する。どちらも済むまで電気を戻さない）"


MEDICAL_TEXT = (
    "在宅の医療機器が止まった、または使っている人の様子がおかしいときは、すぐ 119 番に連絡し、医療機器を使っていることを伝えてください。"
    "停電に備えて、予備の電源があるか、どのくらい使えるか、止まったときに手でできることを、主治医や機器の業者にふだんから確かめておきます。"
    "管理組合は、本人の同意を得て事前に把握し、電気を止めるときに先に知らせる人に入れておきます。"
)

EMERGENCY_TEXT = (
    "人が感電した、倒れている、火や煙が出た、閉じ込められたときは、すぐ 119 番に連絡してください。"
    "電気の部屋の近くや水の中で人が倒れているときは、近づかず、触れず、場所と感電のおそれがあることを伝えてください。"
    "電気が切れたかどうかを、住民、理事、管理員が確かめて近づくことはしません。離れて救急隊を待ち、着いたら案内してください。"
    "管理員か理事長は、{contact}へ連絡します。"
    "火や煙が出ているときは、その場を離れて避難します。エレベーターに閉じ込められたら、非常ボタンかインターホンで連絡し、自力で出ようとしません。"
)

RESTORE_TEXT = (
    "住民、理事、管理員は、電源を入れません。測定もしません。測定の値だけで戻すかを決めることもしません。"
    "水が引いた直後に遮断器を入れません。泥や塩分が残ったまま通電すると、短絡のおそれがあります。"
    "東京電力の設備の送電の再開は東京電力パワーグリッドが行います。"
)

ENTRY_TEXT = "電気室・盤の部屋・東京電力の変圧器の部屋・ポンプ室に入らず、扉も開けません。"

ENGLISH_NOTE = (
    "No. Do not enter the electrical room or touch anything. Do not walk into the water. "
    "If you are in the water, get out without touching anything and go above ground. "
    "If someone has collapsed near electrical equipment or in water, do not approach them. "
    "Call 119, then contact the building manager."
)


def disclaimer(has_chief_engineer: bool = True) -> str:
    """固定の文の本体は変えず、主任技術者のいない建物では括弧書きを添える。"""
    return DISCLAIMER_1 if has_chief_engineer else DISCLAIMER_1 + NO_ENGINEER_NOTE


_EMERGENCY = re.compile(r"感電|しびれ|ビリ|倒れ|意識が|呼吸|火が|火花|燃え|煙|焦げ|異臭|バチ|ショート|閉じ込め|出られない|息が")
# 在宅の医療機器。感電の文を混ぜると、止まった人の手当てを遅らせかねないので分ける。
_MEDICAL = re.compile(r"人工呼吸|呼吸器|酸素|吸引器|透析|医療機器")
_SHOCK = re.compile(r"感電|しびれ|ビリ|火が|火花|燃え|煙|焦げ|バチ|ショート")
# 建物が安全かを聞く文。言い切らず、札の意味を答える。
_IS_SAFE = re.compile(r"(安全|大丈夫)(なん|です|だよ|なの|か|でしょ)|問題(ない|ありません)(です|よね|か)")
# 文末の「大丈夫？」は、建物や浸水の話のときだけ札の意味の文に回す（費用・決め方・備えの段取りの問いは塞がない）。
_IS_SAFE_END = re.compile(r"(安全|大丈夫)\s*[?？]?\s*$")
_BUILDING_SUBJECT = re.compile(r"うち|マンション|建物|この棟")
# 電気を戻す判断を聞く文。立入の文ではなく、誰が判断するかを答える。
_RESTORE = re.compile(r"復電|通電|送電|電源を入れ|電気を(戻|入れ)|絶縁抵抗|メガ|(代わり|代理).{0,12}(判断|復旧)|復旧の判断")
_WATER = re.compile(r"水|雨|浸|冠|濡れ|ぬれ|洪|台風|停電|断水")
_PLACE = re.compile(r"扉|ドア|隙間|懐中電灯|部屋|つまみ|レバー|主開閉器|電気|受電|キュービクル|盤|ブレーカー|遮断|電源|スイッチ|ポンプ|ピット|マンホール|蓋|ふた|ハンドホール|借室|変圧器|地下|駐車場|車|スロープ|エレベーター|発電機|蓄電池|太陽光|止水板|土のう|管路|穴|電線|貯留|タンク|バルブ")
_ACT = re.compile(r"覗|見に|見て[行き]|下げ|詰め|入[っるれりろ]|はい[っるれり]|降り|行[っくき]|見[にてた]|のぞ|確認し|確かめ[にたて]|様子|開け|あけ|外[しす]|触|さわ|切[っるれり]|戻|上げ|落と|塞|ふさ|詰|栓|コーキング|シーリング|止水材|ストパック|抜[いきくけ]|くみ|汲み|回[しす]|つな|使[いうえっ]|動か|かけ|乾か|洗|撮|鍵|リセット|再起動|通電|送電|復電|置きに|取りに|始め")
_PERMIT = re.compile(r"いい|よい|良い|大丈夫|平気|したい|ていい|ても|可能|できます|ますか|ます$|ます。|安全|問題ない|どうすれば|べき")
_EXPLAIN = re.compile(r"どういう|とは|なぜ|どうして|なんで|何が|何の|どこに|どれ|誰が|いくら|費用|補助|助成|総会|理事会|決議|意味|教えて|説明")
_DIRECT = re.compile(r"(代わり|代理).{0,12}(判断|復旧)|復電|通電|送電|再起動|リセット|電源車|電源を入れ|(垂|切れ|落ち).*電線|電線.*(垂|切れ|落ち)|(水の位置|[123]の位置).*(入れ|入っ|はい)|もう(安全|大丈夫)")
# 建物の部屋や盤の操作のやり方を聞く文。説明の語があっても AI に回さない。
_HOWTO = re.compile(r"(開け|あけ|切[るり]|入れ|落と|詰め|塞|ふさ|外[しす]|下げ|上げ|戻|止め|閉め|開放|オ[フン]に|オ[フン]す|接続|操作|復旧|確認す|見る).{0,24}(方法|手順|やり方|しかた|仕方)")
# 費用や決め方を聞く文と、模型の想定を見せてと頼む文。立入や操作の語がなければ AI に回す。
_COST = re.compile(r"いくら|費用|補助|助成|総会|理事会|決議|決め|見積|想定|見せ|切り替え|模型")
_HARD = re.compile(r"入[っるれりろ]|はい[っるれり]|開け|あけ|触|さわ|切(?:[っるれ]|り(?!替))|戻|電源|排水")
_BARE = re.compile(r"(開け|見てき|降り|入り|入っ|触り|触っ|行ってき)(ます|る|てき)")
_HOME = re.compile(r"(うちの|自分の|部屋の|各戸の|家の|自宅).*(分電盤|コンセント|家電|ブレーカー)|(冷蔵庫|洗濯機|テレビ|家電|コンセント|分電盤).*(濡|ぬれ|水|浸|使え)|(濡|ぬれ|水|浸).*(冷蔵庫|洗濯機|テレビ|家電|コンセント|分電盤)")
_FOREIGN = re.compile(r"electric|enter|breaker|switch|flood|电|进入|配电")
_FORECAST = re.compile(r"今夜|今晩|今日.*(浸水|雨)|明日.*(浸水|雨)|いつ.*雨|予報|何ミリ|降る")


# 水が来ている、止まった、など「今起きている」ことを言う語。
_NOW = re.compile(
    r"今(?!のうち)|いま|現在|さっき|中で|の中|中に|浸水中|冠水中|停電中|大雨だ|大雨で|雨がひど|雨が強|入ってき|入って来|来ている|来てる|来ました|水が来た|上がってき|水位が上|流れ込|あふれ|越水|逆流|水没|漏れ"
    r"|溜ま|たまっ|浸か|濡れ|ぬれ|冠水路|冠水した道|冠水し(?:て|た(?!ら))|浸水し(?:て|た(?!ら))|停電し(?:て|た(?!ら))|停電にな|電気が消|水が引|引いた|復旧した|止まった"
    r"|避難指示|避難の?情報が出|が出た|が出て|出ている|倒れ|感電|煙|火が|火花|焦げ|閉じ込められ|出られない|ビリ|バチ|ショート|もう"
)
# 危険な場所への立入、操作、接触の語。備えの話でも、これがあれば通さない。
_NO_PREPARE_ACT = re.compile(
    r"入[っるりろ]|はい[っるれり]|開け|あけ|外[しす]|触|さわ|切(?:[っるれ]|り(?!替))|戻|電源|通電|送電|復電|復旧|再起動|リセット|排水|抜[いきくけ]|汲|くみ|見に|見て[行き]|見てき|覗|のぞ|降り|近づ|様子"
    r"|取りに|置きに|出しに|取り付けに|に行|に向か|鍵|撮|つな|接続|コーキング|シーリング|シリコン|止水材|栓|詰|落と|下げ|閉め|開放|オ[フン]に|オ[フン]す|操作"
)
_DANGER_PLACE = re.compile(r"電気室|電気の部屋|受電|受変電|配電|高圧|主幹|開閉器|キュービクル|盤|ブレーカー|遮断|スイッチ|つまみ|レバー|借室|変圧器|ポンプ|ピット|マンホール|蓋|ふた|ハンドホール|管路|電線|貯留|タンク|バルブ|弁|発電機|蓄電池|太陽光")
# 車は、車いす、救急車、電車、電源車を含めない。
CAR_WORD = r"(?<!救急)(?<!消防)(?<!電)(?<!電源)車(?!いす|椅子)|駐車"
# 具体的な備えの話。これがあれば通す。
_PREPARE_SPECIFIC = re.compile(CAR_WORD + r"|止水板|土のう|吸水|防水板|閉じ込め(の|への)?(対策|備え)|ポータブル電源")
# 一般的な備えの語。電気の話が混ざらないときだけ通す。
_PREPARE_GENERAL = re.compile(r"備え|事前|あらかじめ|前に|準備|対策|手順|ふだん|普段|平時|訓練|役割|連絡先|段取り")
_ELECTRIC_WORD = re.compile(r"電気|電源|電線|停電させ")
_SAFE_WORDS = re.compile(r"ポータブル電源|モバイルバッテリー")
_TRAPPED_PLAN = re.compile(r"閉じ込め(の|への)?(対策|備え)")


# 「浸水しても大丈夫？」を事前の問いとして通すときだけ使う、取りこぼし防ぎの語（電気保安の専門家の指摘、2026-11-04）。
# 進行中の浸水・停電の言い方と、排水・接近・歩行などの動作、設備の別名。どれかがあれば立入の固定文に回す。
_NOW_MORE = re.compile(r"溢れ|水浸し|氾濫|決壊|停電(が|で|だ|のまま|続)|来て(い)?ても")
_ACT_MORE = re.compile(r"排水|近づ|近寄|歩い|歩く|渡っ|渡る|通っ|通る|出し|流し|点検|作業|見る|見ても|操作|接続|閉め|トランス|配電|機械室|受水槽|EV|エレベータ")


def is_preparation(message: str) -> bool:
    """事前の備えの質問か。今起きていること、危険な場所への立入や操作に触れる文は当てはめない。"""
    text = _SAFE_WORDS.sub("備品", unicodedata.normalize("NFKC", message))
    if _NOW.search(text) or _NO_PREPARE_ACT.search(text):
        return False
    if _DANGER_PLACE.search(text) and (_ACT.search(text) or re.search(r"止め|手順|方法|やり方", text)):
        return False
    if _PREPARE_SPECIFIC.search(text) or _PREPARE_SPECIFIC.search(message):
        return True
    return bool(_PREPARE_GENERAL.search(text)) and not _ELECTRIC_WORD.search(text) and not _DANGER_PLACE.search(text)


def _touches_safety(message: str) -> bool:
    """固定の文に回すのは、浸水や停電の中の危険な場所への立入、操作、接触。取りこぼしより出しすぎを許すが、事前の備えは塞がない。"""
    if _DIRECT.search(message) or _FOREIGN.search(message.lower()):
        return True
    if is_preparation(message):
        return False
    act = bool(_ACT.search(message))
    near = bool(_PLACE.search(message) or _WATER.search(message))
    if near and _HOWTO.search(message):
        return True
    if _COST.search(message) and not _HARD.search(message):
        return False
    explaining = bool(_EXPLAIN.search(message))
    permission = bool(_PERMIT.search(message))
    # 「浸水しても大丈夫？」のような、今起きていることも場所も操作も含まない事前の問いは、
    # 立入の固定文に回さない（原則4）。下の is_safe の文が「この道具は安全かを言わない」と答える。
    if _WATER.search(message) and re.search(r"安全|大丈夫", message):
        # 「浸水しても」「来ても、うちは」の「ても」を、今の出来事（浸水して・もう）と読み違えない。
        hypothetical = message.replace("ても", "テモ")
        if (
            _NOW.search(hypothetical)
            or _NOW_MORE.search(message)
            or _PLACE.search(message)
            or _DANGER_PLACE.search(message)
            or _ACT.search(message)
            or _NO_PREPARE_ACT.search(message)
            or _ACT_MORE.search(message)
        ):
            return True
    if _BARE.search(message) and not explaining:
        return True
    if act and near:
        return not explaining or permission and not re.search(r"教えて|説明", message)
    return False


def fixed_answer(message: str, has_chief_engineer: bool = True, unsure: bool = False) -> Optional[dict]:
    """固定の文を返す。当たらなければ None で、AI に回してよい。"""
    message = unicodedata.normalize("NFKC", message)
    notice = disclaimer(has_chief_engineer and not unsure)
    if unsure:
        contact = "東京電力パワーグリッドと管理会社と、いれば主任技術者"
    elif has_chief_engineer:
        contact = "主任技術者と東京電力パワーグリッド"
    else:
        contact = "東京電力パワーグリッドと管理会社"
    # 日本語を含まない質問は、語で見分けられないので、英語を添えて安全の文に回す。
    foreign = bool(_FOREIGN.search(message.lower())) or (bool(re.search(r"[A-Za-z]", message)) and not re.search(r"[ぁ-んァ-ヶ一-龠]", message))
    if _MEDICAL.search(message) and not _SHOCK.search(message):
        return {"kind": "medical", "text": MEDICAL_TEXT}
    prepared = is_preparation(message)
    # 緊急の文は備えの判定に左右させない。外すのは「閉じ込め対策」のような言い方だけ。
    if _EMERGENCY.search(_TRAPPED_PLAN.sub("", message)):
        return {"kind": "emergency", "text": EMERGENCY_TEXT.format(contact=contact) + "\n\n" + notice}
    if _HOME.search(message):
        return {
            "kind": "home",
            "text": "濡れた分電盤やコンセント、家電には触らず、使わないでください。東京電力パワーグリッドか電気工事の業者に相談してください。ご自宅の中の判断は、この道具の範囲の外です。\n\n" + notice,
        }
    english = ENGLISH_NOTE + "\n\n" if foreign else ""
    if not foreign and _RESTORE.search(message):
        if unsure:
            judge = "電気を戻すかは、主任技術者がいれば主任技術者が判断します。いない建物では、借室は東京電力パワーグリッドの確認を待ち、マンション側は電気工事の業者が点検・測定した結果を書面で受けて管理組合が決めます。どちらも済むまで電気を戻しません。"
        elif has_chief_engineer:
            judge = "電気を戻すかは、電気主任技術者が判断します。主任技術者に連絡がつかないときは、保安規程に書かれた連絡先（保安管理業務の委託先など）と東京電力パワーグリッドに連絡し、つながるまで電気を戻しません。"
        else:
            judge = "この建物に主任技術者はいません。借室は東京電力パワーグリッドの確認を待ち、マンション側は電気工事の業者が点検・測定した結果を書面で受けて管理組合が決めます。どちらも済むまで電気を戻しません。"
        lead = "値は出しません。" if re.search(r"絶縁抵抗|メガ|いくつ", message) else "いいえ。"
        entry = ENTRY_TEXT if re.search(r"[室屋盤]に入|入って", message) else ""
        return {"kind": "restore", "text": notice + "\n\n" + lead + judge + RESTORE_TEXT + entry}
    if foreign or _touches_safety(message):
        pump = "借りたポンプや発電機を、水に浸かった配線につなぎません。発電機を切替の装置なしに建物の盤につなぐと、東京電力の側へ電気が流れて作業の人が感電するおそれがあるので、つなぎません。発電機は、排気が地下や室内に入る場所では使いません。" if re.search(r"ポンプ|排水|発電機|水を抜", message) else ""
        return {
            "kind": "safety",
            "text": (
                english
                + notice
                + "\n\n電気室・盤の部屋・東京電力の変圧器の部屋・ポンプ室・エレベーターの底に入らず、扉も開けません。"
                "水に浸かった盤、コード、ブレーカーに触れません。電気を切るために中へ入りません。"
                "歩道ぎわの蓋やマンホールは開けません。東京電力の変圧器の部屋の穴や管路に、だれも栓や止水材を入れません。垂れた電線や水に浸かった地上の変圧器には近づきません。冠水の中へ入りません。"
                "水が来ているときに地下にいたら、何にも触れず地上へ上がります。"
                + f"連絡は管理員か理事長が、{contact}へします。"
                + ("" if has_chief_engineer or unsure else "この建物に主任技術者はいません。")
                + "電気を切っても、東京電力の設備の側や太陽光・蓄電池・発電機の側には電気が残ることがあります。"
                + "\n\n"
                + (
                    "排水は、東京電力パワーグリッドに連絡せずに始めません。排水を始める前に、東京電力パワーグリッドの切り離しと、主任技術者の開放を確かめます。"
                    if has_chief_engineer and not unsure
                    else "排水は、東京電力パワーグリッドに連絡せずに始めません。排水を始める前に、東京電力パワーグリッドに電話で切り離しを確かめ、電気工事の業者に電気が切れていて排水を始めてよいと確かめたうえで、管理組合が排水を始めます。"
                )
                + pump
                + "水の位置は、立ち入ってよい高さではありません。水が引いても、借室（東京電力の変圧器の部屋）は東京電力パワーグリッド、マンション側の部屋は主任技術者（いない建物では電気工事業者）が安全を確かめて入ってよいと指示するまで、住民、理事、管理員は入りません。"
                "入るのは、その場で指示された人だけで、指示された範囲だけです。この道具は入室を許可しません。"
            ),
        }
    end_safe = bool(_IS_SAFE_END.search(message)) and bool(_WATER.search(message) or _BUILDING_SUBJECT.search(message)) and not prepared and not _COST.search(message)
    if _IS_SAFE.search(message) or end_safe:
        return {
            "kind": "is_safe",
            "text": "この道具は、建物が安全かどうかを言いません。判定は画面の札のとおりで、「未確認」はまだ確かめていないという意味です。「問題なし」の札も、立ち入ってよいという意味ではありません。未確認の行は、依頼メモで管理会社に確かめてもらいます。浸水したら何が止まりうるかは、②建物の「止まる設備」と、A4 のおもての一番上の行で見られます。浸水や停電のさなかは、電気室・地下・盤・ポンプ室に近づかず、何にも触れません。\n\n" + notice,
        }
    if _FORECAST.search(message) and not prepared:
        return {
            "kind": "forecast",
            "text": "この道具は予報ではなく、現時点の静的な整理です。雨や浸水の見込みは、自治体と気象庁が出す警戒レベルで確かめてください。避難の情報が出たら従い、地下へ降りません。警戒レベルが出たときに誰が何をするかは、一枚の「大雨が近づいたら」に書いています。",
        }
    return None


_BANNED = re.compile(r"月1回|月に1回|オフにして|閉めてください|開放して|接続して|止めてください|操作してください|入ってよい|入っても|入室でき|開けてよい|操作してよい|安心|心配ありません|大丈夫でしょう|すぐ使え|安全です|安全だと|浸水しません|大丈夫です|問題ありません|構いません|入って大丈夫|入ってください|入れます|使えます|触って|触れて|開けて|開けても|切ってください|入れてください|戻して|確認してきて|近づいて|ブレーカーを入れ|復電して|MΩ|メガオーム|世界初|唯一")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WITH_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(cm|mm|m|メートル|センチ|ミリ|日|時間|週間|か月|ヶ月|カ月|万円|円|kV|V|A)")
_SAME_UNIT = {"ヶ月": "か月", "カ月": "か月", "メートル": "m", "センチ": "cm", "ミリ": "mm"}


def numbers_in(text: str) -> List[str]:
    return _NUMBER.findall(text.replace(",", ""))


def numbers_with_units(text: str) -> List[str]:
    """数字と単位を組にする。「約2か月」と「約2日」を別のものとして比べるため。"""
    return [f"{number}{_SAME_UNIT.get(unit, unit)}" for number, unit in _WITH_UNIT.findall(text.replace(",", ""))]


def check_text(text: str, allowed_sources: Iterable[str], baseline: str = "") -> Optional[str]:
    """問題があれば理由を返す。数字は手元の事実と建物のデータにあるものだけを認める。

    baseline はもとの文。もとの文にある語（「扉を開けて盤に近づくのは業者だけ」など）は、増えなければ通す。
    """
    for found in _BANNED.finditer(text):
        word = found.group(0)
        if text.count(word) > baseline.count(word):
            return f"禁止の語が入っています：{word}"
    allowed = set()
    allowed_with_unit = set()
    for source in allowed_sources:
        allowed.update(numbers_in(source))
        allowed_with_unit.update(numbers_with_units(source))
    # 単位のついた数字は、単位ごと裏づけを求める。固定の cm や建物の日数を言わせないため。
    # 依頼メモや見本の番号、列挙の番号に使う小さな数字は認める。
    plain = set(allowed) | {str(i) for i in range(0, 11)}
    unknown = [number for number in numbers_with_units(text) if number not in allowed_with_unit]
    unknown += [number for number in numbers_in(text) if number not in plain]
    if unknown:
        return f"裏づけのない数字が入っています：{'、'.join(sorted(set(unknown)))}"
    return None
