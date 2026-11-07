"""図面の線と文字を一か所に持ち、SVG と DXF の両方へ書き出す。追加のインストールは要らない。

座標は図面の用紙の px で持つ。DXF では図ごとの縮尺で割り、実寸の mm にする。
"""

from __future__ import annotations

import html
import math
from typing import List, Optional, Tuple

FONT = 'font-family="Hiragino Sans, Yu Gothic, Noto Sans JP, sans-serif"'

# 名前: (DXF の色番号, DXF の線種, SVG の色, SVG の線幅, SVG の破線)
LAYERS = {
    "図枠": (7, "CONTINUOUS", "#111111", 1.2, ""),
    "通り芯": (1, "CENTER", "#c0392b", 0.6, "14 3 2 3"),
    "寸法": (5, "CONTINUOUS", "#2d5f9a", 0.6, ""),
    "壁": (7, "CONTINUOUS", "#111111", 0.6, ""),
    "柱": (7, "CONTINUOUS", "#111111", 0.6, ""),
    "建具": (7, "CONTINUOUS", "#111111", 0.8, ""),
    "シャッター": (7, "DASHED", "#111111", 1.0, "6 3"),
    "設備": (8, "CONTINUOUS", "#333333", 0.9, ""),
    "階段EV": (8, "CONTINUOUS", "#333333", 0.7, ""),
    "敷地": (7, "DASHDOT", "#111111", 1.6, "12 4 2 4"),
    "道路": (8, "CONTINUOUS", "#555555", 0.8, ""),
    "地盤": (8, "CONTINUOUS", "#8a8a8a", 0.5, ""),
    "引込": (5, "DASHED", "#1565c0", 1.6, "7 4"),
    "水の入り道": (4, "CONTINUOUS", "#0277bd", 1.8, ""),
    "水の位置": (4, "DASHED", "#0277bd", 1.2, "8 4"),
    "文字": (7, "CONTINUOUS", "#111111", 0.5, ""),
    # 家具・機器・仕上げの細い線と、上部にあるものの破線（2026-11-07 竣工図らしい密度にするために追加）。
    "細線": (8, "CONTINUOUS", "#3a3a3a", 0.4, ""),
    "破線": (8, "DASHED", "#3a3a3a", 0.45, "3 2"),
    # 画面で部屋の種類を見分けるための薄い塗り。CAD の線の図には要らないので DXF には書き出さない。
    "部屋の色": (9, "CONTINUOUS", "#f3f3f3", 0.0, ""),
}


class View:
    """縮尺をそろえる一つの図。scale は 1mm あたりの px。"""

    def __init__(self, left: float, top: float, scale: float):
        self.left, self.top, self.scale = left, top, scale

    def x(self, mm: float) -> float:
        return self.left + mm * self.scale

    def y(self, mm: float) -> float:
        return self.top + mm * self.scale


class Sheet:
    def __init__(self, width: int, height: int, scale: float, world_y: float = 0.0):
        self.width, self.height = width, height
        self.paper = View(0, 0, scale)
        self.view = self.paper
        self.world_y = world_y
        self.items: List[dict] = []
        # True のあいだに描いたものは DXF にだけ書き出し、画面と PDF の絵（SVG）には描かない（寸法線・通り芯など）。
        self.cad_only = False

    def _add(self, item: dict) -> None:
        if self.cad_only:
            item["cad_only"] = True
        self.items.append(item)

    def use(self, view: Optional[View]) -> None:
        self.view = view or self.paper

    def line(self, x1, y1, x2, y2, layer="建具", width=None):
        self._add({"t": "line", "p": [(x1, y1), (x2, y2)], "layer": layer, "width": width, "view": self.view})

    def path(self, points, layer="建具", closed=False, width=None):
        self._add({"t": "path", "p": list(points), "closed": closed, "layer": layer, "width": width, "view": self.view})

    def rect(self, x, y, w, h, layer="建具", width=None):
        self.path([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], layer, True, width)

    def solid(self, points, layer="壁", color=None):
        """塗りつぶし。DXF の SOLID に合わせて、3 点か 4 点にする。"""
        self._add({"t": "solid", "p": list(points), "layer": layer, "color": color, "view": self.view})

    def solid_rect(self, x, y, w, h, layer="壁", color=None):
        self.solid([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], layer, color)

    def circle(self, x, y, r, layer="建具"):
        self._add({"t": "circle", "c": (x, y), "r": r, "layer": layer, "view": self.view})

    def arc(self, x, y, r, start, end, layer="建具"):
        """画面の向きの角度で、start から end へ時計回りに描く。"""
        self._add({"t": "arc", "c": (x, y), "r": r, "a": (start, end), "layer": layer, "view": self.view})

    def text(self, x, y, value, size=11, anchor="middle", layer="文字", bold=False, color=None, rotate=0):
        lines = str(value).split("\n")
        for i, line in enumerate(lines):
            dy = (i - (len(lines) - 1) / 2) * (size + 2)
            self._add({"t": "text", "c": (x, y + dy), "s": line, "size": size, "anchor": anchor, "layer": layer, "bold": bold, "color": color, "rotate": rotate, "view": self.view})

    def arrow(self, x1, y1, x2, y2, layer="水の入り道", head=9):
        self.line(x1, y1, x2, y2, layer)
        angle = math.atan2(y2 - y1, x2 - x1)
        left = (x2 - head * math.cos(angle - 0.42), y2 - head * math.sin(angle - 0.42))
        right = (x2 - head * math.cos(angle + 0.42), y2 - head * math.sin(angle + 0.42))
        self.solid([(x2, y2), left, right], layer)

    def hatch(self, x, y, w, h, layer="地盤", gap=10.0):
        """四角の中に 45 度の線を引く。DXF でも同じ線になるよう、線そのものを持つ。"""
        total = w + h
        offset = gap
        while offset < total:
            x1, y1 = (x + offset, y) if offset <= w else (x + w, y + offset - w)
            x2, y2 = (x, y + offset) if offset <= h else (x + offset - h, y + h)
            self.line(x1, y1, x2, y2, layer)
            offset += gap

    def hatch_poly(self, points, layer="地盤", gap=10.0):
        """多角形の中に 45 度の線を引く（土の断面など）。線そのものを持つので DXF でも同じになる。"""
        points = list(points)
        if len(points) < 3:
            return
        sums = [x + y for x, y in points]
        value = min(sums) + gap
        while value < max(sums):
            hits = []
            for i, (x1, y1) in enumerate(points):
                x2, y2 = points[(i + 1) % len(points)]
                f1, f2 = x1 + y1 - value, x2 + y2 - value
                if (f1 <= 0 < f2) or (f2 <= 0 < f1):
                    t = f1 / (f1 - f2)
                    hits.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
            hits.sort()
            for (ax, ay), (bx, by) in zip(hits[0::2], hits[1::2]):
                self.line(ax, ay, bx, by, layer)
            value += gap

    # 書き出し

    def svg_body(self) -> str:
        return "".join(_svg_item(item) for item in self.items if not item.get("cad_only"))

    def dxf_entities(self) -> str:
        return "".join(_dxf_item(item, self) for item in self.items)


def _stroke(item: dict) -> str:
    _, _, color, width, dash = LAYERS[item["layer"]]
    width = item.get("width") or width
    dashed = f' stroke-dasharray="{dash}"' if dash else ""
    return f'stroke="{color}" stroke-width="{width}"{dashed} fill="none"'


def _svg_item(item: dict) -> str:
    kind = item["t"]
    if kind == "line":
        (x1, y1), (x2, y2) = item["p"]
        return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" {_stroke(item)}/>'
    if kind == "path":
        tag = "polygon" if item["closed"] else "polyline"
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in item["p"])
        return f'<{tag} points="{points}" {_stroke(item)}/>'
    if kind == "solid":
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in item["p"])
        return f'<polygon points="{points}" fill="{item["color"] or LAYERS[item["layer"]][2]}" stroke="none"/>'
    if kind == "circle":
        return f'<circle cx="{item["c"][0]:.2f}" cy="{item["c"][1]:.2f}" r="{item["r"]:.2f}" {_stroke(item)}/>'
    if kind == "arc":
        (x, y), r, (start, end) = item["c"], item["r"], item["a"]
        x1, y1 = x + r * math.cos(math.radians(start)), y + r * math.sin(math.radians(start))
        x2, y2 = x + r * math.cos(math.radians(end)), y + r * math.sin(math.radians(end))
        large = 1 if (end - start) % 360 > 180 else 0
        return f'<path d="M {x1:.2f} {y1:.2f} A {r:.2f} {r:.2f} 0 {large} 1 {x2:.2f} {y2:.2f}" {_stroke(item)}/>'
    x, y = item["c"]
    color = item["color"] or LAYERS[item["layer"]][2]
    weight = ' font-weight="600"' if item["bold"] else ""
    turn = f' transform="rotate({item["rotate"]} {x:.2f} {y:.2f})"' if item["rotate"] else ""
    return f'<text x="{x:.2f}" y="{y + item["size"] / 3:.2f}" font-size="{item["size"]}" text-anchor="{item["anchor"]}" fill="{color}" {FONT}{weight}{turn}>{html.escape(item["s"])}</text>'


# DXF は読めるソフトが一番多い R12 の形で書く。日本語は Shift_JIS にする。

def _world(view: View, sheet: Sheet, x: float, y: float) -> Tuple[float, float]:
    """用紙の px を実寸の mm にする。図の置き場所は用紙の配置に合わせる。"""
    base = sheet.paper.scale
    return (
        round(view.left / base + (x - view.left) / view.scale, 2),
        round(-(view.top / base + (y - view.top) / view.scale) + sheet.world_y, 2),
    )


def _pairs(*pairs) -> str:
    return "".join(f"{code}\n{value}\n" for code, value in pairs)


def _dxf_item(item: dict, sheet: Sheet) -> str:
    kind, layer, view = item["t"], item["layer"], item["view"]
    if layer == "部屋の色":
        return ""
    if kind == "line":
        (x1, y1), (x2, y2) = [_world(view, sheet, *point) for point in item["p"]]
        return _pairs((0, "LINE"), (8, layer), (10, x1), (20, y1), (30, 0), (11, x2), (21, y2), (31, 0))
    if kind == "path":
        out = _pairs((0, "POLYLINE"), (8, layer), (66, 1), (70, 1 if item["closed"] else 0))
        for point in item["p"]:
            x, y = _world(view, sheet, *point)
            out += _pairs((0, "VERTEX"), (8, layer), (10, x), (20, y), (30, 0))
        return out + _pairs((0, "SEQEND"), (8, layer))
    if kind == "solid":
        points = [_world(view, sheet, *point) for point in item["p"]]
        # SOLID の 3 点目と 4 点目は、四角の向かいの順に並べる。
        ordered = [points[0], points[1], points[3], points[2]] if len(points) == 4 else [points[0], points[1], points[2], points[2]]
        pairs = [(0, "SOLID"), (8, layer)]
        for i, (x, y) in enumerate(ordered):
            pairs += [(10 + i, x), (20 + i, y), (30 + i, 0)]
        return _pairs(*pairs)
    if kind == "circle":
        x, y = _world(view, sheet, *item["c"])
        return _pairs((0, "CIRCLE"), (8, layer), (10, x), (20, y), (30, 0), (40, round(item["r"] / view.scale, 2)))
    if kind == "arc":
        x, y = _world(view, sheet, *item["c"])
        start, end = item["a"]
        return _pairs((0, "ARC"), (8, layer), (10, x), (20, y), (30, 0), (40, round(item["r"] / view.scale, 2)), (50, round(-end % 360, 3)), (51, round(-start % 360, 3)))
    x, y = _world(view, sheet, *item["c"])
    height = round(item["size"] * 0.82 / view.scale, 1)
    align = {"start": 0, "middle": 1, "end": 2}[item["anchor"]]
    value = item["s"].replace("〜", "～").replace("−", "－")
    return _pairs((0, "TEXT"), (8, layer), (10, x), (20, y), (30, 0), (40, height), (1, value), (50, -item["rotate"] % 360), (7, "JP"), (72, align), (11, x), (21, y), (31, 0), (73, 2))


LTYPES = {
    "CONTINUOUS": ("Solid line", []),
    "CENTER": ("Center", [900.0, -150.0, 150.0, -150.0]),
    "DASHED": ("Dashed", [400.0, -200.0]),
    "DASHDOT": ("Dash dot", [800.0, -200.0, 100.0, -200.0]),
}


def _table(name: str, count: int, body: str) -> str:
    return _pairs((0, "TABLE"), (2, name), (70, count)) + body + _pairs((0, "ENDTAB"))


def dxf(sheets: List[Sheet]) -> bytes:
    """図面をひとつの DXF にする。"""
    header = _pairs((0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1009"), (9, "$DWGCODEPAGE"), (3, "ANSI_932"), (9, "$INSUNITS"), (70, 4), (0, "ENDSEC"))
    ltypes = ""
    for name, (description, pattern) in LTYPES.items():
        pairs = [(0, "LTYPE"), (2, name), (70, 0), (3, description), (72, 65), (73, len(pattern)), (40, sum(abs(v) for v in pattern))]
        pairs += [(49, value) for value in pattern]
        ltypes += _pairs(*pairs)
    layers = "".join(_pairs((0, "LAYER"), (2, name), (70, 0), (62, spec[0]), (6, spec[1])) for name, spec in LAYERS.items())
    style = _pairs((0, "STYLE"), (2, "JP"), (70, 0), (40, 0), (41, 1), (50, 0), (71, 0), (42, 2.5), (3, "msgothic.ttc"), (4, ""))
    tables = _pairs((0, "SECTION"), (2, "TABLES")) + _table("LTYPE", len(LTYPES), ltypes) + _table("LAYER", len(LAYERS), layers) + _table("STYLE", 1, style) + _pairs((0, "ENDSEC"))
    entities = _pairs((0, "SECTION"), (2, "ENTITIES")) + "".join(sheet.dxf_entities() for sheet in sheets) + _pairs((0, "ENDSEC"))
    return (header + tables + entities + _pairs((0, "EOF"))).encode("cp932", errors="replace")
