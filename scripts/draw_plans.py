"""架空の見本の竣工図を CAD の線で描く。python3 -m scripts.draw_plans

見本ごとに、平面図の用紙（ピンを立てる図）と、基準階と水の入り道の断面の用紙を作り、
SVG と DXF に書き出す。PDF は手元の Chrome、PNG は macOS の sips で作る。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

from app.building import WATER_LEVELS
from app.samples import PLAN_HEIGHT, PLAN_WIDTH, REPORTS, SAMPLES
from scripts.cad import FONT, Sheet, View, dxf

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "samples")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OPEN_AIR = {"soil", "garden"}
OUTER_WALL = 300
INNER_WALL = 150
COLUMN = 800


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
SECTION_KIND = {"電気室": "power", "受変電室": "power", "共用分電盤室": "power", "借室": "power", "発電機室": "power", "給水ポンプ室": "water", "雨水貯留槽": "water", "車路": "car"}


def _water_lines(sheet, x, y, w, h, gap=9.0):
    """水をためる所の印。土の斜線と分ける。"""
    yy = y + gap
    while yy < y + h:
        sheet.line(x + 2, yy, x + w - 2, yy, "寸法")
        yy += gap


class PlanView:
    """平面図を一つ描く。座標は図の左上を原点にした mm。"""

    def __init__(self, sheet, spec, left, top, scale, size, grid):
        self.sheet, self.spec, self.size, self.grid = sheet, spec, size, grid
        self.view = View(left, top, scale)
        self.rooms = spec["rooms"]
        # 図が大きいほど小さな文字も大きくする。0.02 px/mm を基準にする。
        self.zoom = max(1.0, min(1.6, scale / 0.02))

    def px(self, x, y):
        return self.view.x(x), self.view.y(y)

    def line(self, x1, y1, x2, y2, layer="設備"):
        self.sheet.line(*self.px(x1, y1), *self.px(x2, y2), layer)

    def box(self, x0, y0, x1, y1, layer="設備"):
        px, py = self.px(x0, y0)
        self.sheet.rect(px, py, (x1 - x0) * self.view.scale, (y1 - y0) * self.view.scale, layer)

    def label(self, x, y, value, size=8, layer="文字", bold=False):
        self.sheet.text(*self.px(x, y), value, size * self.zoom, layer=layer, bold=bold)

    # 通り芯と寸法

    def draw_grid(self):
        """通り芯と寸法線は DXF（CAD の図面）にだけ残し、画面と PDF の絵には描かない（部屋の色と名前を読みやすくするため。2026-11-04）。"""
        self.sheet.cad_only = True
        try:
            self._grid_lines()
        finally:
            self.sheet.cad_only = False

    def _grid_lines(self):
        s = self.sheet
        xs, ys = self.grid["x"], self.grid["y"]
        top, bottom = self.view.y(0), self.view.y(self.size[1])
        left, right = self.view.x(0), self.view.x(self.size[0])
        for i, value in enumerate(xs):
            x = self.view.x(value)
            s.line(x, top - 48, x, bottom + 12, "通り芯")
            s.circle(x, top - 60, 11, "図枠")
            s.text(x, top - 60, f"X{i + 1}", 9)
        for i, value in enumerate(ys):
            y = self.view.y(value)
            s.line(left - 48, y, right + 12, y, "通り芯")
            s.circle(left - 60, y, 11, "図枠")
            s.text(left - 60, y, f"Y{i + 1}", 9)
        y = top - 26
        s.line(left, y, right, y, "寸法")
        for i, value in enumerate(xs):
            x = self.view.x(value)
            s.line(x - 3, y + 3, x + 3, y - 3, "寸法")
            if i < len(xs) - 1:
                s.text((x + self.view.x(xs[i + 1])) / 2, y - 7, f"{xs[i + 1] - value:,}", 8.5, layer="寸法")
        x = left - 26
        s.line(x, top, x, bottom, "寸法")
        for i, value in enumerate(ys):
            yy = self.view.y(value)
            s.line(x - 3, yy + 3, x + 3, yy - 3, "寸法")
            if i < len(ys) - 1:
                s.text(x - 7, (yy + self.view.y(ys[i + 1])) / 2, f"{ys[i + 1] - value:,}", 8.5, layer="寸法", rotate=-90)

    # 壁と建具

    def _openings(self):
        found = []
        for room in self.rooms:
            x0, y0, x1, y1 = room["mm"]
            specs = list(room.get("openings", []))
            if room.get("unit_door"):
                specs.append(room["unit_door"])
            for spec in specs:
                side = spec["side"]
                if side in ("top", "bottom"):
                    found.append({**spec, "axis": "h", "pos": y0 if side == "top" else y1, "room": room})
                else:
                    found.append({**spec, "axis": "v", "pos": x0 if side == "left" else x1, "room": room})
        return found

    def draw_walls(self):
        edges = {}
        for room in self.rooms:
            if room["key"] in OPEN_AIR or room.get("outdoor"):
                continue
            x0, y0, x1, y1 = room["mm"]
            edges.setdefault(("h", y0), []).append([x0, x1])
            edges.setdefault(("h", y1), []).append([x0, x1])
            edges.setdefault(("v", x0), []).append([y0, y1])
            edges.setdefault(("v", x1), []).append([y0, y1])
        openings = self._openings()
        for (axis, pos), spans in edges.items():
            merged = []
            for span in sorted(spans):
                if merged and span[0] <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], span[1])
                else:
                    merged.append(list(span))
            cuts = sorted((o["at"] - o["w"] / 2, o["at"] + o["w"] / 2) for o in openings if o["axis"] == axis and o["pos"] == pos)
            limit = self.size[1] if axis == "h" else self.size[0]
            thickness = OUTER_WALL if pos in (0, limit) else INNER_WALL
            for start, end in merged:
                cursor = start
                for cut_start, cut_end in cuts:
                    if cut_end <= cursor or cut_start >= end:
                        continue
                    self._wall(axis, pos, cursor, cut_start, thickness)
                    cursor = cut_end
                self._wall(axis, pos, cursor, end, thickness)
        for opening in openings:
            self._opening(opening)

    def _wall(self, axis, pos, start, end, thickness):
        if end <= start:
            return
        half = thickness / 2
        s = self.view.scale
        if axis == "h":
            self.sheet.solid_rect(self.view.x(start), self.view.y(pos - half), (end - start) * s, thickness * s, "壁")
        else:
            self.sheet.solid_rect(self.view.x(pos - half), self.view.y(start), thickness * s, (end - start) * s, "壁")

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
        elif kind == "sliding":
            normal = 2.0 * inward
            if o["axis"] == "h":
                s.line(p1[0], p1[1] + normal, (p1[0] + p2[0]) / 2 + 3, p1[1] + normal, "建具")
                s.line((p1[0] + p2[0]) / 2 - 3, p1[1] - normal, p2[0], p1[1] - normal, "建具")
            else:
                s.line(p1[0] + normal, p1[1], p1[0] + normal, (p1[1] + p2[1]) / 2 + 3, "建具")
                s.line(p1[0] - normal, (p1[1] + p2[1]) / 2 - 3, p1[0] - normal, p2[1], "建具")
        elif kind == "window":
            for normal in (-2.0, 0.0, 2.0):
                if o["axis"] == "h":
                    s.line(p1[0], p1[1] + normal, p2[0], p2[1] + normal, "建具")
                else:
                    s.line(p1[0] + normal, p1[1], p2[0] + normal, p2[1], "建具")
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

    # 部屋の中身

    def _symbol(self, room):
        x0, y0, x1, y1 = room["mm"]
        kind = room.get("symbol")
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = x1 - x0, y1 - y0
        if kind == "cubicle":
            self.box(x0 + w * 0.15, y1 - h * 0.34, x1 - w * 0.15, y1 - h * 0.1)
            self.label(cx, y1 - h * 0.22, "高圧受変電設備（キュービクル）", 8)
        elif kind == "transformer":
            self.box(x0 + w * 0.22, y1 - h * 0.34, x1 - w * 0.22, y1 - h * 0.1)
            self.label(cx, y1 - h * 0.22, "？", 12, bold=True)
            self.label(cx, y1 - h * 0.42, "中は建物側から分からない", 7)
        elif kind in ("pump", "pump_stand"):
            r = min(w, h) * 0.07
            for dx in (-r * 1.7, r * 1.7):
                self.sheet.circle(*self.px(cx + dx, y1 - h * 0.22), r * self.view.scale, "設備")
            self.box(x0 + w * 0.08, y1 - h * 0.34, x0 + w * 0.22, y1 - h * 0.1)
            self.label(cx, y1 - h * 0.42, "給水ポンプと制御盤（壁掛け）" if kind == "pump" else "給水ポンプと制御盤（架台の上）", 7)
            if kind == "pump_stand":
                self.box(x0 + w * 0.05, y1 - h * 0.38, x1 - w * 0.05, y1 - h * 0.11, "シャッター")
        elif kind == "panel_stand":
            self.box(x0 + w * 0.15, y1 - h * 0.34, x1 - w * 0.15, y1 - h * 0.14)
            self.box(x0 + w * 0.1, y1 - h * 0.38, x1 - w * 0.1, y1 - h * 0.11, "シャッター")
            self.label(cx, y1 - h * 0.24, "主開閉器盤（架台の上）", 7)
        elif kind == "water_tank":
            self.box(x0 + w * 0.2, y1 - h * 0.42, x1 - w * 0.2, y1 - h * 0.12)
            self.label(cx, y1 - h * 0.27, "受水槽", 8)
        elif kind == "generator":
            self.box(x0 + w * 0.15, y1 - h * 0.32, x1 - w * 0.15, y1 - h * 0.08)
            self.label(cx, y1 - h * 0.2, "発電機", 8)
        elif kind in ("pit", "parking"):
            bays = max(3, int(w / 2400))
            for i in range(bays):
                bx = x0 + 300 + i * (w - 600) / bays
                self.box(bx + 150, y0 + h * 0.5, bx + (w - 600) / bays - 150, y1 - 300, "シャッター" if kind == "pit" else "設備")
        elif kind == "parking_flat":
            bays = int(w / 2500)
            for i in range(1, bays):
                bx = x0 + i * w / bays
                self.line(bx, y0 + h * 0.15, bx, y1 - 150)
        elif kind == "bike":
            for i in range(1, int(w / 900)):
                bx = x0 + i * 900
                self.line(bx, y1 - h * 0.34, bx, y1 - 150)
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
        elif kind == "stair":
            mid = cx
            landing = y0 + h * 0.2
            self.line(mid, landing, mid, y1 - 200, "階段EV")
            steps = int((y1 - landing) / 300)
            for i in range(steps):
                ty = landing + i * (y1 - 200 - landing) / steps
                self.line(x0 + 150, ty, x1 - 150, ty, "階段EV")
            self.sheet.arrow(*self.px((x0 + mid) / 2, y1 - 500), *self.px((x0 + mid) / 2, landing + 200), "階段EV", 6)
            self.label((mid + x1) / 2, y1 - 500, "DN", 6.5)
            self.label((x0 + mid) / 2, y1 - 300, "UP", 6.5)

    def _unit(self, room):
        x0, y0, x1, y1 = room["mm"]
        scale = self.view.scale
        if "unit_door" not in room:
            spec = {"side": "top", "at": x0 + (x1 - x0) * 0.7, "w": 900, "kind": "door", "axis": "h", "pos": y0, "room": room}
            self._gap_wall(spec)
            self._leaf("h", self.px(spec["at"] - 450, y0), 900 * scale, 1)
            self.box(x0 + (x1 - x0) * 0.12, y0 + 100, x0 + (x1 - x0) * 0.42, y0 + 700)
            self.label(x0 + (x1 - x0) * 0.27, y0 + 400, "MB", 6.5)
            window = {"side": "bottom", "at": (x0 + x1) / 2, "w": (x1 - x0) * 0.55, "kind": "window", "axis": "h", "pos": y1, "room": room}
            self._gap_wall(window)
            self._opening(window)

    def _gap_wall(self, spec):
        """壁を描いたあとに開ける住戸の開口。白で抜く代わりに、ここだけ線で区切る。"""
        half = spec["w"] / 2
        px1, py1 = self.px(spec["at"] - half, spec["pos"])
        px2, py2 = self.px(spec["at"] + half, spec["pos"])
        self.sheet.solid_rect(px1, py1 - 2.2, px2 - px1, 4.4, "壁", color="#ffffff")

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
            if room.get("symbol") in ("cubicle", "transformer", "pump", "pump_stand", "panel_stand", "water_tank", "generator"):
                y = y0 + (y1 - y0) * 0.3
            elif room.get("symbol") in ("pit", "parking", "bike", "slope"):
                y = y0 + (y1 - y0) * 0.26
            elif room.get("symbol") in ("ev", "ev_bank"):
                y = y0 + (y1 - y0) * 0.84
            elif room.get("symbol") == "stair":
                y = y0 + (y1 - y0) * 0.1
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
        left, right = self.view.x(-margin), self.view.x(W + margin)
        site_bottom = self.view.y(H + margin)
        s.path([(left, self.view.y(-margin)), (right, self.view.y(-margin)), (right, site_bottom), (left, site_bottom)], "敷地", True)
        walk = site_bottom + 2500 * scale
        s.line(left - 30, site_bottom, right + 10, site_bottom, "道路")
        s.line(left - 30, walk, right + 10, walk, "道路")
        if mark.get("slope"):
            s.text(self.view.x(W * 0.72), (site_bottom + walk) / 2, mark["label"], 8.5, layer="道路")
            s.text(right + 6, self.view.y(-margin), "丘の側（高い）", 8.5, "start", layer="道路", bold=True)
            s.text(right + 14, walk, "前の道路（低い）", 8.5, "start", layer="道路", bold=True)
            s.arrow(right + 24, self.view.y(0), right + 24, self.view.y(H), "道路", 8)
            s.text(right + 12, self.view.y(H / 2), "下り", 8, layer="道路", rotate=-90)
        else:
            s.text(self.view.x(W * 0.72), (site_bottom + walk) / 2, "歩道", 9, layer="道路", bold=True)
            s.text(self.view.x(W * 0.9), walk + 13, "公道（前面道路）", 9, layer="道路", bold=True)
        entrance = self.view.x(W * 0.46)
        s.solid([(entrance, site_bottom - 7), (entrance - 6, site_bottom + 3), (entrance + 6, site_bottom + 3)], "図枠")
        s.text(entrance, site_bottom + 12, "マンション出入口", 8, layer="道路")

    def draw_balconies(self):
        if self.spec.get("balcony_ring"):
            W, H = self.size
            self.box(0, 0, W, H, "建具")
            self.label(W / 2, 900, "バルコニー", 7.5)
            self.label(W / 2, H - 900, "バルコニー", 7.5)
            return
        units = [r["mm"] for r in self.rooms if r.get("unit")]
        if not units:
            return
        bottom = max(u[3] for u in units)
        limit = self.size[1]
        for i, (x0, _, x1, _) in enumerate(units):
            self.box(x0 + 80, bottom, x1 - 80, min(bottom + 1500, limit))
            self.label(x0 + (x1 - x0) * (0.76 if i == 0 else 0.5), min(bottom + 750, limit - 500), "バルコニー", 7)
        hatch_x = units[0][0] + 300
        self.box(hatch_x, bottom + 300, hatch_x + 600, bottom + 900)
        self.label(hatch_x + 1500, bottom + 600, "避難ハッチ", 6.5)

    def draw(self, scale_text):
        s = self.sheet
        s.use(self.view)
        self.fill_rooms()
        self.draw_grid()
        self.draw_rooms()
        self.draw_walls()
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
    ("wall", "壁"),
    ("column", "柱"),
    ("door", "片開き扉・両開き扉"),
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
        x = x0 + (i % 3) * 200 if columns else x0
        yy = y0 + 24 + (i // 3) * 24 if columns else y0 + 22 + i * 22
        if kind == "wall":
            sheet.solid_rect(x, yy - 2, 30, 4, "壁")
        elif kind == "column":
            sheet.solid_rect(x + 9, yy - 6, 12, 12, "柱")
        elif kind == "door":
            sheet.line(x + 8, yy + 6, x + 8, yy - 6, "建具")
            sheet.arc(x + 8, yy + 6, 12, 270, 360, "建具")
        elif kind == "shutter":
            sheet.line(x, yy, x + 30, yy, "シャッター")
        elif kind == "site":
            sheet.line(x, yy, x + 30, yy, "敷地")
        elif kind == "conduit":
            sheet.line(x, yy, x + 30, yy, "引込")
        elif kind.startswith("fill:"):
            sheet.solid_rect(x, yy - 7, 30, 14, "部屋の色", color=ROOM_COLORS[kind[5:]])
            sheet.rect(x, yy - 7, 30, 14, "設備", 0.6)
        sheet.text(x + 40, yy, "引込線（空中）" if aerial and kind == "conduit" else name, 11, "start")


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
        PlanView(sheet, spec, left, top, scale, (W, H), sample["grid"]).draw("S=1/100")
        extra = 100 if any(m["kind"] == "road" for m in spec.get("marks", [])) else 26
        title_of(sheet, left + width / 2, top + H * scale + extra, spec["name"], "S=1/100")
    if sample["id"] == "a":
        north(sheet, 1110, 120)
        legend(sheet, 1070, 190)
    else:
        north(sheet, 70 + 40, 850)
        legend(sheet, 200, 836, aerial=sample["id"] == "b", columns=True)
    return sheet


# 水の入り道の断面

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
    "発電機室": "floor",
    "雨水貯留槽": "floor",
    "車路": "floor",
    "エントランス": "floor",
}


def _section_short(sample):
    """水の位置①②③の短い言い方。断面図の凡例と画面の重ね絵で同じ文を使う。"""
    short = {1: "道路・スロープ・壁の穴に達した", 2: "一番低い床に達した", 3: "盤・高圧受変電設備の下端に達した"}
    if not sample["underground_feed"]:
        short[1], short[3] = "前の道路・坂下の扉に達した", "架台の上の盤の下端に達した"
    return short


def _section_key(sheet, sample, x, y):
    """断面の読み方を短く。長い説明は書かない。"""
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
    columns = ((x + 420, "水の入り道", [p for p in sample["pins"] if p["target"] in entries]), (x + 720, "水に弱い設備", [p for p in sample["pins"] if p["target"] not in entries]))
    for px, heading, pins in columns:
        sheet.text(px, y, heading, 12, "start", bold=True)
        for i, pin in enumerate(pins):
            _pin(sheet, px + 13, y + 28 + 30 * i, pin["key"])
            sheet.text(px + 34, y + 28 + 30 * i, pin["title"], 11, "start")


def section_underground(sheet, sample, view, left, base):
    """地下に機器がある建物の模式断面。部屋は順に並べた展開で、実際の並びとは違う。"""
    s = view.scale
    X = lambda mm: left + mm * s
    Z = lambda mm: base - mm * s
    has_gen = sample["id"] == "c"
    wall, slab = 300, 300
    build_left = 9000
    if has_gen:
        rooms = [(9300, "受変電室"), (14500, "借室"), (18000, "発電機室"), (21000, "給水ポンプ室"), (25000, "雨水貯留槽"), (28500, "車路")]
        build_right, upper_right = 32500, 25000
    else:
        rooms = [(9300, "電気室"), (15000, "借室"), (19000, "給水ポンプ室"), (23500, "車路")]
        build_right, upper_right = 28500, 28500
    floor_1, top_2, b1 = 500, 4300, -4500
    level_3 = b1 + 1300
    pipe = -1400
    slope_top = build_right + 5500
    # 道路と土
    sheet.line(X(0), Z(0), X(5000), Z(0), "道路", 2)
    sheet.line(X(5000), Z(0), X(5000), Z(150), "道路", 2)
    sheet.line(X(5000), Z(150), X(build_left), Z(150), "道路", 2)
    sheet.text(X(2500), Z(0) - 14, "公道（前面道路）", 12, layer="道路", bold=True)
    sheet.text(X(8000), Z(150) - 14, "歩道", 12, layer="道路", bold=True)
    sheet.hatch(X(0), Z(0) + 2, X(5900) - X(0), Z(b1 - 600) - Z(0) - 2, gap=20)
    sheet.hatch(X(7000), Z(0) + 2, X(build_left) - X(7000), Z(b1 - 600) - Z(0) - 2, gap=20)
    # 部屋の種類の薄い塗り（壁より先に描く）。
    for i, (x, name) in enumerate(rooms):
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right
        kind = SECTION_KIND.get(name)
        if kind:
            sheet.solid_rect(X(x), Z(floor_1 - slab), X(room_end) - X(x), Z(b1) - Z(floor_1 - slab), "部屋の色", color=ROOM_COLORS[kind])
    # 建物
    sheet.solid_rect(X(build_left), Z(floor_1), X(build_right) - X(build_left), slab * s, "壁")
    sheet.solid_rect(X(build_left), Z(top_2), X(upper_right) - X(build_left), slab * s, "壁")
    sheet.solid_rect(X(build_left), Z(b1), X(build_right) - X(build_left), slab * s, "壁")
    sheet.solid_rect(X(build_left), Z(top_2 + 700), wall * s, Z(b1 - slab) - Z(top_2 + 700), "壁")
    sheet.solid_rect(X(upper_right - wall), Z(top_2 + 700), wall * s, Z(floor_1) - Z(top_2 + 700), "壁")
    sheet.solid_rect(X(build_right - wall), Z(floor_1), wall * s, Z(-1200) - Z(floor_1), "壁")
    sheet.line(X(build_left), Z(top_2 + 700), X(upper_right), Z(top_2 + 700), "図枠", 1)
    middle = (X(build_left) + X(upper_right)) / 2
    sheet.text(middle, Z(top_2 + 700) - 14, f"2階より上は省略（全{sample['floors']}階建て）", 11)
    sheet.text(middle, (Z(floor_1) + Z(top_2)) / 2, "1階", 13, bold=True)
    for i, (x, name) in enumerate(rooms):
        if i:
            sheet.solid_rect(X(x), Z(floor_1 - slab), 150 * s, Z(b1) - Z(floor_1 - slab), "壁")
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right
        sheet.text((X(x) + X(room_end)) / 2, Z(-450), name, _fit_label(name, X(room_end) - X(x), 26, 12), bold=True)
    sheet.text(X(build_left) + 12, Z(floor_1) - 12, "1FL", 11, "start", layer="寸法")
    sheet.text(X(build_left) - 8, Z(b1) + 4, "地下1階FL", 11, "end", layer="寸法")
    sheet.text(X(0) - 6, Z(0), "GL", 11, "end", layer="寸法")
    # 機器
    elec_end = rooms[1][0]
    cub_x, cub_w = elec_end - 3400, 2800
    sheet.rect(X(cub_x), Z(level_3 + 1600), cub_w * s, 1600 * s, "設備")
    for leg in (cub_x + 300, cub_x + cub_w - 300):
        sheet.line(X(leg), Z(level_3), X(leg), Z(b1), "設備")
    sheet.text(X(cub_x + cub_w / 2), Z(level_3 + 800), "受変電設備" if has_gen else "高圧受変電設備\n（キュービクル）", 11)
    tr_x, tr_end = rooms[1][0] + 400, rooms[2][0] - 400
    sheet.rect(X(tr_x), Z(level_3 + 1300), (tr_end - tr_x) * s, 1300 * s, "設備")
    sheet.text((X(tr_x) + X(tr_end)) / 2 + 16, Z(level_3 + 650), "？", 18, bold=True)
    sheet.text((X(tr_x) + X(tr_end)) / 2, Z(-1100), "中は建物側から\n分からない", 10.5)
    pump_room = rooms[3][0] if has_gen else rooms[2][0]
    sheet.circle(X(pump_room + 1000), Z(b1 + 500), 500 * s, "設備")
    sheet.text(X(pump_room + 1700), Z(b1 + 450), "ポンプ", 10.5, "start")
    sheet.rect(X(pump_room + 2700), Z(level_3 + 1100), 1000 * s, 1100 * s, "設備")
    sheet.text(X(pump_room + 2300), Z(level_3 + 1450), "制御盤（壁掛け）", 10.5)
    if has_gen:
        sheet.rect(X(18400), Z(b1 + 1500), 2200 * s, 1500 * s, "設備")
        sheet.text(X(19500), Z(b1 + 750), "発電機", 11)
        _water_lines(sheet, X(25150), Z(b1 + 2200), X(28400) - X(25150), 2200 * s, 11)
    # 引込（HH → 管 → 壁の穴 → 高圧受変電設備）
    hh_x, hh_w = 5900, 1100
    sheet.rect(X(hh_x), Z(150), hh_w * s, 2100 * s, "引込", 2)
    sheet.text(X(hh_x + hh_w / 2), Z(150) - 34, "歩道ぎわの蓋（HH）", 11.5, layer="寸法", bold=True)
    sheet.line(X(hh_x + hh_w), Z(pipe), X(build_left), Z(pipe), "引込", 2.4)
    sheet.text(X(8000), Z(pipe) + 30, "電線の管", 11, layer="寸法")
    sheet.circle(X(build_left + 150), Z(pipe), 7, "引込")
    sheet.line(X(build_left + 300), Z(pipe), X(cub_x + 300), Z(pipe), "引込", 2.4)
    sheet.line(X(cub_x + 300), Z(pipe), X(cub_x + 300), Z(level_3 + 1600), "引込", 2.4)
    sheet.text(X(build_left + 500), Z(pipe) - 14, "ケーブルを通す壁の穴", 11, "start", layer="寸法", bold=True)
    # 水の入り道
    sheet.arrow(X(3900), Z(0) + 10, X(hh_x + 300), Z(-600), "水の入り道", 12)
    sheet.arrow(X(hh_x + hh_w + 100), Z(pipe - 350), X(build_left + 1700), Z(pipe - 350), "水の入り道", 12)
    _pin(sheet, X(build_left + 2200), Z(pipe - 350), "ア")
    _pin(sheet, (X(tr_x) + X(tr_end)) / 2 - 22, Z(level_3 + 650), "エ")
    _pin(sheet, X(pump_room + 2100), Z(level_3 + 500), "イ")
    sheet.line(X(build_right), Z(b1 + 300), X(slope_top), Z(150), "道路", 2)
    sheet.line(X(slope_top), Z(150), X(slope_top + 2200), Z(150), "道路", 2)
    sheet.text(X(slope_top + 1100), Z(150) - 14, "車路の入口", 12, layer="道路", bold=True)
    mx, mz = (X(build_right) + X(slope_top)) / 2, (Z(b1 + 300) + Z(150)) / 2
    sheet.text(mx + 20, mz + 30, "車路スロープ", 12, "start", layer="道路", bold=True)
    sheet.arrow(X(slope_top) - 8, Z(150) - 10, X(build_right) - 10, Z(b1 + 1100), "水の入り道", 12)
    if has_gen:
        basin = X(27600)
        sheet.rect(basin - 11, Z(floor_1) - 14, 22, 14, "寸法", 2)
        sheet.text(basin, Z(floor_1) - 28, "敷地の雨水ます", 11.5, layer="寸法", bold=True)
        sheet.arrow(basin, Z(floor_1 - slab) + 2, basin, Z(b1 + 2300), "水の入り道", 12)
        _pin(sheet, basin - 32, Z(-1600), "ウ")
        sheet.text(basin + 14, Z(-2100), "満水で\nあふれる", 10, "start", layer="寸法")
        sheet.text(mx + 20, mz + 48, "（ここからも入る）", 11, "start", layer="寸法")
    else:
        _pin(sheet, mx - 30, mz - 26, "ウ")
    # 水の位置
    for key, z in ((2, b1 + 150), (3, level_3)):
        sheet.line(X(build_left + 300), Z(z), X(build_right - 300), Z(z), "水の位置")
        _level_mark(sheet, X(rooms[-1][0] + 1600), Z(z), key)
    _level_mark(sheet, X(4500), Z(0) - 16, 1)
    # 画面の重ね絵（web/section-anim.js）が使う基準の座標。上で描いた値をそのまま渡し、図は変えない。
    room_spans = []
    for i, (x, name) in enumerate(rooms):
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right - wall
        room_spans.append({"name": name, "role": _ROOM_ROLES[name], "x0": X(x + (150 if i else 0)), "x1": X(room_end)})
    anchors = {
        "kind": "underground",
        "floor_y": Z(b1),
        "ceiling_y": Z(floor_1 - slab),
        "levels": {"2": Z(b1 + 150), "3": Z(level_3)},
        "rooms": room_spans,
        "outside": [
            {"profile": [[X(0), Z(0)], [X(5000), Z(0)], [X(5000), Z(150)], [X(build_left), Z(150)]]},
            {"profile": [[X(slope_top), Z(150)], [X(slope_top + 2200), Z(150)]]},
        ],
        "outside_levels": {"1": Z(150 + 200), "2": Z(150 + 400), "3": Z(150 + 700)},
        "handhole": [X(hh_x), Z(150), hh_w * s, 2100 * s],
        "equipment": {
            "hv": {"rect": [X(cub_x), Z(level_3 + 1600), cub_w * s, 1600 * s]},
            "tr": {"rect": [X(tr_x), Z(level_3 + 1300), (tr_end - tr_x) * s, 1300 * s]},
            "panel": {"rect": [X(pump_room + 2700), Z(level_3 + 1100), 1000 * s, 1100 * s]},
            "pump": {"circle": [X(pump_room + 1000), Z(b1 + 500), 500 * s]},
        },
        "routes": [
            {"key": "hole", "guard": "hv", "points": [[X(hh_x + hh_w / 2), Z(150)], [X(hh_x + hh_w / 2), Z(pipe)], [X(build_left + 150), Z(pipe)], [X(build_left + 900), Z(pipe)], [X(build_left + 900), Z(b1 + 700)]], "block": [X(build_left + 150), Z(pipe)]},
            {"key": "slope", "points": [[X(slope_top + 1100), Z(150)], [X(slope_top), Z(150)], [X(build_right), Z(b1 + 300)], [X(rooms[-1][0]), Z(b1 + 300)]]},
        ],
        "stage_names": {str(k): v for k, v in _section_short(sample).items()},
        # 画面のビューアーで寄せて見せる、図のある範囲（用紙の px。左・上・右・下）。
        "focus": [round(X(0) - 40, 1), round(Z(top_2 + 700) - 40, 1), round(X(slope_top + 2200) + 30, 1), round(Z(b1 - 600) + 20, 1)],
    }
    if has_gen:
        anchors["equipment"]["gen"] = {"rect": [X(18400), Z(b1 + 1500), 2200 * s, 1500 * s]}
        anchors["routes"].append({"key": "basin", "points": [[X(27600), Z(floor_1)], [X(27600), Z(b1 + 2300)]]})
    return anchors


def section_hillside(sheet, sample, view, left, base):
    """機器が1階にある建物の模式断面。丘から低い側へ水が下りてくる。"""
    s = view.scale
    X = lambda mm: left + mm * s
    Z = lambda mm: base - mm * s
    build_left, build_right, floor_1, wall = 7000, 28000, 300, 300
    top_2 = floor_1 + 3300
    sheet.line(X(0), Z(0), X(4500), Z(0), "道路", 2)
    sheet.line(X(4500), Z(0), X(4500), Z(100), "道路", 2)
    sheet.line(X(4500), Z(100), X(build_left), Z(200), "道路", 2)
    sheet.line(X(build_right), Z(1000), X(32000), Z(1800), "道路", 2)
    sheet.line(X(32000), Z(1800), X(38500), Z(5500), "道路", 2)
    sheet.text(X(2600), Z(0) - 14, "前の道路（低い）", 12, layer="道路", bold=True)
    sheet.text(X(5700), Z(100) + 16, "敷地内通路", 11, layer="道路", bold=True)
    sheet.text(X(37000), Z(5500) - 10, "丘の側（高い）", 12, layer="道路", bold=True)
    sheet.hatch(X(0), Z(-400), X(38500) - X(0), 50, gap=16)
    sheet.solid_rect(X(build_left), Z(floor_1), X(build_right) - X(build_left), 300 * s, "壁")
    sheet.solid_rect(X(build_left), Z(top_2), X(build_right) - X(build_left), 300 * s, "壁")
    for x in (build_left, build_right - wall):
        sheet.solid_rect(X(x), Z(top_2 + 700), wall * s, Z(floor_1) - Z(top_2 + 700), "壁")
    sheet.line(X(build_left), Z(top_2 + 700), X(build_right), Z(top_2 + 700), "図枠", 1)
    sheet.text((X(build_left) + X(build_right)) / 2, Z(top_2 + 700) - 14, f"2階より上は省略（全{sample['floors']}階建て）", 11)
    rooms = [(7300, "共用分電盤室"), (13000, "借室"), (18000, "給水ポンプ室"), (23000, "エントランス")]
    # 部屋の種類の薄い塗り（外壁の内側だけ。間仕切りの壁はこのあとで上に描く）。
    for i, (x, name) in enumerate(rooms):
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right - wall
        kind = SECTION_KIND.get(name)
        if kind:
            sheet.solid_rect(X(x), Z(top_2 - 300), X(room_end) - X(x), Z(floor_1) - Z(top_2 - 300), "部屋の色", color=ROOM_COLORS[kind])
    for i, (x, name) in enumerate(rooms):
        if i:
            sheet.solid_rect(X(x), Z(top_2 - 300), 150 * s, Z(floor_1) - Z(top_2 - 300), "壁")
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right
        # 1階の部屋は低いので、中の「？」と重ならない大きさにとどめる。
        sheet.text((X(x) + X(room_end)) / 2, Z(top_2 - 300) + 15, name, _fit_label(name, X(room_end) - X(x), 20, 12), bold=True)
    for x, w, name in ((8800, 2800, "主開閉器盤"), (19400, 2400, "制御盤")):
        sheet.line(X(x), Z(floor_1), X(x), Z(floor_1 + 500), "設備")
        sheet.line(X(x + w), Z(floor_1), X(x + w), Z(floor_1 + 500), "設備")
        sheet.rect(X(x), Z(floor_1 + 1900), w * s, 1400 * s, "設備")
        sheet.text(X(x + w / 2), Z(floor_1 + 1200), f"{name}\n（架台の上）", 10)
    sheet.rect(X(13800), Z(floor_1 + 2000), 3200 * s, 1500 * s, "設備")
    sheet.text(X(15400), Z(floor_1 + 1750), "？", 18, bold=True)
    sheet.text(X(15400), Z(floor_1 + 1050), "中は建物側から\n分からない", 10)
    sheet.line(X(build_left), Z(floor_1 + 2100), X(build_left), Z(floor_1 + 200), "建具", 2.4)
    sheet.rect(X(build_left) - 3, Z(floor_1 + 80) - 9, 9, 9, "設備")
    sheet.text(X(build_left) - 10, Z(floor_1 + 1700), "坂下側出入口\n足元換気口", 11.5, "end", layer="寸法", bold=True)
    attach = floor_1 + 2600
    sheet.line(X(800), Z(0), X(800), Z(6200), "設備", 2)
    sheet.line(X(800), Z(5800), X(build_left), Z(attach), "引込", 2.4)
    sheet.solid_rect(X(build_left) - 5, Z(attach) - 5, 10, 10, "図枠")
    sheet.text(X(800) + 8, Z(6100), "電柱（空中からの引込み）", 11.5, "start", layer="寸法", bold=True)
    sheet.text(X(1300), Z(3100), "外壁の取付点（例）。\nその先の経路は\n図から分からない", 10.5, "start", layer="寸法")
    sheet.arrow(X(37500), Z(5000) - 14, X(30000), Z(1450) - 14, "水の入り道", 12)
    sheet.arrow(X(5800), Z(650), X(build_left) + 2, Z(520), "水の入り道", 12)
    sheet.text(X(29000), Z(5600), "雨水が坂を下り、\n建物の脇を回って低い側へ", 11.5, "start", layer="寸法", bold=True)
    _pin(sheet, X(4600), Z(1000), "ウ")
    _pin(sheet, X(8100), Z(floor_1 + 1500), "ア")
    _pin(sheet, X(18700), Z(floor_1 + 1500), "イ")
    _pin(sheet, X(14200), Z(floor_1 + 2350), "エ")
    for key, z in ((2, floor_1 + 120), (3, floor_1 + 500)):
        sheet.line(X(build_left + 300), Z(z), X(build_right - 300), Z(z), "水の位置")
        _level_mark(sheet, X(24200 if key == 2 else 26200), Z(z), key)
    _level_mark(sheet, X(1600), Z(0) - 36, 1)
    # 画面の重ね絵（web/section-anim.js）が使う基準の座標。上で描いた値をそのまま渡し、図は変えない。
    room_spans = []
    for i, (x, name) in enumerate(rooms):
        room_end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right - wall
        room_spans.append({"name": name, "role": _ROOM_ROLES[name], "x0": X(x + (150 if i else 0)), "x1": X(room_end)})
    return {
        "kind": "hillside",
        "floor_y": Z(floor_1),
        "ceiling_y": Z(top_2 - 300),
        "levels": {"2": Z(floor_1 + 120), "3": Z(floor_1 + 500)},
        "rooms": room_spans,
        "outside": [
            {"profile": [[X(0), Z(0)], [X(4500), Z(0)], [X(4500), Z(100)], [X(build_left), Z(200)]]},
        ],
        "outside_levels": {"1": Z(floor_1 + 50), "2": Z(floor_1 + 120 + 150), "3": Z(floor_1 + 500 + 150)},
        "equipment": {
            "hv": {"rect": [X(8800), Z(floor_1 + 1900), 2800 * s, 1400 * s]},
            "panel": {"rect": [X(19400), Z(floor_1 + 1900), 2400 * s, 1400 * s]},
            "tr": {"rect": [X(13800), Z(floor_1 + 2000), 3200 * s, 1500 * s]},
        },
        "routes": [
            {"key": "hill", "points": [[X(37500), Z(5000) - 14], [X(30000), Z(1450) - 14]]},
            {"key": "door", "points": [[X(5800), Z(650)], [X(build_left) + 2, Z(520)]]},
        ],
        "stage_names": {str(k): v for k, v in _section_short(sample).items()},
        # 画面のビューアーで寄せて見せる、図のある範囲（用紙の px。左・上・右・下）。
        "focus": [round(X(0) - 20, 1), round(Z(6200) - 30, 1), round(X(38500) + 20, 1), round(Z(-400) + 60, 1)],
    }


def section_sheet(sample):
    number = {"a": "A-201", "b": "A-211", "c": "A-221"}[sample["id"]]
    if sample["id"] == "b":
        scale = 0.0335
        sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, scale)
        frame_and_title(sheet, sample, "竣工図 模式断面図（水の入り道）", number, "模式")
        view = View(80, 560, scale)
        sheet.use(view)
        sheet.anchors = section_hillside(sheet, sample, view, 80, 560)
    else:
        width = 40500 if sample["id"] == "c" else 36500
        scale = 1260 / width
        sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, scale)
        frame_and_title(sheet, sample, "竣工図 模式断面図（水の入り道）", number, "模式")
        view = View(80, 470, scale)
        sheet.use(view)
        sheet.anchors = section_underground(sheet, sample, view, 80, 470)
    sheet.use(None)
    title_of(sheet, 520, 720, "模式断面図（水の入り道）", "部屋は順に並べた展開")
    _section_key(sheet, sample, 80, 770)
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
