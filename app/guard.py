"""チャットと Claude の文の囲い。感電や立入につながる答えを出さないための、プログラムの決まり。

水、立入、電気の操作に触れる質問は、AI を通さず固定の文を出す。取りこぼしより出しすぎを許す。
Claude の文は、数字と禁止の語を事後に確かめる。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional

DISCLAIMER_1 = "本シートは公開データと入力情報から作成したもので、現地の判定や安全を保証するものではない。浸水中は電気室・借室（東京電力の変圧器の部屋）・ポンプ室・EVピットに立ち入らず、復電の可否は電気主任技術者が判断する"

NO_ENGINEER_NOTE = "（電気主任技術者を選任していない建物では、東京電力パワーグリッドおよび電気工事業者が安全を確認して判断する）"


def disclaimer(has_chief_engineer: bool = True) -> str:
    """固定の文の本体は変えず、主任技術者のいない建物では括弧書きを添える。"""
    return DISCLAIMER_1 if has_chief_engineer else DISCLAIMER_1 + NO_ENGINEER_NOTE


_EMERGENCY = re.compile(r"感電|しびれ|ビリ|倒れ|意識が|呼吸|火が|火花|燃え|煙|焦げ|異臭|バチ|ショート|閉じ込め|出られない|人工呼吸|酸素|吸引器|透析|医療機器.*(止|切)|息が")
_WATER = re.compile(r"水|雨|浸|冠|濡れ|ぬれ|洪|台風|停電|断水")
_PLACE = re.compile(r"電気|受電|キュービクル|盤|ブレーカー|遮断|電源|スイッチ|ポンプ|ピット|マンホール|蓋|ふた|ハンドホール|借室|変圧器|地下|駐車場|車|スロープ|エレベーター|発電機|蓄電池|太陽光|止水板|土のう|管路|穴|電線|貯留|タンク|バルブ")
_ACT = re.compile(r"入[っるれりろ]|はい[っるれり]|降り|行[っくき]|見[にてた]|のぞ|確認し|確かめ[にたて]|様子|開け|あけ|外[しす]|触|さわ|切[っるれり]|戻|上げ|落と|塞|ふさ|詰|栓|コーキング|シーリング|止水材|ストパック|抜[いきくけ]|くみ|汲み|回[しす]|つな|使[いうえっ]|動か|かけ|乾か|洗|撮|鍵|リセット|再起動|通電|送電|復電|置きに|取りに|始め")
_PERMIT = re.compile(r"いい|よい|良い|大丈夫|平気|したい|ていい|ても|可能|できます|ますか|ます$|ます。|安全|問題ない|どうすれば|べき")
_EXPLAIN = re.compile(r"どういう|とは|なぜ|どうして|なんで|何が|何の|どこに|どれ|誰が|いくら|費用|補助|助成|総会|理事会|決議|意味|教えて|説明")
_DIRECT = re.compile(r"復電|通電|送電|再起動|リセット|電源車|電源を入れ|(垂|切れ|落ち).*電線|電線.*(垂|切れ|落ち)|(水の位置|[123]の位置).*(入れ|入っ|はい)|もう(安全|大丈夫)")
_BARE = re.compile(r"(開け|見てき|降り|入り|入っ|触り|触っ|行ってき)(ます|る|てき)")
_HOME = re.compile(r"(うちの|自分の|部屋の|各戸の|家の|自宅).*(分電盤|コンセント|家電|ブレーカー)|(冷蔵庫|洗濯機|テレビ|家電|コンセント|分電盤).*(濡|ぬれ|水|浸|使え)|(濡|ぬれ|水|浸).*(冷蔵庫|洗濯機|テレビ|家電|コンセント|分電盤)")
_FOREIGN = re.compile(r"electric|enter|breaker|switch|flood|电|进入|配电")
_FORECAST = re.compile(r"今夜|今晩|今日.*(浸水|雨)|明日.*(浸水|雨)|いつ.*雨|予報|何ミリ|降る")


def _touches_safety(message: str) -> bool:
    """説明を求めるだけの質問は通し、立入や操作に触れそうなものは止める。取りこぼしより出しすぎを許す。"""
    if _DIRECT.search(message) or _FOREIGN.search(message.lower()):
        return True
    act = bool(_ACT.search(message))
    near = bool(_PLACE.search(message) or _WATER.search(message))
    explaining = bool(_EXPLAIN.search(message))
    permission = bool(_PERMIT.search(message))
    if _WATER.search(message) and re.search(r"安全|大丈夫", message):
        return True
    if _BARE.search(message) and not explaining:
        return True
    if act and near:
        return not explaining or permission and not re.search(r"教えて|説明", message)
    return False


def fixed_answer(message: str, has_chief_engineer: bool = True) -> Optional[dict]:
    """固定の文を返す。当たらなければ None で、AI に回してよい。"""
    message = unicodedata.normalize("NFKC", message)
    notice = disclaimer(has_chief_engineer)
    if _EMERGENCY.search(message):
        return {
            "kind": "emergency",
            "text": "人が感電した、倒れている、火が出た、閉じ込められた、在宅の医療機器が止まったときは、すぐ 119 番に連絡してください。倒れている人には、電気が切れたと確かめられるまで素手で触れないでください。電気の部屋には入らず、水に近づかないでください。\n\n" + notice,
        }
    if _HOME.search(message):
        return {
            "kind": "home",
            "text": "濡れた分電盤やコンセント、家電には触らず、使わないでください。東京電力パワーグリッドか電気工事の業者に相談してください。ご自宅の中の判断は、この道具の範囲の外です。\n\n" + notice,
        }
    if _touches_safety(message):
        if has_chief_engineer:
            contact = "連絡は管理員か理事長が、主任技術者と東京電力パワーグリッドへします。電気を切っても、東京電力の設備の側や太陽光・蓄電池・発電機の側には電気が残ることがあります。"
        else:
            contact = "連絡は管理員か理事長が、東京電力パワーグリッドと管理会社へします。この建物に主任技術者はいません。"
        return {
            "kind": "safety",
            "text": (
                notice
                + "\n\n電気室・盤の部屋・東京電力の変圧器の部屋・ポンプ室・エレベーターの底に入らず、扉も開けません。"
                "水に浸かった盤、コード、ブレーカーに触れません。電気を切るために中へ入りません。"
                "歩道ぎわの蓋やマンホールは開けません。東京電力の変圧器の部屋の穴や管路に、だれも栓や止水材を入れません。垂れた電線や水に浸かった地上の変圧器には近づきません。冠水の中へ入りません。"
                + contact
                + "\n\n"
                + (
                    "排水を始める前に、東京電力パワーグリッドの切り離しと、主任技術者の開放を確かめます。"
                    if has_chief_engineer
                    else "排水を始める前に、東京電力パワーグリッドに電話で切り離しを確かめ、電気工事の業者が始めてよいと答えてから始めます。"
                )
                + "水の位置は、立ち入ってよい高さではありません。水が引いても、主任技術者（主任技術者がいない建物では東京電力パワーグリッドや電気工事業者）が安全を確かめるまで入りません。"
            ),
        }
    if _FORECAST.search(message):
        return {
            "kind": "forecast",
            "text": "この道具は予報ではなく、現時点の静的な整理です。雨や浸水の見込みは、自治体と気象庁が出す警戒レベルで確かめてください。警戒レベルが出たときに誰が何をするかは、一枚の「大雨が近づいたら」に書いています。",
        }
    return None


_BANNED = re.compile(r"安全です|安全だと|安心です|浸水しません|大丈夫です|問題ありません|構いません|入って大丈夫|入ってください|入れます|使えます|触って|触れて|開けて|開けても|切ってください|入れてください|戻して|確認してきて|近づいて|ブレーカーを入れ|復電して|MΩ|メガオーム|世界初|唯一")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WITH_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(cm|mm|m|メートル|センチ|ミリ|日|時間|週間|か月|ヶ月|カ月|万円|円|kV|V|A)")


def numbers_in(text: str) -> List[str]:
    return _NUMBER.findall(text.replace(",", ""))


def check_text(text: str, allowed_sources: Iterable[str]) -> Optional[str]:
    """問題があれば理由を返す。数字は手元の事実と建物のデータにあるものだけを認める。"""
    found = _BANNED.search(text)
    if found:
        return f"禁止の語が入っています：{found.group(0)}"
    allowed = set()
    for source in allowed_sources:
        allowed.update(numbers_in(source))
    # 単位のついた数字は小さくても裏づけを求める。固定の cm や建物の日数を言わせないため。
    with_unit = [match.group(1) for match in _WITH_UNIT.finditer(text.replace(",", ""))]
    # 依頼メモや見本の番号、列挙の番号に使う小さな数字は認める。
    plain = set(allowed) | {str(i) for i in range(0, 11)}
    unknown = [number for number in with_unit if number not in allowed]
    unknown += [number for number in numbers_in(text) if number not in plain]
    if unknown:
        return f"裏づけのない数字が入っています：{'、'.join(sorted(set(unknown)))}"
    return None
