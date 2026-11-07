"""架空の見本の竣工図を CAD の線で描く。python3 -m scripts.draw_plans

見本ごとに、平面図の用紙（ピンを立てる図）と、基礎から塔屋までの断面の用紙を作り、
SVG と DXF に書き出す。PDF は手元の Chrome、PNG は macOS の sips で作る。

部屋の箱・図の置き場所・ピンの位置は app/samples.py が持つ。ここはその箱の中と周りに、
通り芯・寸法・柱・壁・建具・シャフト・機器・家具を描き足す（2026-11-07 竣工図らしく描き直し）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

from app.building import WATER_LEVELS  # noqa: F401  （水の位置の段は app/building.py と同じ 3 段）
from app.samples import PLAN_HEIGHT, PLAN_WIDTH, REPORTS, SAMPLES
from scripts.cad import FONT, Sheet, View, dxf  # noqa: F401

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "samples")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OPEN_AIR = {"soil", "garden"}
OUTER_WALL = 300
INNER_WALL = 150
CORE_WALL = 200
COLUMN = 800
# 階段・EV・シャフトの壁は躯体なので黒く塗る。ほかの間仕切りは二重線にする。
CORE_ROOMS = {"ev", "ev_1f", "stair", "stair_1f", "ev_pit_room"}
# 外壁に面していれば窓（サッシ）を描く部屋。地下の図（見本 A・C の 0 番）には描かない。
WINDOW_ROOMS = {"office", "trunk", "lounge", "mail", "hall", "hall_back", "lobby", "unit_101", "unit_102"}
# 部屋の箱の中に描く小さなシャフト（名前, x0, y0, x1, y1 mm）。上下の階で同じ位置に重ねる。
SHAFTS = {
    ("a", 0): [("EPS", 24500, 13800, 25750, 15000), ("DS", 39600, 6000, 40800, 7200)],
    ("a", 1): [("EPS", 24500, 13500, 25750, 15000), ("PS", 25750, 13500, 27000, 15000)],
    ("b", 0): [("EPS", 24000, 2700, 25000, 3500), ("PS", 25000, 2700, 26000, 3500)],
    ("c", 0): [("EPS", 10500, 12000, 12000, 13500), ("PS", 10500, 13500, 12000, 15000), ("DS", 10500, 15000, 12000, 16500)],
    ("c", 1): [("EPS", 10500, 12000, 12000, 13500), ("PS", 10500, 13500, 12000, 15000), ("DS", 10500, 15000, 12000, 16500)],
}
# シャフトと重ならないよう、名前を上下に寄せる部屋（部屋の高さに対する割合）。
LABEL_Y = {("a", 0, "ev_pit_room"): 0.28, ("b", 0, "hall_back"): 0.62}


def _fit_label(label, width_px, largest=14, smallest=8):
    longest = max(len(line) for line in label.split("\n")) or 1
    return max(smallest, min(largest, width_px * 0.86 / longest))


# 部屋の種類ごとの薄い塗り（画面で、電気・水・昇降・車の部屋をひと目で見分ける。2026-11-04）。
ROOM_COLORS = {
    "power": "#fbd9b0",  # 電気の部屋（受電・借室・盤・発電機）：橙
    "water": "#c9e3f6",  # 水の部屋（ポンプ・受水槽・貯留槽）：青
    "lift": "#e3dcf2",   # エレベーター・階段・PS：紫
    "car": "#e6e6e6",    # 駐車場・車路：灰
}
ROOM_KIND = {
    "elec": "power", "tr": "power", "panel_room": "power", "gen": "power",
    "pump": "water", "water_tank": "water", "tank": "water",
    "ev": "lift", "ev_1f": "lift", "stair": "lift", "stair_1f": "lift", "ev_pit_room": "lift",
    "park": "car", "park_1f": "car", "aisle": "car", "slope": "car", "parking_flat": "car",
}
# 図の上で長すぎて小さくなる部屋の名前だけ、短く書く（正式な名前は凡例とピンの説明にある）。
PLAN_SHORT_LABELS = {"tr": "借室\n（東京電力）"}
SECTION_KIND = {"電気室": "power", "受変電室": "power", "共用分電盤室": "power", "借室": "power", "発電機室": "power", "給水ポンプ室": "water", "受水槽室": "water", "雨水貯留槽": "water", "車路": "car", "EV": "lift", "階段": "lift"}


def _water_lines(sheet, x, y, w, h, gap=9.0):
    """水をためる所の印。土の斜線と分ける。"""
    yy = y + gap
    while yy < y + h:
        sheet.line(x + 2, yy, x + w - 2, yy, "寸法")
        yy += gap


class PlanView:
    """平面図を一つ描く。座標は図の左上を原点にした mm。"""

    def __init__(self, sheet, spec, left, top, scale, size, grid, sample_id="", index=0):
        self.sheet, self.spec, self.size, self.grid = sheet, spec, size, grid
        self.view = View(left, top, scale)
        self.rooms = spec["rooms"]
        self.sid, self.index = sample_id, index
        self.underground = sample_id in ("a", "c") and index == 0
        self.shafts = SHAFTS.get((sample_id, index), [])
        # 図が大きいほど小さな文字も大きくする。0.02 px/mm を基準にする。
        self.zoom = max(1.0, min(1.6, scale / 0.02))

    def px(self, x, y):
        return self.view.x(x), self.view.y(y)

    def line(self, x1, y1, x2, y2, layer="設備"):
        self.sheet.line(*self.px(x1, y1), *self.px(x2, y2), layer)

    def box(self, x0, y0, x1, y1, layer="設備"):
        px, py = self.px(x0, y0)
        self.sheet.rect(px, py, (x1 - x0) * self.view.scale, (y1 - y0) * self.view.scale, layer)

    def circle(self, x, y, r, layer="設備"):
        self.sheet.circle(*self.px(x, y), r * self.view.scale, layer)

    def label(self, x, y, value, size=8, layer="文字", bold=False, anchor="middle", rotate=0):
        # 用紙を 1400 px に縮めても読めるよう、8 px より小さな文字は使わない。
        self.sheet.text(*self.px(x, y), value, max(8, size * self.zoom), anchor, layer=layer, bold=bold, rotate=rotate)

    # 通り芯と寸法

    def draw_axes(self):
        """通り芯の丸と 2 段の寸法（mm）。図の上と左に置く。部屋を横切る長い通り芯の線は DXF だけ（draw_grid）。"""
        s = self.sheet
        xs, ys = self.grid["x"], self.grid["y"]
        top, left = self.view.y(0), self.view.x(0)
        for i, value in enumerate(xs):
            x = self.view.x(value)
            s.line(x, top - 47, x, top, "細線")
            s.circle(x, top - 55, 8, "図枠", )
            s.text(x, top - 55, f"X{i + 1}", 8)
        for i, value in enumerate(ys):
            y = self.view.y(value)
            s.line(left - 46, y, left, y, "細線")
            s.circle(left - 54, y, 8, "図枠")
            s.text(left - 54, y, f"Y{i + 1}", 8)
        self._dim_h(top - 16, xs)
        self._dim_h(top - 35, [xs[0], xs[-1]])
        self._dim_v(left - 16, ys)
        self._dim_v(left - 34, [ys[0], ys[-1]])

    def _dim_h(self, y, values):
        s = self.sheet
        xs = [self.view.x(v) for v in values]
        s.line(xs[0], y, xs[-1], y, "寸法")
        for x in xs:
            s.line(x - 3, y + 3, x + 3, y - 3, "寸法")
        for a, b, xa, xb in zip(values, values[1:], xs, xs[1:]):
            s.text((xa + xb) / 2, y - 6, f"{b - a:,}", 8, layer="寸法")

    def _dim_v(self, x, values):
        s = self.sheet
        ys = [self.view.y(v) for v in values]
        s.line(x, ys[0], x, ys[-1], "寸法")
        for y in ys:
            s.line(x - 3, y + 3, x + 3, y - 3, "寸法")
        for a, b, ya, yb in zip(values, values[1:], ys, ys[1:]):
            s.text(x - 6, (ya + yb) / 2, f"{b - a:,}", 8, layer="寸法", rotate=-90)

    def draw_grid(self):
        """部屋を横切る長い通り芯の線は DXF（CAD の図面）にだけ残し、画面と PDF の絵には描かない（部屋の色と名前を読みやすくするため。2026-11-04）。"""
        self.sheet.cad_only = True
        try:
            s = self.sheet
            top, bottom = self.view.y(0), self.view.y(self.size[1])
            left, right = self.view.x(0), self.view.x(self.size[0])
            for value in self.grid["x"]:
                x = self.view.x(value)
                s.line(x, top - 47, x, bottom + 12, "通り芯")
            for value in self.grid["y"]:
                y = self.view.y(value)
                s.line(left - 46, y, right + 12, y, "通り芯")
        finally:
            self.sheet.cad_only = False

    # 壁と建具

    def _room_at(self, x, y):
        """点 (x, y) を含む、壁で囲まれた部屋。外気（植栽・土）と図の外は None。"""
        for room in self.rooms:
            if room["key"] in OPEN_AIR or room.get("outdoor"):
                continue
            x0, y0, x1, y1 = room["mm"]
            if x0 <= x <= x1 and y0 <= y <= y1:
                return room
        return None

    def _openings(self):
        found = []
        for room in self.rooms:
            x0, y0, x1, y1 = room["mm"]
            specs = list(room.get("openings", []))
            if room.get("unit_door"):
                specs.append(room["unit_door"])
            if room.get("unit"):
                # 住戸：玄関扉は廊下側（上）、窓はバルコニー側（下）。
                specs.append({"side": "top", "at": x0 + (x1 - x0) * 0.7, "w": 900, "kind": "door"})
                specs.append({"side": "bottom", "at": (x0 + x1) / 2, "w": (x1 - x0) * 0.55, "kind": "window"})
            for spec in specs:
                side = spec["side"]
                if side in ("top", "bottom"):
                    found.append({**spec, "axis": "h", "pos": y0 if side == "top" else y1, "room": room})
                else:
                    found.append({**spec, "axis": "v", "pos": x0 if side == "left" else x1, "room": room})
        found += self._auto_windows(found)
        return found

    def _auto_windows(self, existing):
        """外壁に面した部屋の辺に、まだ建具がなければ窓を置く。"""
        if self.underground:
            return []
        windows = []
        for room in self.rooms:
            if room["key"] not in WINDOW_ROOMS or room.get("unit"):
                continue
            x0, y0, x1, y1 = room["mm"]
            for side in ("top", "bottom", "left", "right"):
                if any(o["room"] is room and o["side"] == side for o in existing):
                    continue
                if side in ("top", "bottom"):
                    pos = y0 if side == "top" else y1
                    outside = (x0 + x1) / 2, pos + (-80 if side == "top" else 80)
                    length, at, axis = x1 - x0, (x0 + x1) / 2, "h"
                else:
                    pos = x0 if side == "left" else x1
                    outside = pos + (-80 if side == "left" else 80), (y0 + y1) / 2
                    length, at, axis = y1 - y0, (y0 + y1) / 2, "v"
                if self._room_at(*outside) is not None:
                    continue
                if any(self._touches(shaft, axis, pos, x0, y0, x1, y1) for shaft in self.shafts):
                    continue
                width = min(3600, length * 0.4)
                windows.append({"side": side, "at": at, "w": width, "kind": "window", "axis": axis, "pos": pos, "room": room})
        return windows

    @staticmethod
    def _touches(shaft, axis, pos, x0, y0, x1, y1):
        _, sx0, sy0, sx1, sy1 = shaft
        if not (sx0 < x1 and sx1 > x0 and sy0 < y1 and sy1 > y0):
            return False
        return (axis == "h" and pos in (sy0, sy1)) or (axis == "v" and pos in (sx0, sx1))

    def draw_walls(self):
        edges = {}
        stops = {"h": set(), "v": set()}
        for room in self.rooms:
            if room["key"] in OPEN_AIR or room.get("outdoor"):
                continue
            x0, y0, x1, y1 = room["mm"]
            edges.setdefault(("h", y0), []).append([x0, x1])
            edges.setdefault(("h", y1), []).append([x0, x1])
            edges.setdefault(("v", x0), []).append([y0, y1])
            edges.setdefault(("v", x1), []).append([y0, y1])
            stops["h"].update((x0, x1))
            stops["v"].update((y0, y1))
        openings = self._openings()
        pieces = []
        for (axis, pos), spans in edges.items():
            merged = []
            for span in sorted(spans):
                if merged and span[0] <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], span[1])
                else:
                    merged.append(list(span))
            cuts = sorted((o["at"] - o["w"] / 2, o["at"] + o["w"] / 2) for o in openings if o["axis"] == axis and o["pos"] == pos)
            for start, end in merged:
                for a, b, style in self._classified(axis, pos, start, end, stops[axis]):
                    cursor = a
                    for cut_start, cut_end in cuts:
                        if cut_end <= cursor or cut_start >= b:
                            continue
                        pieces.append((axis, pos, cursor, max(cursor, cut_start), style, cursor != a, True))
                        cursor = min(b, cut_end)
                    pieces.append((axis, pos, cursor, b, style, cursor != a, False))
        # 二重線の間仕切りを先に、躯体の黒い壁をあとに描く（取り合いを黒で覆う）。
        for solid in (False, True):
            for axis, pos, start, end, style, cap_start, cap_end in pieces:
                if (style != "double") == solid:
                    self._wall(axis, pos, start, end, style, cap_start, cap_end)
        for opening in openings:
            self._opening(opening)

    def _classified(self, axis, pos, start, end, stops):
        """部屋の境で区切り、隣の空間が変わる所で分ける。"""
        points = sorted({start, end} | {p for p in stops if start < p < end})
        out = []
        for a, b in zip(points, points[1:]):
            style = self._style(axis, pos, a, b)
            if out and out[-1][2] == style:
                out[-1][1] = b
            else:
                out.append([a, b, style])
        return [tuple(item) for item in out]

    def _style(self, axis, pos, a, b):
        """壁の種類：外壁（outer）、階段・EV の壁（core）、間仕切り（double）。"""
        mid = (a + b) / 2
        sides = [(mid, pos - 60), (mid, pos + 60)] if axis == "h" else [(pos - 60, mid), (pos + 60, mid)]
        keys = [(room or {}).get("key") for room in (self._room_at(x, y) for x, y in sides)]
        if None in keys:
            return "outer"
        if any(k in CORE_ROOMS for k in keys):
            return "core"
        return "double"

    def _wall(self, axis, pos, start, end, style, cap_start=False, cap_end=False):
        if end <= start:
            return
        thickness = {"outer": OUTER_WALL, "core": CORE_WALL, "double": INNER_WALL}[style]
        half = thickness / 2
        s = self.view.scale
        if axis == "h":
            x, y, w, h = self.view.x(start), self.view.y(pos - half), (end - start) * s, thickness * s
        else:
            x, y, w, h = self.view.x(pos - half), self.view.y(start), thickness * s, (end - start) * s
        if style != "double":
            self.sheet.solid_rect(x, y, w, h, "壁")
            return
        self.sheet.solid_rect(x, y, w, h, "壁", color="#ffffff")
        if axis == "h":
            self.sheet.line(x, y, x + w, y, "壁")
            self.sheet.line(x, y + h, x + w, y + h, "壁")
            if cap_start:
                self.sheet.line(x, y, x, y + h, "壁")
            if cap_end:
                self.sheet.line(x + w, y, x + w, y + h, "壁")
        else:
            self.sheet.line(x, y, x, y + h, "壁")
            self.sheet.line(x + w, y, x + w, y + h, "壁")
            if cap_start:
                self.sheet.line(x, y, x + w, y, "壁")
            if cap_end:
                self.sheet.line(x, y + h, x + w, y + h, "壁")

    def _opening(self, o):
        kind, s = o["kind"], self.sheet
        scale = self.view.scale
        half = o["w"] / 2
        a, b = o["at"] - half, o["at"] + half
        # 部屋の内側へ向く向き。
        inward = {"top": 1, "left": 1, "bottom": -1, "right": -1}[o["side"]]
        if o["axis"] == "h":
            p1, p2 = self.px(a, o["pos"]), self.px(b, o["pos"])
        else:
            p1, p2 = self.px(o["pos"], a), self.px(o["pos"], b)
        if kind == "shutter":
            s.line(*p1, *p2, "シャッター")
        elif kind == "open":
            # 枠だけの開口：壁の両面の線を細く残す。
            face = (OUTER_WALL if self._style(o["axis"], o["pos"], a, b) == "outer" else INNER_WALL) / 2 * scale
            for normal in (-face, face):
                if o["axis"] == "h":
                    s.line(p1[0], p1[1] + normal, p2[0], p2[1] + normal, "細線")
                else:
                    s.line(p1[0] + normal, p1[1], p2[0] + normal, p2[1], "細線")
        elif kind == "sliding":
            normal = 2.0 * inward
            if o["axis"] == "h":
                s.line(p1[0], p1[1] + normal, (p1[0] + p2[0]) / 2 + 3, p1[1] + normal, "建具")
                s.line((p1[0] + p2[0]) / 2 - 3, p1[1] - normal, p2[0], p1[1] - normal, "建具")
            else:
                s.line(p1[0] + normal, p1[1], p1[0] + normal, (p1[1] + p2[1]) / 2 + 3, "建具")
                s.line(p1[0] - normal, (p1[1] + p2[1]) / 2 - 3, p1[0] - normal, p2[1], "建具")
        elif kind == "window":
            style = self._style(o["axis"], o["pos"], a, b)
            face = (OUTER_WALL if style == "outer" else INNER_WALL) / 2 * scale
            for normal, layer in ((-face, "細線"), (0.0, "建具"), (face, "細線")):
                if o["axis"] == "h":
                    s.line(p1[0], p1[1] + normal, p2[0], p2[1] + normal, layer)
                else:
                    s.line(p1[0] + normal, p1[1], p2[0] + normal, p2[1], layer)
            # 方立（サッシの縦枠）。
            if o["axis"] == "h":
                mid = (p1[0] + p2[0]) / 2
                s.line(mid, p1[1] - face, mid, p1[1] + face, "細線")
            else:
                mid = (p1[1] + p2[1]) / 2
                s.line(p1[0] - face, mid, p1[0] + face, mid, "細線")
        elif kind == "door":
            self._leaf(o["axis"], p1, o["w"] * scale, inward)
        elif kind == "double":
            leaf = o["w"] * scale / 2
            self._leaf(o["axis"], p1, leaf, inward)
            self._leaf(o["axis"], p2, leaf, inward, reverse=True)

    def _leaf(self, axis, hinge, size, inward, reverse=False):
        """片開きの扉と軌跡。hinge を軸に、壁から部屋の内側へ開く。"""
        s = self.sheet
        x, y = hinge
        if axis == "h":
            s.line(x, y, x, y + size * inward, "建具")
            start, end = {(1, False): (0, 90), (1, True): (90, 180), (-1, False): (270, 360), (-1, True): (180, 270)}[(inward, reverse)]
        else:
            s.line(x, y, x + size * inward, y, "建具")
            start, end = {(1, False): (0, 90), (1, True): (270, 360), (-1, False): (90, 180), (-1, True): (180, 270)}[(inward, reverse)]
        s.arc(x, y, size, start, end, "建具")

    def draw_columns(self):
        """通り芯の交点の柱。建物のない所には立てない。"""
        size = COLUMN if self.size[0] != self.size[1] else 1100
        inside = [r["mm"] for r in self.rooms if r["key"] not in OPEN_AIR and not r.get("outdoor")]
        for x in self.grid["x"]:
            for y in self.grid["y"]:
                touching = any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in inside)
                if not touching:
                    continue
                left = min(max(x - size / 2, 0), self.size[0] - size)
                top = min(max(y - size / 2, 0), self.size[1] - size)
                self.sheet.solid_rect(self.view.x(left), self.view.y(top), size * self.view.scale, size * self.view.scale, "柱")

    def draw_shafts(self):
        """EPS・PS・DS の小さなシャフト。白く抜いて細い二重線で囲む。"""
        for name, x0, y0, x1, y1 in self.shafts:
            px, py = self.px(x0, y0)
            w, h = (x1 - x0) * self.view.scale, (y1 - y0) * self.view.scale
            self.sheet.solid_rect(px, py, w, h, "壁", color="#ffffff")
            self.sheet.rect(px, py, w, h, "壁")
            self.sheet.rect(px + 2.2, py + 2.2, w - 4.4, h - 4.4, "細線")
            self.sheet.text(*self.px((x0 + x1) / 2, (y0 + y1) / 2), name, 8.5)

    # 部屋の中身

    def _symbol(self, room):
        x0, y0, x1, y1 = room["mm"]
        kind = room.get("symbol")
        cx = (x0 + x1) / 2
        w, h = x1 - x0, y1 - y0
        if kind == "cubicle":
            # キュービクルは盤の列。前面に保守の空き（破線）、壁ぎわにケーブルピット。
            bx0, bx1, by0, by1 = x0 + w * 0.15, x1 - w * 0.15, y1 - h * 0.42, y1 - h * 0.18
            self.box(bx0, by0, bx1, by1)
            panels = 4
            for i in range(1, panels):
                bx = bx0 + (bx1 - bx0) * i / panels
                self.line(bx, by0, bx, by1, "細線")
            for i in range(panels):
                hx = bx0 + (bx1 - bx0) * (i + 0.82) / panels
                self.circle(hx, (by0 + by1) / 2, 60, "細線")
            self.box(bx0 - 600, by0 - 700, bx1 + 600, by1 + 300, "破線")
            self.box(x0 + 300, y1 - 700, bx0 - 800, y1 - 300, "破線")
            self.label(cx, by0 - 330, "高圧受変電設備（キュービクル）", 8)
        elif kind == "transformer":
            self.box(x0 + w * 0.22, y1 - h * 0.34, x1 - w * 0.22, y1 - h * 0.1)
            self.label(cx, y1 - h * 0.22, "？", 12, bold=True)
            self.label(cx, y1 - h * 0.42, "中は建物側から分からない", 8)
        elif kind in ("pump", "pump_stand"):
            # 共通の架台に 2 台のポンプ（丸＋モーターの箱）、壁ぎわに制御盤、受水槽側へ吸込み管。
            r = min(w, h) * 0.07
            base_y0, base_y1 = y1 - h * 0.34, y1 - h * 0.1
            base_x0, base_x1 = cx - r * 3.4, cx + r * 3.4
            self.box(base_x0, base_y0, base_x1, base_y1, "細線")
            py = y1 - h * 0.22
            for dx in (-r * 1.7, r * 1.7):
                self.circle(cx + dx, py, r)
                self.box(cx + dx - r * 0.5, base_y0 + 60, cx + dx + r * 0.5, py - r * 0.9, "細線")
            self.line(base_x0 - 400, py, base_x0, py, "細線")
            self.line(base_x1, py, x1 - 300, py, "細線")
            self.box(x0 + w * 0.08, y1 - h * 0.34, x0 + w * 0.22, y1 - h * 0.1)
            self.label(cx, y1 - h * 0.42, "給水ポンプと制御盤（壁掛け）" if kind == "pump" else "給水ポンプと制御盤（架台の上）", 8)
            if kind == "pump_stand":
                self.box(x0 + w * 0.05, y1 - h * 0.38, x1 - w * 0.05, y1 - h * 0.11, "シャッター")
        elif kind == "panel_stand":
            self.box(x0 + w * 0.15, y1 - h * 0.34, x1 - w * 0.15, y1 - h * 0.14)
            for i in range(1, 3):
                bx = x0 + w * 0.15 + (w * 0.7) * i / 3
                self.line(bx, y1 - h * 0.34, bx, y1 - h * 0.14, "細線")
            self.box(x0 + w * 0.1, y1 - h * 0.38, x1 - w * 0.1, y1 - h * 0.11, "シャッター")
            self.label(cx, y1 - h * 0.24, "主開閉器盤（架台の上）", 8)
        elif kind == "water_tank":
            # FRP パネルの受水槽：二重の箱、パネルの目地、はしご、周りの保守の空き（破線）。
            tx0, ty0, tx1, ty1 = x0 + w * 0.2, y1 - h * 0.42, x1 - w * 0.2, y1 - h * 0.12
            self.box(tx0, ty0, tx1, ty1)
            self.box(tx0 + 100, ty0 + 100, tx1 - 100, ty1 - 100, "細線")
            gx = tx0 + 1000
            while gx < tx1 - 200:
                self.line(gx, ty0 + 100, gx, ty1 - 100, "細線")
                gx += 1000
            self.box(tx0 - 400, (ty0 + ty1) / 2 - 300, tx0 - 100, (ty0 + ty1) / 2 + 300, "細線")
            self.box(tx0 - 600, ty0 - 600, tx1 + 600, ty1 + 600, "破線")
            self.label(cx, y1 - h * 0.27, "受水槽", 8)
        elif kind == "generator":
            gx0, gy0, gx1, gy1 = x0 + w * 0.15, y1 - h * 0.32, x1 - w * 0.15, y1 - h * 0.08
            self.box(gx0, gy0, gx1, gy1)
            self.line(gx0 + (gx1 - gx0) * 0.3, gy0, gx0 + (gx1 - gx0) * 0.3, gy1, "細線")
            self.box(gx1 - (gx1 - gx0) * 0.14, gy0 + 100, gx1 - 100, gy1 - 100, "細線")
            self.line(gx1, (gy0 + gy1) / 2, x1 - 150, (gy0 + gy1) / 2, "破線")
            self.box(x0 + 300, y0 + h * 0.52, x0 + 1300, y0 + h * 0.52 + 800, "細線")
            self.label(cx, y1 - h * 0.2, "発電機", 8)
        elif kind in ("pit", "parking"):
            bays = max(3, int(w / 2400))
            for i in range(bays):
                bx = x0 + 300 + i * (w - 600) / bays
                bw = (w - 600) / bays
                self.box(bx + 150, y0 + h * 0.5, bx + bw - 150, y1 - 300, "シャッター" if kind == "pit" else "設備")
                self.label(bx + bw / 2, y1 - 650, str(i + 1), 8)
            if kind == "pit":
                self.box(x0 + 300, y0 + h * 0.5 - 300, x1 - 300, y1 - 300, "細線")
        elif kind == "parking_flat":
            bays = int(w / 2500)
            for i in range(1, bays):
                bx = x0 + i * w / bays
                self.line(bx, y0 + h * 0.15, bx, y1 - 150)
            for i in range(bays):
                bx = x0 + (i + 0.5) * w / bays
                self.label(bx, y1 - 600, str(i + 1), 8)
                self.box(bx - 700, y1 - 450, bx - 500, y1 - 250, "細線")
                self.box(bx + 500, y1 - 450, bx + 700, y1 - 250, "細線")
        elif kind == "bike":
            top = y1 - h * 0.34
            for i in range(1, int(w / 900)):
                bx = x0 + i * 900
                self.line(bx, top, bx, y1 - 150)
            self.line(x0 + 300, top + 300, x1 - 300, top + 300, "細線")
        elif kind == "slope":
            for i in range(1, 8):
                by = y0 + h * i / 8
                self.line(x0 + 200, by, x1 - 200, by, "階段EV")
            self.sheet.arrow(*self.px(cx + w * 0.3, y0 + h * 0.16), *self.px(cx + w * 0.3, y1 - h * 0.16), "建具", 8)
            self.label(cx - w * 0.14, y1 - h * 0.22, "勾配 1/6 下り", 8)
        elif kind in ("ev", "ev_bank"):
            cars = 2 if kind == "ev_bank" else 1
            for i in range(cars):
                bw = w / cars
                bx = x0 + i * bw
                car_h = min(h * 0.68, bw)
                self.box(bx + 250, y0 + 250, bx + bw - 250, y0 + car_h, "階段EV")
                self.line(bx + 250, y0 + 250, bx + bw - 250, y0 + car_h, "階段EV")
                self.line(bx + bw - 250, y0 + 250, bx + 250, y0 + car_h, "階段EV")
                # つり合いおもり（奥の壁ぎわ）。
                self.box(bx + bw / 2 - 500, y0 + car_h + 150, bx + bw / 2 + 500, y0 + car_h + 350, "細線")
        elif kind == "stair":
            self._stair(room)

    def _stair(self, room):
        """2 つの折り返しの階段：上に名前の場所、下に踊り場。踏み面と段数、UP・DN。"""
        x0, y0, x1, y1 = room["mm"]
        h = y1 - y0
        mid = (x0 + x1) / 2
        top = y0 + max(1300, h * 0.2)
        landing = y1 - max(1300, min(1800, h * 0.25))
        step = max(280, (landing - top) / 12)
        n = max(3, int((landing - top) / step))
        for i in range(n + 1):
            ty = top + i * (landing - top) / n
            self.line(x0 + 150, ty, mid - 60, ty, "階段EV")
            self.line(mid + 60, ty, x1 - 150, ty, "階段EV")
        self.line(mid - 60, top, mid - 60, landing, "設備")
        self.line(mid + 60, top, mid + 60, landing, "設備")
        self.line(mid - 60, top, mid + 60, top, "設備")
        self.line(x0 + 150, landing, x1 - 150, landing, "階段EV")
        # 矢印：左の段を上がり、右の段を下りる。
        self.sheet.arrow(*self.px((x0 + mid) / 2, landing - 150), *self.px((x0 + mid) / 2, top + 150), "階段EV", 6)
        self.sheet.arrow(*self.px((mid + x1) / 2, top + 150), *self.px((mid + x1) / 2, landing - 150), "階段EV", 6)
        self.label((x0 + mid) / 2, landing + (y1 - landing) * 0.35, "UP", 8)
        self.label((mid + x1) / 2, landing + (y1 - landing) * 0.35, "DN", 8)
        self.label(mid, landing + (y1 - landing) * 0.72, f"{2 * n}段", 8)

    def _furniture(self, room):
        """部屋の種類ごとの家具・備品。細い線で描き、名前と重ならない所に置く。"""
        key = room["key"]
        x0, y0, x1, y1 = room["mm"]
        w, h = x1 - x0, y1 - y0
        cx = (x0 + x1) / 2
        if key == "office":
            # 窓口のカウンター（ホール側）と机。
            self.box(x1 - 900, y0 + h * 0.62, x1 - 300, y1 - h * 0.12, "細線")
            self.box(x0 + w * 0.12, y1 - h * 0.34, x0 + w * 0.12 + 1600, y1 - h * 0.34 + 700, "細線")
            self.box(x0 + w * 0.12 + 500, y1 - h * 0.34 + 800, x0 + w * 0.12 + 1000, y1 - h * 0.34 + 1300, "細線")
            self.box(x0 + 300, y0 + h * 0.62, x0 + 800, y1 - h * 0.12, "細線")
        elif key == "mail":
            if h > w:
                yy = y0 + 300
                while yy + 450 <= y0 + h * 0.6:
                    self.box(x0 + 150, yy, x0 + 600, yy + 450, "細線")
                    yy += 450
            else:
                xx = x0 + 1500
                while xx + 450 <= x1 - 1500:
                    self.box(xx, y0 + 150, xx + 450, y0 + 600, "細線")
                    xx += 450
        elif key == "trunk":
            doors = list(room.get("openings", []))
            for side, ya, yb in (("top", y0 + 300, y0 + 1500), ("bottom", y1 - 1500, y1 - 300)):
                xx = x0 + 600
                while xx + 900 <= x1 - 600:
                    blocked = any(o["side"] == side and abs(o["at"] - (xx + 450)) < o["w"] / 2 + 600 for o in doors)
                    if not blocked:
                        self.box(xx, ya, xx + 900, yb, "細線")
                    xx += 900
        elif key == "store":
            xx = x0 + 600
            while xx + 1800 <= x1 - 2000:
                self.box(xx, y0 + 300, xx + 1800, y0 + 900, "細線")
                xx += 1800
            yy = y0 + 1500
            while yy + 1800 <= y1 - 600:
                self.box(x0 + 300, yy, x0 + 900, yy + 1800, "細線")
                yy += 1800
        elif key == "garbage":
            self.box(x0 + 400, y1 - 1600, x0 + 1600, y1 - 400, "破線")
            self.box(x0 + 1900, y1 - 1600, x0 + 3100, y1 - 400, "破線")
            self.circle(x1 - 700, y1 - 700, 150, "細線")
            self.line(x1 - 850, y1 - 700, x1 - 550, y1 - 700, "細線")
            self.line(x1 - 700, y1 - 850, x1 - 700, y1 - 550, "細線")
        elif key == "wind":
            self.box(x0 + w * 0.3, y0 + h * 0.3, x1 - w * 0.3, y1 - h * 0.3, "破線")
        elif key in ("hall", "lobby", "lounge", "hall_back"):
            bw = min(1800, w * 0.3)
            self.box(x0 + w * 0.12, y1 - 1100, x0 + w * 0.12 + bw, y1 - 500, "細線")
            self.box(x1 - w * 0.12 - bw, y1 - 1100, x1 - w * 0.12, y1 - 500, "細線")
            if h > 5000:
                self.circle(x0 + w * 0.12 + 300, y0 + 900, 300, "細線")
        elif key == "garden":
            for fx, fy in ((0.2, 0.22), (0.78, 0.2), (0.5, 0.78)):
                tx, ty = x0 + w * fx, y0 + h * fy
                r = min(900, min(w, h) * 0.18)
                self.circle(tx, ty, r, "細線")
                self.line(tx - r * 0.3, ty, tx + r * 0.3, ty, "細線")
                self.line(tx, ty - r * 0.3, tx, ty + r * 0.3, "細線")
        elif key == "corridor_b":
            self.line(x0 + 300, y0 + 350, x1 - 300, y0 + 350, "破線")
        elif key == "aisle":
            self.line(cx, y0 + 600, cx, y1 - 900, "破線")
            self.sheet.arrow(*self.px(cx, y1 - 1500), *self.px(cx, y1 - 500), "細線", 6)
        elif key == "tank":
            self.circle(x0 + 1500, y0 + 1500, 450, "設備")
            self.circle(x0 + 1500, y0 + 1500, 300, "細線")
            self.line(x0 + 1500, y0, x0 + 1500, y0 + 1050, "破線")

    def _unit(self, room):
        """住戸の中：MB、玄関の廊下、ユニットバス、キッチンの台、居室の間仕切り。"""
        x0, y0, x1, y1 = room["mm"]
        w, h = x1 - x0, y1 - y0
        self.box(x0 + w * 0.12, y0 + 100, x0 + w * 0.42, y0 + 700)
        self.label(x0 + w * 0.27, y0 + 400, "MB", 8)
        self.box(x0 + 500, y0 + 900, x0 + 2100, y0 + 2500, "細線")
        self.line(x0 + 2100, y0 + 900, x0 + 2100, y0 + 3400, "細線")
        self.line(x0, y0 + 3400, x0 + 2100, y0 + 3400, "細線")
        self.box(x1 - 2600, y0 + 1200, x1 - 300, y0 + 1800, "細線")
        self.line(x0, y0 + h * 0.6, x1 - 1500, y0 + h * 0.6, "細線")
        self.line(x1 - 1500, y0 + h * 0.6, x1 - 1500, y0 + h * 0.6 + 800, "細線")

    def fill_rooms(self):
        for room in self.rooms:
            kind = ROOM_KIND.get(room["key"])
            if not kind or room.get("hatch") and room["key"] != "tank":
                continue
            x0, y0, x1, y1 = room["mm"]
            px, py = self.px(x0, y0)
            self.sheet.solid_rect(px, py, (x1 - x0) * self.view.scale, (y1 - y0) * self.view.scale, "部屋の色", color=ROOM_COLORS[kind])

    def draw_rooms(self):
        for room in self.rooms:
            x0, y0, x1, y1 = room["mm"]
            if room.get("outdoor"):
                self.line(x0, y0 + 100, x1, y0 + 100, "建具")
            if room.get("hatch") and room["key"] == "tank":
                _water_lines(self.sheet, *self.px(x0, y0), (x1 - x0) * self.view.scale, (y1 - y0) * self.view.scale)
            elif room.get("hatch"):
                px, py = self.px(x0, y0)
                self.sheet.hatch(px, py, (x1 - x0) * self.view.scale, (y1 - y0) * self.view.scale)
            self._symbol(room)
            self._furniture(room)
            if room.get("unit"):
                self._unit(room)
            if not room["label"]:
                continue
            width = (x1 - x0) * self.view.scale
            # 部屋の名前は前の版の2倍まで大きくし、部屋の幅と高さに収める。
            text = PLAN_SHORT_LABELS.get(room["key"], room["label"])
            lines = len(text.split("\n"))
            height = (y1 - y0) * self.view.scale
            size = min(_fit_label(text, width * 0.95, 26 * self.zoom + 4, 8), max(8, height * 0.5 / lines))
            y = (y0 + y1) / 2
            if (self.sid, self.index, room["key"]) in LABEL_Y:
                y = y0 + (y1 - y0) * LABEL_Y[(self.sid, self.index, room["key"])]
            elif room.get("symbol") in ("cubicle", "transformer", "pump", "pump_stand", "panel_stand", "water_tank", "generator"):
                y = y0 + (y1 - y0) * 0.3
            elif room.get("symbol") in ("pit", "parking", "bike", "slope"):
                y = y0 + (y1 - y0) * 0.26
            elif room.get("symbol") in ("ev", "ev_bank"):
                size = min(size, 30)
                y = y0 + (y1 - y0) * 0.78
            elif room.get("symbol") == "stair":
                size = min(size, 30)
                y = y0 + (y1 - y0) * 0.12
            elif room["key"] in ("office", "hall", "lobby", "lounge", "hall_back", "mail", "trunk", "store", "garden"):
                y = y0 + (y1 - y0) * 0.4
            self.sheet.text(*self.px((x0 + x1) / 2, y), text, size, bold=True)

    # 図の外のもの

    def draw_mark(self, mark):
        kind = mark["kind"]
        W, H = self.size
        if kind == "road":
            self._road(mark)
            return
        x, y = self.px(mark["x"] * W, mark["y"] * H)
        s = self.sheet
        if kind == "conduit":
            s.line(x, y, *self.px(mark["x2"] * W, mark["y2"] * H), "引込")
            s.text(x + 8, (y + self.px(0, mark["y2"] * H)[1]) / 2, mark["label"], 8.5, "start", layer="寸法")
        elif kind == "hh":
            s.rect(x - 11, y - 11, 22, 22, "引込", 1.6)
            s.line(x - 11, y, x + 11, y, "寸法")
            s.text(x + 16, y, mark["label"], 8.5, "start", layer="寸法", bold=True)
        elif kind == "conduit_hole":
            s.circle(x, y, 7, "引込")
            s.text(x + 11, y + 15, mark["label"], 9, "start", layer="寸法", bold=True)
        elif kind == "basin":
            s.rect(x - 9, y - 9, 18, 18, "寸法", 1.6)
            s.line(x - 9, y - 9, x + 9, y + 9, "寸法")
            s.line(x + 9, y - 9, x - 9, y + 9, "寸法")
            s.text(x, y + 18, mark["label"], 8.5, layer="寸法")
        elif kind == "pole":
            s.circle(x, y, 5, "設備")
            s.line(x, y, *self.px(mark["x2"] * W, mark["y2"] * H), "引込")
            s.text(x - 8, y + 2, mark["label"], 8.5, "end", layer="寸法")
        elif kind == "door_low":
            s.solid_rect(x - 30, y - 3, 60, 6, "寸法")
            s.text(x, y + 15, mark["label"], 8.5, layer="寸法", bold=True)

    def _road(self, mark):
        W, H = self.size
        s, scale = self.sheet, self.view.scale
        margin = 1000
        # 境界線は通り芯の丸と寸法の外に置く。上の辺は、2 つの図を縦に並べる用紙では描かない。
        left, right = self.view.x(0) - 64, min(self.view.x(W) + 40, PLAN_WIDTH - 24)
        site_bottom = self.view.y(H + margin)
        site_top = self.view.y(0) - 68
        if mark.get("slope"):
            s.path([(left, site_top), (right, site_top), (right, site_bottom), (left, site_bottom)], "敷地", True)
        else:
            s.path([(left, self.view.y(0)), (left, site_bottom), (right, site_bottom), (right, self.view.y(0))], "敷地")
        walk = site_bottom + 2500 * scale
        road_left = max(left - 30, 24)
        s.line(road_left, site_bottom, right + 10, site_bottom, "道路")
        s.line(road_left, walk, right + 10, walk, "道路")
        if mark.get("slope"):
            s.text(self.view.x(W * 0.72), (site_bottom + walk) / 2, mark["label"], 8.5, layer="道路")
            s.text(right + 6, site_top, "丘の側（高い）", 8.5, "start", layer="道路", bold=True)
            s.text(right + 14, walk, "前の道路（低い）", 8.5, "start", layer="道路", bold=True)
            s.arrow(right + 24, self.view.y(0), right + 24, self.view.y(H), "道路", 8)
            s.text(right + 12, self.view.y(H / 2), "下り", 8, layer="道路", rotate=-90)
        else:
            s.text(self.view.x(W * 0.72), (site_bottom + walk) / 2, "歩道", 9, layer="道路", bold=True)
            s.text(self.view.x(W * 0.9), walk + 13, "公道（前面道路）", 9, layer="道路", bold=True)
            # 歩道の縁石の線。
            s.line(road_left, site_bottom + 4, right + 10, site_bottom + 4, "細線")
        entrance = self.view.x(W * 0.46)
        s.solid([(entrance, site_bottom - 7), (entrance - 6, site_bottom + 3), (entrance + 6, site_bottom + 3)], "図枠")
        s.text(entrance, site_bottom + 12, "マンション出入口", 8, layer="道路")

    def draw_balconies(self):
        if self.spec.get("balcony_ring"):
            W, H = self.size
            self.box(0, 0, W, H, "建具")
            self.label(W / 2, 900, "バルコニー", 8)
            self.label(W / 2, H - 900, "バルコニー", 8)
            return
        units = [r["mm"] for r in self.rooms if r.get("unit")]
        if not units:
            return
        bottom = max(u[3] for u in units)
        depth = 900
        for i, (x0, _, x1, _) in enumerate(units):
            self.box(x0 + 80, bottom, x1 - 80, bottom + depth, "建具")
            self.line(x0 + 80, bottom + depth - 120, x1 - 80, bottom + depth - 120, "細線")
            self.label(x0 + (x1 - x0) * (0.3 if i == 0 else 0.5), bottom + depth / 2, "バルコニー", 8)
        hatch_x = units[0][2] - 1000
        self.box(hatch_x, bottom + 200, hatch_x + 600, bottom + 700)
        self.line(hatch_x, bottom + 200, hatch_x + 600, bottom + 700, "細線")
        self.label(hatch_x - 1100, bottom + 450, "避難ハッチ", 8)

    def draw(self, scale_text):
        s = self.sheet
        s.use(self.view)
        self.fill_rooms()
        self.draw_axes()
        self.draw_grid()
        self.draw_rooms()
        self.draw_walls()
        self.draw_shafts()
        self.draw_columns()
        for mark in self.spec.get("marks", []):
            self.draw_mark(mark)
        self.draw_balconies()
        s.use(None)


def title_of(sheet, x, y, name, scale_text):
    sheet.text(x, y, f"{name}　{scale_text}", 13, bold=True)
    sheet.line(x - 110, y + 11, x + 110, y + 11, "図枠", 1)


def north(sheet, x, y):
    sheet.circle(x, y, 14, "図枠")
    sheet.solid([(x, y - 18), (x - 5, y + 9), (x + 5, y + 9)], "図枠")
    sheet.text(x, y - 27, "N", 10, bold=True)


LEGEND = [
    ("wall", "壁（躯体は黒、間仕切りは二重線）"),
    ("column", "柱"),
    ("door", "片開き扉・両開き扉"),
    ("window", "窓（サッシ）"),
    ("shutter", "シャッター"),
    ("site", "敷地境界線"),
    ("conduit", "引込管路（地中）"),
    ("fill:power", "電気の部屋"),
    ("fill:water", "水の部屋"),
    ("fill:lift", "EV・階段"),
]


def legend(sheet, x0, y0, aerial=False, columns=False):
    sheet.text(x0, y0, "凡例", 11, "start", bold=True)
    for i, (kind, name) in enumerate(LEGEND):
        x = x0 + (i % 3) * 230 if columns else x0
        yy = y0 + 24 + (i // 3) * 24 if columns else y0 + 22 + i * 22
        if kind == "wall":
            sheet.solid_rect(x, yy - 2, 30, 4, "壁")
        elif kind == "column":
            sheet.solid_rect(x + 9, yy - 6, 12, 12, "柱")
        elif kind == "door":
            sheet.line(x + 8, yy + 6, x + 8, yy - 6, "建具")
            sheet.arc(x + 8, yy + 6, 12, 270, 360, "建具")
        elif kind == "window":
            for dy, layer in ((-3, "細線"), (0, "建具"), (3, "細線")):
                sheet.line(x, yy + dy, x + 30, yy + dy, layer)
        elif kind == "shutter":
            sheet.line(x, yy, x + 30, yy, "シャッター")
        elif kind == "site":
            sheet.line(x, yy, x + 30, yy, "敷地")
        elif kind == "conduit":
            sheet.line(x, yy, x + 30, yy, "引込")
        elif kind.startswith("fill:"):
            sheet.solid_rect(x, yy - 7, 30, 14, "部屋の色", color=ROOM_COLORS[kind[5:]])
            sheet.rect(x, yy - 7, 30, 14, "設備", 0.6)
        text = "引込線（空中）" if aerial and kind == "conduit" else name
        if columns and kind == "wall":
            text = "壁（躯体・間仕切り）"
        sheet.text(x + 40, yy, text, 10.5 if columns else 11, "start")


def frame_and_title(sheet, sample, drawing_name, number, scale_text):
    sheet.rect(16, 16, PLAN_WIDTH - 32, PLAN_HEIGHT - 32, "図枠", 2)
    sheet.text(PLAN_WIDTH - 36, 40, "※架空の見本です。実在の建物の図面ではありません。", 13, "end", bold=True)
    x, y, w = PLAN_WIDTH - 356, PLAN_HEIGHT - 124, 336
    rows = [("工事名称", f"{sample['name']} 新築工事"), ("図面名称", drawing_name), ("縮尺", scale_text), ("図番", number)]
    sheet.rect(x, y, w, 104, "図枠", 1.6)
    for i, (name, value) in enumerate(rows):
        yy = y + 26 * i
        if i:
            sheet.line(x, yy, x + w, yy, "図枠", 0.8)
        sheet.text(x + 8, yy + 13, name, 9, "start")
        sheet.text(x + 68, yy + 13, value, 10.5, "start", bold=True)
    sheet.line(x + 60, y, x + 60, y + 104, "図枠", 0.8)


def plan_sheet(sample):
    W, H = sample["plan_size"]
    frames = sample["plan_frames"]
    scale = frames[0][2] / W
    sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, scale)
    frame_and_title(sheet, sample, "竣工図 平面図（機器のある階と1階）", f"A-1{'01' if sample['id'] == 'a' else '11' if sample['id'] == 'b' else '21'}", "S=1/100（用紙に合わせて縮小）")
    for index, (left, top, width) in frames.items():
        spec = sample["views"][index]
        PlanView(sheet, spec, left, top, scale, (W, H), sample["grid"], sample["id"], index).draw("S=1/100")
        extra = 100 if any(m["kind"] == "road" for m in spec.get("marks", [])) else 22
        title_of(sheet, left + width / 2, top + H * scale + extra, spec["name"], "S=1/100")
    if sample["id"] == "a":
        north(sheet, 1110, 120)
        legend(sheet, 1070, 190)
    else:
        north(sheet, 70 + 40, 850)
        legend(sheet, 200, 836, aerial=sample["id"] == "b", columns=True)
    return sheet


# 断面図

def _pin(sheet, x, y, key):
    sheet.circle(x, y, 13, "図枠")
    sheet.text(x, y, key, 13, bold=True)


def _level_mark(sheet, x, y, key):
    sheet.circle(x, y, 10, "水の入り道")
    sheet.text(x, y, str(key), 10.5, color="#0277bd", bold=True)


# 断面の部屋の名前と、重ね絵での扱い。power は盤・高圧受変電設備の部屋（サーバーの wet の hv で浸かるかを決める）、
# tr は借室（中は描かない）、floor は一番低い床の続きの部屋。
_ROOM_ROLES = {
    "電気室": "power",
    "受変電室": "power",
    "共用分電盤室": "power",
    "借室": "tr",
    "給水ポンプ室": "floor",
    "受水槽室": "floor",
    "発電機室": "floor",
    "雨水貯留槽": "floor",
    "車路": "floor",
    "エントランス": "floor",
    "EV": "floor",
    "階段": "floor",
}


def _section_short(sample):
    """水の位置①②③の短い言い方。断面図の凡例と画面の重ね絵で同じ文を使う。"""
    short = {1: "道路・スロープ・壁の穴に達した", 2: "一番低い床に達した", 3: "盤・高圧受変電設備の下端に達した"}
    if not sample["underground_feed"]:
        short[1], short[3] = "前の道路・坂下の扉に達した", "架台の上の盤の下端に達した"
    return short


def _section_key(sheet, sample, x, y):
    """断面の読み方を短く、右の列に縦に並べる。長い説明は書かない。"""
    sheet.text(x, y, "水の位置（画面の①②③）", 12, "start", bold=True)
    short = _section_short(sample)
    for i in (1, 2, 3):
        _level_mark(sheet, x + 10, y + 26 * i, i)
        sheet.text(x + 28, y + 26 * i, short[i], 11, "start")
    notes = ["破線は模式。高さの値ではありません。", "部屋ごとに同じ高さになるとは限りません。", "借室の中の機器の高さは分かりません。"]
    if sample["underground_feed"]:
        notes.append("壁の穴の止水の有無は図から分かりません。")
    for i, note in enumerate(notes):
        sheet.text(x, y + 108 + 16 * i, note, 10.5, "start", color="#0277bd", bold=i == 0)
    entries = {"elec", "slope", "door", "tank"}
    yy = y + 108 + 16 * len(notes) + 22
    for heading, pins in (("水の入り道", [p for p in sample["pins"] if p["target"] in entries]), ("水に弱い設備", [p for p in sample["pins"] if p["target"] not in entries])):
        sheet.text(x, yy, heading, 12, "start", bold=True)
        for i, pin in enumerate(pins):
            _pin(sheet, x + 13, yy + 28 + 30 * i, pin["key"])
            sheet.text(x + 34, yy + 28 + 30 * i, pin["title"], 11, "start")
        yy += 28 + 30 * len(pins) + 18
    # 断面の記号。
    sheet.text(x, yy, "断面の記号", 12, "start", bold=True)
    rows = [("solid", "床スラブ・梁・柱・壁（躯体）"), ("thin", "間仕切り・天井・家具"), ("axis", "通り芯（X・Z）と階高（mm）"), ("water", "水の位置（模式の破線）")]
    for i, (kind, name) in enumerate(rows):
        ry = yy + 24 + 20 * i
        if kind == "solid":
            sheet.solid_rect(x, ry - 3, 30, 6, "壁")
        elif kind == "thin":
            sheet.line(x, ry, x + 30, ry, "細線")
        elif kind == "axis":
            sheet.line(x, ry, x + 30, ry, "通り芯")
        else:
            sheet.line(x, ry, x + 30, ry, "水の位置")
        sheet.text(x + 40, ry, name, 10.5, "start")


class Sec:
    """断面図の座標。x は展開の mm、z は GL を 0 とした高さの mm。zmap で上の階を縮める。"""

    def __init__(self, sheet, left, base, scale, zmap=None):
        self.sheet, self.left, self.base, self.s = sheet, left, base, scale
        self.zmap = zmap or (lambda z: z)

    def X(self, mm):
        return self.left + mm * self.s

    def Z(self, mm):
        return self.base - self.zmap(mm) * self.s

    def solid(self, x0, z0, x1, z1, layer="壁", color=None):
        self.sheet.solid_rect(self.X(x0), self.Z(z1), (x1 - x0) * self.s, self.Z(z0) - self.Z(z1), layer, color)

    def rect(self, x0, z0, x1, z1, layer="設備", width=None):
        self.sheet.rect(self.X(x0), self.Z(z1), (x1 - x0) * self.s, self.Z(z0) - self.Z(z1), layer, width)

    def line(self, x0, z0, x1, z1, layer="細線", width=None):
        self.sheet.line(self.X(x0), self.Z(z0), self.X(x1), self.Z(z1), layer, width)

    def text(self, x, z, value, size=9, anchor="middle", **kw):
        self.sheet.text(self.X(x), self.Z(z), value, size, anchor, **kw)

    # 部品

    def partition(self, x, z0, z1, t=100):
        """間仕切り：白く抜いて細い二重線。"""
        self.solid(x - t / 2, z0, x + t / 2, z1, "壁", color="#ffffff")
        self.line(x - t / 2, z0, x - t / 2, z1)
        self.line(x + t / 2, z0, x + t / 2, z1)

    def door(self, x, z, h=2000, t=300):
        """壁を抜いた扉：白で抜き、薄い扉の線。"""
        self.solid(x - t / 2, z, x + t / 2, z + h, "壁", color="#ffffff")
        self.line(x - t / 2, z, x - t / 2, z + h)
        self.line(x + t / 2, z, x + t / 2, z + h)
        self.line(x - 25, z, x - 25, z + h, "建具")
        self.line(x + 25, z, x + 25, z + h, "建具")

    def sash(self, x, z0, z1, t=300):
        """壁を抜いた窓：白で抜き、ガラスの線と枠。"""
        self.solid(x - t / 2, z0, x + t / 2, z1, "壁", color="#ffffff")
        self.line(x, z0, x, z1, "建具")
        self.line(x - 40, z0, x - 40, z1)
        self.line(x + 40, z0, x + 40, z1)
        self.line(x - t / 2, z0, x + t / 2, z0)
        self.line(x - t / 2, z1, x + t / 2, z1)

    def parapet(self, x, z, h=1100, t=150):
        self.solid(x, z, x + t, z + h)
        self.line(x - 30, z + h, x + t + 30, z + h, "建具")

    def steps(self, x0, z0, x1, z1, n, layer="階段EV"):
        """x0,z0 から x1,z1 へ上がる段の線。"""
        points = []
        for i in range(n):
            xa = x0 + (x1 - x0) * i / n
            xb = x0 + (x1 - x0) * (i + 1) / n
            za = z0 + (z1 - z0) * i / n
            zb = z0 + (z1 - z0) * (i + 1) / n
            points += [(self.X(xa), self.Z(za)), (self.X(xa), self.Z(zb)), (self.X(xb), self.Z(zb))]
        self.sheet.path(points, layer)
        # 段の裏の線（ささら）。
        self.line(x0, z0 - 250, x1, z1 - 250, layer)


def _building(sec, sp):
    """基礎から塔屋までの建物。sp は mm の寸法の辞書。戻り値は階の高さの一覧（Z 軸に使う）など。"""
    wl, wr = sp["build_left"], sp["build_right"]
    ur = sp.get("upper_right", wr)
    wall = 300
    b1 = sp.get("b1")
    f1, f2, fh, n = sp["floor_1"], sp["floor_2"], sp["floor_h"], sp["floors"]
    levels = {1: f1, 2: f2}
    for k in range(3, n + 1):
        levels[k] = f2 + (k - 2) * fh
    rfl = levels[n] + fh
    drawn = sp.get("drawn_floors") or list(range(2, n + 1))
    ev0, ev1 = sp["ev"]
    st0, st1 = sp["stair"]
    tower_top = rfl + 3000
    lf = b1 if b1 is not None else f1
    found = lf - 1800
    bottom = lf - 2600
    cols = sp["columns"]
    room_top = sp["room_top"]
    slab_levels = sorted({levels[k] for k in drawn} | {levels[k + 1] for k in drawn if k + 1 <= n} | {rfl})

    # 部屋の種類の薄い塗り（機器のある階）。
    for i, (x, name) in enumerate(sp["rooms"]):
        room_end = sp["rooms"][i + 1][0] if i + 1 < len(sp["rooms"]) else wr - wall
        kind = SECTION_KIND.get(name)
        if kind:
            sec.solid(x, lf, room_end, room_top, "部屋の色", ROOM_COLORS[kind])

    # 基礎：耐圧版、基礎梁、ピット。
    sec.solid(wl, lf - 300, wr, lf)
    for x in cols:
        if wl <= x <= wr:
            sec.solid(x - 300, found, x + 300, lf - 300)
    sec.solid(wl, found, wl + wall, lf)
    sec.solid(wr - wall, found, wr, lf)
    sec.line(wl - 600, found, wr + 600, found)
    sec.line(wl - 600, found - 150, wr + 600, found - 150, "破線")
    # EV のピットは深い。
    sec.solid(ev0, lf - 1500, ev1, lf, "壁", "#ffffff")
    sec.solid(ev0 - 200, lf - 1800, ev0, lf)
    sec.solid(ev1, lf - 1800, ev1 + 200, lf)
    sec.solid(ev0, lf - 1800, ev1, lf - 1500)
    sec.rect(ev0 + 500, lf - 1500, ev0 + 900, lf - 1100, "設備")
    sec.rect(ev1 - 900, lf - 1500, ev1 - 500, lf - 1100, "設備")
    sec.text((ev0 + ev1) / 2, lf - 750, "ピット", 8.5)

    # 機器のある階の壁と間仕切り。
    sec.solid(wl, lf, wl + wall, room_top + 300)
    for i, (x, name) in enumerate(sp["rooms"]):
        if i:
            sec.solid(x, lf, x + 150, room_top)
    sec.solid(wr - wall, lf, wr, room_top + 300)
    if b1 is not None:
        # 1 階の床と、1 階の部屋。
        sec.solid(wl, f1 - 300, wr, f1)
        for x in cols:
            if wl < x < wr:
                sec.solid(x - 250, f1 - 1000, x + 250, f1 - 300)
        sec.solid(wl, f1 - 300, wl + wall, levels[2])
        sec.solid(ur - wall, f1 - 300, ur, levels[2])
        first = sp["first"]
        for i, (x, name) in enumerate(first):
            if i:
                if name in ("EV", "階段"):
                    sec.solid(x, f1, x + 150, levels[2])
                elif i == 1:
                    sec.sash(x, f1 + 100, f1 + 2600, 150)
                else:
                    sec.partition(x, f1, f1 + 2700)
            room_end = first[i + 1][0] if i + 1 < len(first) else ur - wall
            if name not in ("EV", "階段"):
                sec.line(x + 100, f1 + 2700, room_end - 100, f1 + 2700)
                sec.text((x + room_end) / 2, f1 + 2950, name, _fit_label(name, (room_end - x) * sec.s, 10.5, 8), bold=True)
        # 玄関：左の壁を抜いた自動扉。
        sec.door(wl + wall / 2, f1, 2200, wall)
    else:
        sec.solid(wl, room_top, wl + wall, levels[2])
        sec.solid(wr - wall, room_top, wr, levels[2])

    # 上の階：床スラブ、梁、廊下・住戸・バルコニー。
    upper = sp["upper"]
    for z in slab_levels:
        sec.solid(wl, z - 200, ur, z)
        for x in cols:
            if wl < x < ur:
                sec.solid(x - 225, z - 900, x + 225, z - 200)
    for k in drawn:
        z0 = levels[k]
        z1 = levels[k + 1] if k < n else rfl
        for kind, x0, x1, inner in upper:
            if kind == "corridor":
                sec.parapet(x0, z0)
                sec.solid(x1 - 100, z0, x1 + 100, z1 - 200)
                sec.door(x1, z0, 2000, 200)
                if k == drawn[0]:
                    sec.text((x0 + x1) / 2, z0 + 1700, "廊下", 8)
            elif kind == "balcony":
                outer, inner_x = (x1 - 150, x0) if inner == "right" else (x0, x1)
                sec.parapet(outer, z0)
                sec.solid(inner_x - 100, z0, inner_x + 100, z1 - 200)
                sec.sash(inner_x, z0 + 100, z0 + 2100, 200)
                if k == drawn[0]:
                    sec.text((x0 + x1) / 2, z0 + 1700, "ﾊﾞﾙｺﾆｰ", 8)
            elif kind == "unit":
                sec.line(x0 + 100, z0 + 2400, x1 - 100, z0 + 2400)
                for j, px in enumerate(inner):
                    sec.partition(px, z0, z0 + 2400)
                    if j == 0:
                        sec.door(px, z0, 2000, 100)
                sec.rect(x1 - 1900, z0, x1 - 400, z0 + 850, "細線")
                sec.text((x0 + x1) / 2, z0 + 2000, "住戸", 9)
            elif kind == "wall":
                sec.solid(x0, z0, x1, z1)
    # EV シャフト（ピットから塔屋まで）。
    sec.solid(ev0, lf - 1500, ev0 + 200, tower_top - 200)
    sec.solid(ev1 - 200, lf - 1500, ev1, tower_top - 200)
    sec.line(ev0 + 320, lf - 1500, ev0 + 320, rfl)
    sec.line(ev1 - 320, lf - 1500, ev1 - 320, rfl)
    sec.solid(ev0, rfl, ev1, rfl + 200, "壁", "#ffffff")
    stops = ([b1] if b1 is not None else []) + [f1] + [levels[k] for k in drawn]
    for z in stops:
        sec.door(ev0 + 100, z, 2100, 200)
    car_z = f1
    sec.rect(ev0 + 450, car_z + 80, ev1 - 450, car_z + 2500, "設備")
    sec.rect(ev0 + 600, car_z + 80, ev1 - 600, car_z + 2300, "細線")
    sec.text((ev0 + ev1) / 2, car_z + 1300, "EV", 11, bold=True)
    sec.rect(ev1 - 420, car_z + 1500, ev1 - 300, car_z + 4300, "細線")
    sec.line((ev0 + ev1) / 2, car_z + 2500, (ev0 + ev1) / 2, rfl + 800, "細線")
    # 塔屋（EV 機械室）。
    sec.solid(ev0 - 200, rfl, ev0, tower_top)
    sec.solid(st1, rfl, st1 + 200, tower_top)
    sec.solid(ev0 - 200, tower_top - 200, st1 + 200, tower_top)
    sec.rect(ev0 + 400, rfl + 500, ev1 - 400, rfl + 1300, "設備")
    sec.sheet.circle(sec.X((ev0 + ev1) / 2), sec.Z(rfl + 900), 260 * sec.s, "設備")
    sec.text((ev1 + st1) / 2, rfl + 2200, "EV機械室", 9)
    sec.door(st1 + 100, rfl, 2000, 200)
    # 階段：折り返しの段と踊り場。
    stair_levels = ([b1] if b1 is not None else []) + [f1] + [levels[k] for k in drawn]
    all_stops = sorted(set(stops + [rfl]))
    for z in stair_levels:
        nxt = next((t for t in all_stops if t > z), None)
        if nxt is None or nxt - z > fh * 2.5:
            continue
        h = nxt - z
        mid = z + h / 2
        count = max(6, int(h / 2 / 190))
        sec.steps(st0 + 250, z, st1 - 1000, mid, count)
        sec.solid(st1 - 1000, mid - 150, st1 - 200, mid)
        sec.steps(st1 - 1000, mid, st0 + 250, nxt, count, "破線")
        sec.line(st0 + 250, z + 900, st1 - 1000, mid + 900, "破線")
    # 屋上のパラペット。
    sec.parapet(wl, rfl, 1100, 150)
    sec.parapet(ur - 150, rfl, 1100, 150)
    # 通り芯（縦）と X の丸。
    top_z = tower_top + 1800
    for i, x in enumerate(cols):
        sec.line(x, bottom + 300, x, top_z, "通り芯")
        sec.sheet.circle(sec.X(x), sec.Z(top_z) - 10, 8.5, "図枠")
        sec.sheet.text(sec.X(x), sec.Z(top_z) - 10, f"X{i + 1}", 8.5)
    shown = sorted(set(drawn) | {k + 1 for k in drawn if k + 1 <= n})
    names = ([("B1FL", b1)] if b1 is not None else []) + [("1FL", f1)] + [(f"{k}FL", levels[k]) for k in shown] + [("RFL", rfl)]
    return {"levels": names, "rfl": rfl, "tower_top": tower_top, "bottom": bottom, "found": found, "lf": lf}


def _z_axis(sec, names, x_bub, x_dim, x_stub, right=False, breaks=None):
    """Z の丸、階の名前、階高の寸法。right が True なら名前と寸法を丸の左に置く。"""
    sheet = sec.sheet
    breaks = breaks or {}
    for i, (name, z) in enumerate(names):
        y = sec.Z(z)
        sheet.circle(sec.X(x_bub), y, 9, "図枠")
        sheet.text(sec.X(x_bub), y, f"Z{i + 1}", 8.5)
        sheet.text(sec.X(x_bub) + (-13 if right else 13), y, name, 8.5, "end" if right else "start", layer="寸法")
        sheet.line(sec.X(x_dim), y, sec.X(x_stub), y, "通り芯")
    xs = sec.X(x_dim)
    sheet.line(xs, sec.Z(names[0][1]), xs, sec.Z(names[-1][1]), "寸法")
    for (na, za), (nb, zb) in zip(names, names[1:]):
        for z in (za, zb):
            sheet.line(xs - 3, sec.Z(z) + 3, xs + 3, sec.Z(z) - 3, "寸法")
        text = breaks.get((na, nb), f"{zb - za:,}")
        sheet.text(xs + (7 if right else -7), (sec.Z(za) + sec.Z(zb)) / 2, text, 8.5, layer="寸法", rotate=-90)


def section_underground(sheet, sample, view, left, base):
    """地下に機器がある建物の断面。機器の階は順に並べた展開で、実際の並びとは違う。"""
    s = view.scale
    has_gen = sample["id"] == "c"
    wall, slab = 300, 300
    build_left = 9000
    floor_1, top_2, b1 = 500, 4300, -4500
    level_3 = b1 + 1300
    pipe = -2200
    if has_gen:
        rooms = [(9300, "受変電室"), (13500, "借室"), (16500, "発電機室"), (19500, "給水ポンプ室"), (23000, "受水槽室"), (26000, "EV"), (28400, "階段"), (31300, "雨水貯留槽"), (34800, "車路")]
        build_right, upper_right = 38800, 31300
        ev, stair = (26000, 28400), (28400, 31000)
        first = [(9300, "風除室"), (11400, "エントランスホール"), (19500, "防災センター"), (23000, "ラウンジ"), (26000, "EV"), (28400, "階段")]
        upper = [("balcony", 9300, 10800, "left"), ("unit", 10800, 26000, [13500, 16500, 19500, 23000]), ("wall", 31000, 31300, None)]
        columns = [9300, 16500, 23000, 26000, 31000, 34800, 38500]
        floors, drawn = 38, [2, 3, 4, 5, 6, 36, 37, 38]
    else:
        rooms = [(9300, "電気室"), (14700, "借室"), (18300, "給水ポンプ室"), (22200, "受水槽室"), (25800, "EV"), (28000, "階段"), (30700, "車路")]
        build_right, upper_right = 34800, 34800
        ev, stair = (25800, 28000), (28000, 30700)
        first = [(9300, "風除室"), (11400, "エントランスホール"), (18300, "管理員室"), (22200, "トランクルーム"), (25800, "EV"), (28000, "階段"), (30700, "駐輪場")]
        upper = [("corridor", 9300, 10800, None), ("unit", 10800, 25800, [14700, 18300, 22200]), ("unit", 30700, 33300, [32000]), ("balcony", 33300, 34800, "right")]
        columns = [9300, 14700, 22200, 25800, 30700, 34500]
        floors, drawn = sample["floors"], None
    slope_top = build_right + 5500
    scene_end = slope_top + 2200
    zmap = None
    if has_gen:
        lo, hi, gap = 18800, 4300 + 34 * 2900, 3600

        def zmap(z, lo=lo, hi=hi, gap=gap):
            if z <= lo:
                return z
            if z >= hi:
                return z - (hi - lo) + gap
            return lo + (z - lo) * gap / (hi - lo)
    sec = Sec(sheet, left, base, s, zmap)
    X, Zf = sec.X, sec.Z
    bottom = b1 - 2600
    # 道路・歩道・土。
    sheet.line(X(0), Zf(0), X(4500), Zf(0), "道路", 2)
    sheet.line(X(4500), Zf(0), X(4500), Zf(150), "道路", 2)
    sheet.line(X(4500), Zf(150), X(build_left), Zf(150), "道路", 2)
    sec.line(0, -250, 4500, -250, "細線")
    sheet.text(X(1400), Zf(0) - 12, "公道（前面道路）", 11, layer="道路", bold=True)
    sheet.text(X(7900), Zf(150) - 12, "歩道", 11, layer="道路", bold=True)
    sheet.text(X(0) + 4, Zf(0) + 12, "GL±0", 8.5, "start", layer="寸法")
    hh_x, hh_w = 5900, 1100
    sheet.hatch_poly([(X(700), Zf(0) + 2), (X(4500), Zf(0) + 2), (X(4500), Zf(150) + 2), (X(hh_x), Zf(150) + 2), (X(hh_x), Zf(bottom)), (X(700), Zf(bottom))], gap=18)
    sheet.hatch_poly([(X(hh_x + hh_w), Zf(150) + 2), (X(build_left), Zf(150) + 2), (X(build_left), Zf(bottom)), (X(hh_x + hh_w), Zf(bottom))], gap=18)
    sheet.hatch_poly([(X(build_left), Zf(b1 - 1950)), (X(build_right), Zf(b1 - 1950)), (X(build_right), Zf(bottom)), (X(build_left), Zf(bottom))], gap=18)
    sheet.hatch_poly([(X(build_right), Zf(b1 + 300)), (X(slope_top), Zf(150)), (X(scene_end), Zf(150)), (X(scene_end), Zf(bottom)), (X(build_right), Zf(bottom))], gap=18)
    # 建物。
    info = _building(sec, {
        "build_left": build_left, "build_right": build_right, "upper_right": upper_right, "b1": b1, "floor_1": floor_1, "floor_2": top_2,
        "floor_h": 2900, "floors": floors, "drawn_floors": drawn, "ev": ev, "stair": stair, "rooms": rooms, "room_top": floor_1 - slab,
        "first": first, "upper": upper, "columns": columns,
    })
    # 車路の入口：右の外壁はスロープの上だけ。
    sheet.solid_rect(X(build_right - wall), Zf(-1200), wall * s, Zf(b1 + 300) - Zf(-1200), "壁", color="#ffffff")
    # 機器の階の名前。
    for i, (x, name) in enumerate(rooms):
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right - wall
        sheet.text((X(x) + X(room_end)) / 2, Zf(-400), name, _fit_label(name, X(room_end) - X(x), 14, 9), bold=True)
    sheet.text(X(build_left) + 12, Zf(floor_1) - 10, "1FL", 9, "start", layer="寸法")
    # 機器。
    cub_x, cub_w = rooms[0][0] + 1000, 2800
    sec.rect(cub_x, level_3, cub_x + cub_w, level_3 + 1200, "設備")
    for i in range(1, 3):
        sec.line(cub_x + cub_w * i / 3, level_3, cub_x + cub_w * i / 3, level_3 + 1200)
    for i in range(3):
        for dz in (250, 400, 550):
            sec.line(cub_x + cub_w * i / 3 + 200, level_3 + dz, cub_x + cub_w * (i + 1) / 3 - 200, level_3 + dz)
    sec.rect(cub_x - 150, b1, cub_x + cub_w + 150, b1 + 150, "設備")
    for leg in (cub_x + 300, cub_x + cub_w - 300):
        sheet.line(X(leg), Zf(level_3), X(leg), Zf(b1 + 150), "設備")
    sheet.text(X(cub_x + cub_w / 2), Zf(level_3 + 600), "受変電設備" if has_gen else "高圧受変電設備\n（キュービクル）", 8.5)
    tr_x, tr_end = rooms[1][0] + 400, rooms[2][0] - 400
    sheet.rect(X(tr_x), Zf(level_3 + 1300), (tr_end - tr_x) * s, 1300 * s, "設備")
    sheet.text((X(tr_x) + X(tr_end)) / 2 + 14, Zf(level_3 + 650), "？", 16, bold=True)
    sheet.text((X(tr_x) + X(tr_end)) / 2, Zf(-1300), "中は建物側から\n分からない", 8.5)
    pump_room = rooms[3][0] if has_gen else rooms[2][0]
    pump_end = rooms[4][0] if has_gen else rooms[3][0]
    sec.rect(pump_room + 500, b1, pump_room + 2300, b1 + 150, "設備")
    for px in (pump_room + 1000, pump_room + 1800):
        sheet.circle(X(px), Zf(b1 + 550), 330 * s, "設備")
        sec.rect(px - 180, b1 + 880, px + 180, b1 + 1250, "細線")
    sec.line(pump_room + 200, b1 + 550, pump_room + 670, b1 + 550)
    sec.line(pump_room + 1330, b1 + 550, pump_room + 1470, b1 + 550)
    sec.line(pump_room + 2130, b1 + 550, pump_end, b1 + 550)
    sheet.text(X(pump_room + 1400), Zf(b1 + 1700), "ポンプ", 8.5)
    panel_x = pump_end - 1400
    sheet.rect(X(panel_x), Zf(level_3 + 1100), 1000 * s, 1100 * s, "設備")
    sec.line(panel_x + 100, level_3 + 550, panel_x + 900, level_3 + 550)
    sheet.text(X(panel_x + 300), Zf(level_3 + 1750), "制御盤\n（壁掛け）", 8.5)
    tank_room = rooms[4][0] if has_gen else rooms[3][0]
    tank_end = rooms[5][0] if has_gen else rooms[4][0]
    sec.rect(tank_room + 400, b1 + 600, tank_end - 400, b1 + 2600, "設備")
    sec.rect(tank_room + 500, b1 + 700, tank_end - 500, b1 + 2500, "細線")
    for leg in (tank_room + 600, (tank_room + tank_end) / 2, tank_end - 600):
        sec.line(leg, b1, leg, b1 + 600)
    sec.line(tank_room + 400, b1 + 1800, tank_end - 400, b1 + 1800, "破線")
    sec.line(tank_room, b1 + 550, tank_room + 400, b1 + 550)
    sheet.text(X((tank_room + tank_end) / 2), Zf(b1 + 1300), "受水槽", 9)
    if has_gen:
        gen_x = rooms[2][0]
        sec.rect(gen_x + 300, b1 + 150, gen_x + 2700, b1 + 1650, "設備")
        sec.line(gen_x + 1000, b1 + 150, gen_x + 1000, b1 + 1650)
        sec.rect(gen_x + 2200, b1 + 300, gen_x + 2600, b1 + 1500, "細線")
        sec.line(gen_x + 2700, b1 + 1400, gen_x + 2700, floor_1 - slab, "破線")
        sec.rect(gen_x + 150, b1, gen_x + 2850, b1 + 150, "設備")
        sheet.text(X(gen_x + 1500), Zf(b1 + 2100), "発電機", 9)
        tank_x, tank_e = rooms[7][0], rooms[8][0]
        _water_lines(sheet, X(tank_x + 150), Zf(b1 + 2200), X(tank_e) - X(tank_x + 150), 2200 * s, 9)
        sheet.text(X(upper_right + 500), Zf(floor_1 + 2300), "公開空地", 10, "start", bold=True)
    # 引込（HH → 管 → 壁の穴 → 高圧受変電設備）。
    sheet.solid_rect(X(hh_x), Zf(150), hh_w * s, 2500 * s, "壁", color="#ffffff")
    sheet.rect(X(hh_x), Zf(150), hh_w * s, 2500 * s, "引込", 2)
    sheet.text(X(hh_x + hh_w / 2), Zf(150) - 30, "歩道ぎわの蓋（HH）", 10.5, layer="寸法", bold=True)
    sheet.line(X(hh_x + hh_w), Zf(pipe), X(build_left), Zf(pipe), "引込", 2.4)
    sheet.text(X(8000), Zf(pipe) + 22, "電線の管", 9.5, layer="寸法")
    sheet.circle(X(build_left + 150), Zf(pipe), 6, "引込")
    sheet.line(X(build_left + 300), Zf(pipe), X(cub_x), Zf(pipe), "引込", 2.4)
    sheet.text(X(build_left + 900), Zf(-1300), "ケーブルを通す\n壁の穴", 8, "start", layer="寸法", bold=True)
    # 水の入り道。
    sheet.arrow(X(3600), Zf(0) + 10, X(hh_x + 300), Zf(-600), "水の入り道", 12)
    sheet.arrow(X(hh_x + hh_w + 100), Zf(pipe - 350), X(build_left - 300), Zf(pipe - 350), "水の入り道", 12)
    _pin(sheet, X(build_left + 150), Zf(pipe), "ア")
    _pin(sheet, (X(tr_x) + X(tr_end)) / 2 - 20, Zf(level_3 + 650), "エ")
    _pin(sheet, X(pump_room + 650), Zf(level_3 + 1400), "イ")
    sheet.line(X(build_right), Zf(b1 + 300), X(slope_top), Zf(150), "道路", 2)
    sheet.line(X(slope_top), Zf(150), X(scene_end), Zf(150), "道路", 2)
    sheet.text(X(slope_top + 1100), Zf(150) - 12, "車路の入口", 11, layer="道路", bold=True)
    mx, mz = (X(build_right) + X(slope_top)) / 2, (Zf(b1 + 300) + Zf(150)) / 2
    sheet.text(mx + 16, mz + 26, "車路スロープ", 11, "start", layer="道路", bold=True)
    sheet.arrow(X(slope_top) - 8, Zf(150) - 10, X(build_right) - 10, Zf(b1 + 1100), "水の入り道", 12)
    if has_gen:
        basin = X(33000)
        sheet.rect(basin - 10, Zf(floor_1) - 13, 20, 13, "寸法", 2)
        sheet.text(basin, Zf(floor_1) - 26, "敷地の雨水ます", 10.5, layer="寸法", bold=True)
        sheet.arrow(basin, Zf(floor_1 - slab) + 2, basin, Zf(b1 + 2300), "水の入り道", 12)
        _pin(sheet, basin - 30, Zf(-1700), "ウ")
        sheet.text(basin + 12, Zf(-2200), "満水で\nあふれる", 8.5, "start", layer="寸法")
        sheet.text(mx + 16, mz + 42, "（ここからも入る）", 10, "start", layer="寸法")
    else:
        _pin(sheet, mx - 30, mz - 26, "ウ")
    # 水の位置。
    for key, z in ((2, b1 + 150), (3, level_3)):
        sheet.line(X(build_left + 300), Zf(z), X(build_right - 300), Zf(z), "水の位置")
        _level_mark(sheet, X(rooms[-1][0] + 1800), Zf(z), key)
    _level_mark(sheet, X(4600), Zf(0) - 16, 1)
    # Z 軸は建物の右（車路の入口の先）。
    breaks = {("7FL", "36FL"): "2,900×29"} if has_gen else {}
    _z_axis(sec, info["levels"], scene_end + 2400, scene_end + 1300, scene_end + 900, right=False, breaks=breaks)
    if has_gen:
        band_top, band_bottom = Zf(4300 + 34 * 2900) + 6, Zf(18800) - 6
        xs = [X(build_left) - 20, X(upper_right) + 20]
        count = 14
        upper_edge = [(xs[0] + (xs[1] - xs[0]) * i / count, band_top + (4 if i % 2 else -4)) for i in range(count + 1)]
        lower_edge = [(x, band_bottom + (4 if i % 2 else -4)) for i, (x, _) in enumerate(upper_edge)]
        sheet.solid([(xs[0], band_top - 4), (xs[1], band_top - 4), (xs[1], band_bottom + 4), (xs[0], band_bottom + 4)], "壁", color="#ffffff")
        sheet.path(upper_edge, "図枠", False, 1)
        sheet.path(lower_edge, "図枠", False, 1)
        sheet.text((xs[0] + xs[1]) / 2, (band_top + band_bottom) / 2, "8〜35階は省略（全38階建て）", 9.5)
    # 画面の重ね絵が使う基準の座標。上で描いた値をそのまま渡し、図は変えない。
    room_spans = []
    for i, (x, name) in enumerate(rooms):
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right - wall
        room_spans.append({"name": name, "role": _ROOM_ROLES[name], "x0": X(x + (150 if i else 0)), "x1": X(room_end)})
    anchors = {
        "kind": "underground",
        "floor_y": Zf(b1),
        "ceiling_y": Zf(floor_1 - slab),
        "levels": {"2": Zf(b1 + 150), "3": Zf(level_3)},
        "rooms": room_spans,
        "outside": [
            {"profile": [[X(0), Zf(0)], [X(4500), Zf(0)], [X(4500), Zf(150)], [X(build_left), Zf(150)]]},
            {"profile": [[X(slope_top), Zf(150)], [X(scene_end), Zf(150)]]},
        ],
        "outside_levels": {"1": Zf(150 + 200), "2": Zf(150 + 400), "3": Zf(150 + 700)},
        "handhole": [X(hh_x), Zf(150), hh_w * s, 2500 * s],
        "equipment": {
            "hv": {"rect": [X(cub_x), Zf(level_3 + 1200), cub_w * s, 1200 * s]},
            "tr": {"rect": [X(tr_x), Zf(level_3 + 1300), (tr_end - tr_x) * s, 1300 * s]},
            "panel": {"rect": [X(panel_x), Zf(level_3 + 1100), 1000 * s, 1100 * s]},
            "pump": {"circle": [X(pump_room + 1000), Zf(b1 + 550), 330 * s]},
        },
        "routes": [
            {"key": "hole", "guard": "hv", "points": [[X(hh_x + hh_w / 2), Zf(150)], [X(hh_x + hh_w / 2), Zf(pipe)], [X(build_left + 150), Zf(pipe)], [X(build_left + 900), Zf(pipe)], [X(build_left + 900), Zf(b1 + 700)]], "block": [X(build_left + 150), Zf(pipe)]},
            {"key": "slope", "points": [[X(slope_top + 1100), Zf(150)], [X(slope_top), Zf(150)], [X(build_right), Zf(b1 + 300)], [X(rooms[-1][0]), Zf(b1 + 300)]]},
        ],
        "stage_names": {str(k): v for k, v in _section_short(sample).items()},
        # 画面のビューアーで寄せて見せる、図のある範囲（用紙の px。左・上・右・下）。
        "focus": [round(X(0) - 30, 1), round(Zf(info["tower_top"] + 1800) - 30, 1), round(X(scene_end + 3000) + 10, 1), round(Zf(bottom) + 20, 1)],
    }
    if has_gen:
        gen_x = rooms[2][0]
        anchors["equipment"]["gen"] = {"rect": [X(gen_x + 300), Zf(b1 + 1650), 2400 * s, 1500 * s]}
        anchors["routes"].append({"key": "basin", "points": [[X(33000), Zf(floor_1)], [X(33000), Zf(b1 + 2300)]]})
    return anchors


def section_hillside(sheet, sample, view, left, base):
    """機器が1階にある建物の断面。丘から低い側へ水が下りてくる。"""
    s = view.scale
    sec = Sec(sheet, left, base, s)
    X, Zf = sec.X, sec.Z
    build_left, build_right, floor_1, wall = 7000, 28000, 300, 300
    top_2 = floor_1 + 3300
    rooms = [(7300, "共用分電盤室"), (11300, "借室"), (14800, "給水ポンプ室"), (18800, "EV"), (21000, "階段"), (23600, "エントランス")]
    ev, stair = (18800, 21000), (21000, 23600)
    upper = [("corridor", 7300, 8800, None), ("unit", 8800, 18800, [11300, 14800]), ("unit", 23600, 26500, [25000]), ("balcony", 26500, 28000, "right")]
    columns = [7300, 11300, 14800, 18800, 23600, 27700]
    scene_end = 32500
    hill = [(build_right, 1000), (31500, 1800), (scene_end, 2800)]
    bottom = floor_1 - 2600
    # 地面：左は低い道路、右は丘。
    sheet.line(X(0), Zf(0), X(4500), Zf(0), "道路", 2)
    sheet.line(X(4500), Zf(0), X(4500), Zf(100), "道路", 2)
    sheet.line(X(4500), Zf(100), X(build_left), Zf(200), "道路", 2)
    for (xa, za), (xb, zb) in zip(hill, hill[1:]):
        sheet.line(X(xa), Zf(za), X(xb), Zf(zb), "道路", 2)
    sheet.text(X(2950), Zf(0) - 12, "前の道路（低い）", 11, layer="道路", bold=True)
    sheet.text(X(5700), Zf(100) + 14, "敷地内通路", 10, layer="道路", bold=True)
    sheet.text(X(31300), Zf(2800) + 36, "丘の側（高い）", 11, layer="道路", bold=True)
    sheet.text(X(0) + 4, Zf(0) + 12, "GL±0", 8.5, "start", layer="寸法")
    sheet.hatch_poly([(X(700), Zf(0) + 2), (X(4500), Zf(0) + 2), (X(4500), Zf(100) + 2), (X(build_left), Zf(200) + 2), (X(build_left), Zf(bottom)), (X(700), Zf(bottom))], gap=18)
    sheet.hatch_poly([(X(build_left), Zf(floor_1 - 1950)), (X(build_right), Zf(floor_1 - 1950)), (X(build_right), Zf(bottom)), (X(build_left), Zf(bottom))], gap=18)
    sheet.hatch_poly([(X(x), Zf(z) + 2) for x, z in hill] + [(X(scene_end), Zf(bottom)), (X(build_right), Zf(bottom))], gap=18)
    info = _building(sec, {
        "build_left": build_left, "build_right": build_right, "b1": None, "floor_1": floor_1, "floor_2": top_2, "floor_h": 2900,
        "floors": sample["floors"], "ev": ev, "stair": stair, "rooms": rooms, "room_top": top_2 - 300, "upper": upper, "columns": columns,
    })
    for i, (x, name) in enumerate(rooms):
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right - wall
        sheet.text((X(x) + X(room_end)) / 2, Zf(top_2 - 300) + 13, name, _fit_label(name, X(room_end) - X(x), 16, 9), bold=True)
    sheet.text(X(build_left) + 12, Zf(floor_1) - 10, "1FL", 9, "start", layer="寸法")
    # 機器：架台の上の主開閉器盤と制御盤、増圧ポンプ、借室の箱。
    hv_x, hv_w = 8300, 2600
    panel_x, panel_w = 16500, 1900
    for x, w, name in ((hv_x, hv_w, "主開閉器盤"), (panel_x, panel_w, "制御盤")):
        sec.rect(x - 100, floor_1, x + w + 100, floor_1 + 120, "設備")
        for leg in (x + 150, x + w - 150):
            sec.line(leg, floor_1 + 120, leg, floor_1 + 500, "設備")
        sheet.rect(X(x), Zf(floor_1 + 1900), w * s, 1400 * s, "設備")
        sec.line(x + 150, floor_1 + 1200, x + w - 150, floor_1 + 1200)
        sheet.text(X(x + w / 2), Zf(floor_1 + 1200), f"{name}\n（架台の上）", 8.5)
    for px in (15200, 15900):
        sheet.circle(X(px), Zf(floor_1 + 420), 280 * s, "設備")
        sec.rect(px - 160, floor_1 + 700, px + 160, floor_1 + 1050, "細線")
    sec.rect(14850, floor_1, 16250, floor_1 + 120, "設備")
    sec.line(14800, floor_1 + 420, 14920, floor_1 + 420)
    sec.line(16180, floor_1 + 420, 16450, floor_1 + 420)
    sheet.text(X(15550), Zf(floor_1 + 1500), "ポンプ", 8.5)
    tr_x, tr_w = 11800, 2600
    sheet.rect(X(tr_x), Zf(floor_1 + 2000), tr_w * s, 1500 * s, "設備")
    sheet.text(X(tr_x + tr_w / 2) + 14, Zf(floor_1 + 1500), "？", 16, bold=True)
    sheet.text(X(tr_x + tr_w / 2), Zf(floor_1 + 900), "中は建物側から\n分からない", 8.5)
    # 坂下側の出入口と足元の換気口。
    sheet.solid_rect(X(build_left), Zf(floor_1 + 2100), wall * s, Zf(floor_1) - Zf(floor_1 + 2100), "壁", color="#ffffff")
    sheet.line(X(build_left + 150), Zf(floor_1 + 2100), X(build_left + 150), Zf(floor_1 + 200), "建具", 2.4)
    sheet.rect(X(build_left) - 3, Zf(floor_1 + 80) - 8, 9, 8, "設備")
    sheet.text(X(build_left) - 8, Zf(floor_1 + 1500), "坂下側出入口\n足元換気口", 10, "end", layer="寸法", bold=True)
    attach = floor_1 + 2600
    sheet.line(X(800), Zf(0), X(800), Zf(6200), "設備", 2)
    sheet.line(X(800), Zf(5800), X(build_left), Zf(attach), "引込", 2.4)
    sheet.solid_rect(X(build_left) - 5, Zf(attach) - 5, 10, 10, "図枠")
    sheet.text(X(800) + 8, Zf(6100), "電柱（空中からの引込み）", 10.5, "start", layer="寸法", bold=True)
    sheet.text(X(2000), Zf(3300), "外壁の取付点（例）。\nその先の経路は\n図から分からない", 9, "start", layer="寸法")
    sheet.arrow(X(32200), Zf(2700) - 14, X(29500), Zf(1300) - 14, "水の入り道", 12)
    sheet.arrow(X(5800), Zf(650), X(build_left) + 2, Zf(520), "水の入り道", 12)
    sheet.text(X(28600), Zf(5300), "雨水が坂を下り、\n建物の脇を回って\n低い側へ", 10.5, "start", layer="寸法", bold=True)
    _pin(sheet, X(4600), Zf(1000), "ウ")
    _pin(sheet, X(7700), Zf(floor_1 + 1500), "ア")
    _pin(sheet, X(15550), Zf(floor_1 + 2300), "イ")
    _pin(sheet, X(tr_x + tr_w / 2) - 20, Zf(floor_1 + 1500), "エ")
    for key, z in ((2, floor_1 + 120), (3, floor_1 + 500)):
        sheet.line(X(build_left + 300), Zf(z), X(build_right - 300), Zf(z), "水の位置")
        _level_mark(sheet, X(24400 if key == 2 else 26400), Zf(z), key)
    _level_mark(sheet, X(1600), Zf(0) - 36, 1)
    # Z 軸は建物の左（道路の上の空）。
    _z_axis(sec, info["levels"], -1500, -400, 1200, right=True)
    room_spans = []
    for i, (x, name) in enumerate(rooms):
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right - wall
        room_spans.append({"name": name, "role": _ROOM_ROLES[name], "x0": X(x + (150 if i else 0)), "x1": X(room_end)})
    return {
        "kind": "hillside",
        "floor_y": Zf(floor_1),
        "ceiling_y": Zf(top_2 - 300),
        "levels": {"2": Zf(floor_1 + 120), "3": Zf(floor_1 + 500)},
        "rooms": room_spans,
        "outside": [
            {"profile": [[X(0), Zf(0)], [X(4500), Zf(0)], [X(4500), Zf(100)], [X(build_left), Zf(200)]]},
        ],
        "outside_levels": {"1": Zf(floor_1 + 50), "2": Zf(floor_1 + 120 + 150), "3": Zf(floor_1 + 500 + 150)},
        "equipment": {
            "hv": {"rect": [X(hv_x), Zf(floor_1 + 1900), hv_w * s, 1400 * s]},
            "panel": {"rect": [X(panel_x), Zf(floor_1 + 1900), panel_w * s, 1400 * s]},
            "tr": {"rect": [X(tr_x), Zf(floor_1 + 2000), tr_w * s, 1500 * s]},
        },
        "routes": [
            {"key": "hill", "points": [[X(32200), Zf(2700) - 14], [X(29500), Zf(1300) - 14]]},
            {"key": "door", "points": [[X(5800), Zf(650)], [X(build_left) + 2, Zf(520)]]},
        ],
        "stage_names": {str(k): v for k, v in _section_short(sample).items()},
        # 画面のビューアーで寄せて見せる、図のある範囲（用紙の px。左・上・右・下）。
        "focus": [round(X(-2400) - 10, 1), round(Zf(info["tower_top"] + 1800) - 30, 1), round(X(scene_end) + 20, 1), round(Zf(bottom) + 20, 1)],
    }


def section_sheet(sample):
    number = {"a": "A-201", "b": "A-211", "c": "A-221"}[sample["id"]]
    if sample["id"] == "b":
        scale = 0.027
        sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, scale)
        frame_and_title(sheet, sample, "竣工図 模式断面図（水の入り道）", number, "S=1/100（用紙に合わせて縮小）")
        left, base = 110, 150 + 20800 * scale
        view = View(left, base, scale)
        sheet.use(view)
        sheet.anchors = section_hillside(sheet, sample, view, left, base)
        title_y = 905
    else:
        scale = 0.019 if sample["id"] == "a" else 0.0185
        sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, scale)
        frame_and_title(sheet, sample, "竣工図 模式断面図（水の入り道）", number, "S=1/100（用紙に合わせて縮小）")
        top_mm = 36300 + 2600 if sample["id"] == "a" else 34100 + 2600
        left, base = 50, 62 + top_mm * scale
        view = View(left, base, scale)
        sheet.use(view)
        sheet.anchors = section_underground(sheet, sample, view, left, base)
        title_y = 952
    sheet.use(None)
    title_of(sheet, 480, title_y, "模式断面図（水の入り道）", "機器の階は順に並べた展開")
    _section_key(sheet, sample, 1000, 90)
    return sheet


def section_anchors(sample) -> dict:
    """断面図の基準の座標（用紙の px。PNG と同じ 1400×990）を、図を描く関数の値から作る。"""
    anchors = section_sheet(sample).anchors

    def rounded(value):
        if isinstance(value, float):
            return round(value, 2)
        if isinstance(value, dict):
            return {key: rounded(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [rounded(item) for item in value]
        return value

    return {"width": PLAN_WIDTH, "height": PLAN_HEIGHT, "sample": sample["id"], **rounded(anchors)}


def section_anchors_json(sample) -> str:
    return json.dumps(section_anchors(sample), ensure_ascii=False, indent=1) + "\n"


def write_section_anchors() -> None:
    """python3 -m scripts.draw_plans --anchors で、図を作り直さずに web/samples/section_*.json だけを書く。"""
    for sample in SAMPLES.values():
        with open(os.path.join(OUT_DIR, f"section_{sample['id']}.json"), "w", encoding="utf-8") as handle:
            handle.write(section_anchors_json(sample))


# 電気と給水の系統図

def _box(sheet, x, y, w, label, floor=None, pin=None, unknown=False, water=False):
    h = 58
    # 平面図と同じ色で、水の機器は青、電気の機器は橙に薄く塗る（道路の配電線など建物の外は塗らない）。
    if not unknown and floor not in ("道路", "歩道の下", "道路の下"):
        sheet.solid_rect(x, y, w, h, "部屋の色", color=ROOM_COLORS["water" if water else "power"])
    if unknown:
        sheet.rect(x, y, w, h, "引込", 1.6)
    else:
        sheet.rect(x, y, w, h, "図枠", 1.6)
    sheet.text(x + w / 2, y + h / 2 - (7 if floor else 0), label, _fit_label(label, w, 17, 12), bold=True, color="#0277bd" if water else None)
    if floor:
        sheet.text(x + w / 2, y + h - 12, floor, 10.5, color="#0277bd" if "地下" in floor else "#5a5a60", bold="地下" in floor)
    if pin:
        _pin(sheet, x + w - 16, y - 16, pin)
    return (x, y, w, h)


def _flow(sheet, a, b, layer="図枠", label=None, width=1.8):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if abs((ay + ah / 2) - (by + bh / 2)) < 2:
        x1, y1, x2, y2 = ax + aw, ay + ah / 2, bx, by + bh / 2
    elif bx >= ax + aw:
        x1, y1, x2, y2 = ax + aw, ay + ah / 2, bx, by + bh / 2
        mid = (x1 + x2) / 2
        sheet.line(x1, y1, mid, y1, layer, width)
        sheet.line(mid, y1, mid, y2, layer, width)
        sheet.arrow(mid, y2, x2, y2, layer, 9)
        if label:
            sheet.text(mid + 6, (y1 + y2) / 2, label, 10.5, "start", layer="寸法")
        return
    else:
        x1, y1, x2, y2 = ax + aw / 2, ay + ah, bx + bw / 2, by
    sheet.line(x1, y1, x2, y2, layer, width)
    sheet.arrow((x1 + x2) / 2 if x1 == x2 else x2 - 1, y2 - 1 if x1 == x2 else y2, x2, y2, layer, 9)
    if label:
        sheet.text((x1 + x2) / 2, (y1 + y2) / 2 - 10, label, 10.5, layer="寸法")


def system_sheet(sample):
    number = {"a": "E-101", "b": "E-111", "c": "E-121"}[sample["id"]]
    sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, 0.02)
    frame_and_title(sheet, sample, "竣工図 電気・給水の系統図（模式）", number, "なし（系統図）")
    sid = sample["id"]
    basement = sid != "b"
    floor = "地下1階" if basement else "1階"
    sheet.text(70, 92, "電気の系統", 16, "start", bold=True)
    sheet.line(70, 104, 1330, 104, "図枠", 1)
    # 電気
    line = _box(sheet, 70, 150, 170, "東京電力の配電線", "道路")
    if sample["underground_feed"]:
        hh = _box(sheet, 300, 150, 170, "歩道ぎわの蓋（HH）", "歩道の下")
        _flow(sheet, line, hh)
        hole = _box(sheet, 530, 150, 190, "ケーブルを通す壁の穴", floor, pin="ア")
        _flow(sheet, hh, hole, "引込", "地中の管")
        sheet.text(385, 226, "電力会社と建物の境目は書類で確かめる", 10.5, layer="寸法")
        entry = hole
    else:
        pole = _box(sheet, 300, 150, 170, "電柱", "敷地の外")
        _flow(sheet, line, pole)
        entry = _box(sheet, 530, 150, 190, "外壁の取付点", "1階の外壁")
        _flow(sheet, pole, entry, "引込", "空中の線")
    tr = _box(sheet, 530, 290, 190, "借室（東京電力の変圧器）", floor, pin="エ")
    sheet.text(625, 362, "借室の位置と数は図から分からない" if sid == "c" else "中の機器は建物側から分からない", 10.5, layer="寸法")
    homes = _box(sheet, 790, 290, 170, "各戸の分電盤", "各階")
    sheet.line(155, 208, 155, 319, "引込", 1.6)
    sheet.arrow(155, 319, 530, 319, "引込", 9)
    sheet.text(170, 336, "借室までの経路は建物側から分からない", 10.5, "start", layer="寸法")
    sheet.text(170, 352, "上の引込みと同じか別かも図から分からない", 10.5, "start", layer="寸法")
    _flow(sheet, tr, homes)
    if sample["has_chief_engineer"]:
        hv = _box(sheet, 790, 150, 170, "受変電設備" if sid == "c" else "高圧受変電設備", floor)
        _flow(sheet, entry, hv)
        panel = _box(sheet, 1030, 150, 170, "共用の分電盤", floor)
        _flow(sheet, hv, panel)
        loads = [(1220, 290, 110, "エレベーター", floor), (1220, 360, 110, "共用照明", "各階")]
        pump_panel = _box(sheet, 1030, 430, 170, "給水ポンプの制御盤", floor, pin="イ")
        px, py, pw, ph = panel
        sheet.line(px + pw / 2, py + ph, px + pw / 2, 420, "図枠", 1.8)
        sheet.arrow(px + pw / 2, 420, px + pw / 2, 430, "図枠", 9)
        bus = px + pw + 10
        sheet.line(px + pw, py + ph / 2, bus, py + ph / 2, "図枠", 1.8)
    else:
        sheet.text(625, 230, "受電設備なし。借室から先は低圧（例）", 10.5, layer="寸法")
        panel = _box(sheet, 790, 420, 170, "共用部の\n主開閉器盤", floor, pin="ア")
        sheet.line(625, 378, 625, 449, "引込", 1.6)
        sheet.arrow(625, 449, 790, 449, "引込", 9)
        sheet.line(720, 179, 745, 179, "引込", 1.6)
        sheet.line(745, 179, 745, 430, "引込", 1.6)
        sheet.arrow(745, 430, 790, 430, "引込", 8)
        sheet.text(735, 398, "共用部をどこから受けるかは書類で確かめる", 10.5, "end", layer="寸法")
        loads = [(1030, 300, 170, "エレベーター", floor), (1030, 370, 170, "共用照明", "各階")]
        pump_panel = _box(sheet, 1030, 440, 170, "給水ポンプの制御盤", floor, pin="イ")
        px, py, pw, ph = panel
        bus = 1000
        sheet.line(px + pw, py + ph / 2, bus, py + ph / 2, "図枠", 1.8)
        sheet.line(bus, py + ph / 2, bus, 469, "図枠", 1.8)
        sheet.arrow(bus, 469, 1030, 469, "図枠", 8)
    for lx, ly, lw, name, where in loads:
        target = _box(sheet, lx, ly, lw, name, where)
        tx, ty, tw, th = target
        sheet.line(bus, py + ph / 2, bus, ty + th / 2, "図枠", 1.8)
        sheet.arrow(bus, ty + th / 2, tx, ty + th / 2, "図枠", 8)
    if sid == "c":
        gen = _box(sheet, 530, 430, 190, "非常用発電機", floor)
        backup = _box(sheet, 790, 430, 170, "非常用の設備の一部", "建物による", unknown=True)
        sheet.line(720, 459, 760, 459, "引込", 1.6)
        sheet.arrow(760, 459, 790, 459, "引込", 8)
        sheet.text(625, 506, "どの設備へ送るかは、管理会社と主任技術者に書類で確かめる", 10.5, layer="寸法")
    # 給水
    top = 540
    sheet.text(70, top + 2, "給水の系統", 16, "start", bold=True, color="#0277bd")
    sheet.line(70, top + 14, 1330, top + 14, "水の入り道", 1)
    main = _box(sheet, 70, top + 60, 170, "水道の本管", "道路の下", water=True)
    if basement:
        tank = _box(sheet, 300, top + 60, 170, "受水槽", floor, water=True)
        _flow(sheet, main, tank, "水の入り道")
        pump = _box(sheet, 530, top + 60, 190, "給水ポンプ", floor, water=True)
        _flow(sheet, tank, pump, "水の入り道")
    else:
        pump = _box(sheet, 300, top + 60, 190, "増圧の給水ポンプ", floor, water=True)
        _flow(sheet, main, pump, "水の入り道")
    taps = _box(sheet, 790, top + 60, 170, "各戸の蛇口", "各階", water=True)
    _flow(sheet, pump, taps, "水の入り道")
    drain = _box(sheet, 790, top + 180, 170, "トイレ・排水", "各階", water=True)
    sewer = _box(sheet, 300, top + 180, 170, "下水道", "道路の下", water=True)
    sheet.arrow(790, top + 209, 470, top + 209, "水の入り道", 9)
    lift = _box(sheet, 530, top + 280, 190, "汲み上げポンプ", "有無は未確認", unknown=True)
    sheet.text(625, top + 360, "地下の排水を汲み上げる建物の場合（停電で止まる）", 10.5, layer="寸法")
    # 電気が止まると水も止まる
    ppx, ppy, ppw, pph = pump_panel
    pux, puy, puw, puh = pump
    sheet.line(ppx + ppw / 2, ppy + pph, ppx + ppw / 2, puy - 20, "図枠", 2.4)
    sheet.line(ppx + ppw / 2, puy - 20, pux + puw / 2, puy - 20, "図枠", 2.4)
    sheet.arrow(pux + puw / 2, puy - 20, pux + puw / 2, puy, "図枠", 10)
    stop = "電気が止まると給水ポンプも止まる" + ("（発電機から送るかは書類で確認）" if sid == "c" else "")
    sheet.text(ppx + ppw / 2 - 8, puy - 30, stop, 11.5, "end", color="#b91c1c", bold=True)
    # 凡例
    lx, ly = 1010, 700
    sheet.text(lx, ly, "凡例", 12, "start", bold=True)
    sheet.line(lx, ly + 24, lx + 40, ly + 24, "図枠", 1.8)
    sheet.text(lx + 50, ly + 24, "電気の流れ", 11, "start")
    sheet.line(lx, ly + 46, lx + 40, ly + 46, "水の入り道", 1.8)
    sheet.text(lx + 50, ly + 46, "水の流れ", 11, "start")
    sheet.line(lx, ly + 68, lx + 40, ly + 68, "引込", 1.8)
    sheet.text(lx + 50, ly + 68, "引込み・つながり・未確認", 11, "start")
    sheet.text(lx, ly + 94, "赤い文字は停電で止まるつながり", 11, "start", color="#b91c1c", bold=True)
    sheet.text(lx, ly + 116, "青い階名は浸水しうる地下の階", 11, "start", color="#0277bd", bold=True)
    sheet.text(lx, ly + 138, "機器の構成は一例です", 11, "start")
    return sheet


def svg(sheet):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {PLAN_WIDTH} {PLAN_HEIGHT}" width="{PLAN_WIDTH}" height="{PLAN_HEIGHT}">'
        f'<rect width="{PLAN_WIDTH}" height="{PLAN_HEIGHT}" fill="#ffffff"/>' + sheet.svg_body() + "</svg>"
    )


def print_pdf(chrome, url, pdf_path):
    """Chrome は PDF を書いたあと終わらないことがあるので、書き終わりを見て止める。"""
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    process = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={OUT_DIR}/.chrome", f"--print-to-pdf={pdf_path}", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    last_size, deadline = -1, time.time() + 120
    while time.time() < deadline:
        size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
        if size and size == last_size:
            break
        last_size = size
        time.sleep(2)
    process.terminate()
    process.wait(timeout=20)
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"PDF を作れませんでした: {pdf_path}")


def export(chrome, name):
    svg_path = os.path.join(OUT_DIR, f"{name}.svg")
    page = os.path.join(OUT_DIR, f"{name}.print.html")
    with open(svg_path, encoding="utf-8") as handle:
        body = handle.read()
    with open(page, "w", encoding="utf-8") as handle:
        handle.write(
            '<!doctype html><meta charset="utf-8"><style>@page{size:'
            f"{PLAN_WIDTH}px {PLAN_HEIGHT}px;margin:0}}html,body{{margin:0}}svg{{display:block}}</style>{body}"
        )
    url = "file://" + page
    print_pdf(chrome, url, f"{OUT_DIR}/{name}.pdf")
    subprocess.run(
        ["sips", "-s", "format", "png", "-Z", str(PLAN_WIDTH), f"{OUT_DIR}/{name}.pdf", "--out", f"{OUT_DIR}/{name}.png"],
        check=True,
        capture_output=True,
    )
    os.remove(page)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    names = []
    for sample in SAMPLES.values():
        sid = sample["id"]
        for name, sheet in ((f"plan_{sid}", plan_sheet(sample)), (f"section_{sid}", section_sheet(sample)), (f"system_{sid}", system_sheet(sample))):
            with open(os.path.join(OUT_DIR, f"{name}.svg"), "w", encoding="utf-8") as handle:
                handle.write(svg(sheet))
            with open(os.path.join(OUT_DIR, f"{name}.dxf"), "wb") as handle:
                handle.write(dxf([sheet]))
            names.append(name)
        with open(os.path.join(OUT_DIR, f"report_{sid}.txt"), "w", encoding="utf-8") as handle:
            handle.write(REPORTS[sid])
    write_section_anchors()
    if not os.path.exists(CHROME):
        print("Chrome がないので SVG と DXF だけ作りました。", file=sys.stderr)
        return
    for name in names:
        export(CHROME, name)
    shutil.rmtree(os.path.join(OUT_DIR, ".chrome"), ignore_errors=True)


if __name__ == "__main__":
    if "--anchors" in sys.argv[1:]:
        write_section_anchors()
    else:
        main()
