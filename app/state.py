"""一枚、3D、連鎖の図、試算、チャットが共通で読む、建物ひとつ分のデータの形。

画面ごとに別のデータを持つと、同じ設備の判定が画面によって食い違う。
判定はここに置き、画面は読むだけにする。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

SCHEMA_VERSION = 1

RISK = "risk"
UNCONFIRMED = "unconfirmed"
CLEAR = "clear"
VERDICT_LABELS = {
    RISK: "リスクあり（確定）",
    UNCONFIRMED: "未確認（調査が必要）",
    CLEAR: "問題なし",
}

# 値をどの点で読んだか。代表点の地図の値は、当たっても当たらなくても未確認にする。
REPRESENTATIVE = "representative"
BUILDING = "building"
BASES = (REPRESENTATIVE, BUILDING)

# 確かめた根拠。「なし」と読めるのは図面で確かめたときだけなので、根拠を分けて持つ。
DRAWING = "drawing"
DOCUMENT = "document"
QUESTION = "question"
EVIDENCES = (DRAWING, DOCUMENT, QUESTION)

# 依頼メモの区分。①管理会社が確かめる、②業者の現地調査、③保守会社への照会・測定。
MEMO_SECTIONS = (1, 2, 3)


def _check_verdict(verdict: str) -> None:
    if verdict not in VERDICT_LABELS:
        raise ValueError(f"判定の値が決まりにありません: {verdict}")


@dataclass
class Site:
    label: str
    longitude: float
    latitude: float
    basis: str
    demo: bool = False

    def __post_init__(self):
        if self.basis not in BASES:
            raise ValueError(f"読んだ点の値が決まりにありません: {self.basis}")


@dataclass
class Row:
    """立地の一行。headline は二段表示の一段目、details と confirm_by は二段目。

    紙のおもてには summary と confirm_short を出し、全文は別紙に出す。
    """

    key: str
    label: str
    verdict: str
    headline: str
    details: List[str] = field(default_factory=list)
    confirm_by: Optional[str] = None
    verdict_label: str = ""
    records: List[str] = field(default_factory=list)
    summary: str = ""  # 紙のおもての細い表に出す短い言い方
    confirm_short: Optional[str] = None

    def __post_init__(self):
        _check_verdict(self.verdict)
        self.verdict_label = VERDICT_LABELS[self.verdict]


@dataclass
class Equipment:
    """止まるものの一行。形だけ先に決めてあり、質問と書類の段で埋まる。"""

    key: str
    label: str
    verdict: str
    headline: str
    floor: Optional[str] = None
    evidence: Optional[str] = None
    confirmed_by_person: bool = False
    details: List[str] = field(default_factory=list)
    confirm_by: Optional[str] = None
    memo_section: Optional[int] = None
    verdict_label: str = ""

    def __post_init__(self):
        _check_verdict(self.verdict)
        self.verdict_label = VERDICT_LABELS[self.verdict]
        if self.evidence is not None and self.evidence not in EVIDENCES:
            raise ValueError(f"根拠の値が決まりにありません: {self.evidence}")
        if self.memo_section is not None and self.memo_section not in MEMO_SECTIONS:
            raise ValueError(f"依頼メモの区分が決まりにありません: {self.memo_section}")

    @property
    def confirmed_on_drawing(self) -> bool:
        """図面で確かめたと読むのは、読み取りのあとに人が確かめたときだけ。"""
        return self.evidence == DRAWING and self.confirmed_by_person


@dataclass
class Pin:
    """確かめる場所のピン。ア・イ・ウ・エで呼び、依頼メモの ①②③ と重ねない。"""

    key: str
    equipment_key: str
    x: Optional[float] = None
    y: Optional[float] = None
    confirmed_by_person: bool = False


def new_state(
    site: Site,
    reading: dict,
    rows: List[Row],
    equipment: Optional[List[Equipment]] = None,
    pins: Optional[List[Pin]] = None,
    basis_note: str = "",
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "site": asdict(site),
        "location": {"reading": reading, "basis_note": basis_note, "rows": [asdict(row) for row in rows]},
        "equipment": [asdict(item) for item in equipment or []],
        "pins": [asdict(pin) for pin in pins or []],
    }
