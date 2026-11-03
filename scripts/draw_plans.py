"""架空の見本の竣工図を CAD の線で描く。python3 -m scripts.draw_plans

見本ごとに、平面図の用紙（ピンを立てる図）と、基準階と水の入り道の断面の用紙を作り、
SVG と DXF に書き出す。PDF は手元の Chrome、PNG は macOS の sips で作る。
"""

from __future__ import annotations

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

    def px(self, x, y):
        return self.view.x(x), self.view.y(y)

    def line(self, x1, y1, x2, y2, layer="設備"):
        self.sheet.line(*self.px(x1, y1), *self.px(x2, y2), layer)

    def box(self, x0, y0, x1, y1, layer="設備"):
        px, py = self.px(x0, y0)
        self.sheet.rect(px, py, (x1 - x0) * self.view.scale, (y1 - y0) * self.view.scale, layer)

    def label(self, x, y, value, size=8, layer="文字", bold=False):
        self.sheet.text(*self.px(x, y), value, size, layer=layer, bold=bold)

    # 通り芯と寸法

    def draw_grid(self):
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
            self.label(cx, y1 - h * 0.22, "受電の箱（キュービクル）", 8)
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
            self.label(cx, y1 - h * 0.24, "共用部の盤（架台の上）", 7)
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
            size = _fit_label(room["label"], width)
            y = (y0 + y1) / 2
            if room.get("symbol") in ("cubicle", "transformer", "pump", "pump_stand", "panel_stand", "water_tank", "generator"):
                y = y0 + (y1 - y0) * 0.3
            elif room.get("symbol") in ("pit", "parking", "bike", "slope"):
                y = y0 + (y1 - y0) * 0.26
            elif room.get("symbol") in ("ev", "ev_bank"):
                y = y0 + (y1 - y0) * 0.84
            elif room.get("symbol") == "stair":
                y = y0 + (y1 - y0) * 0.1
            self.sheet.text(*self.px((x0 + x1) / 2, y), room["label"], size, bold=True)

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
]


def legend(sheet, x, y, aerial=False):
    sheet.text(x, y, "凡例", 10, "start", bold=True)
    for i, (kind, name) in enumerate(LEGEND):
        yy = y + 20 + i * 19
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
        sheet.text(x + 40, yy, "引込線（空中）" if aerial and kind == "conduit" else name, 9.5, "start")


def frame_and_title(sheet, sample, drawing_name, number, scale_text):
    sheet.rect(16, 16, PLAN_WIDTH - 32, PLAN_HEIGHT - 32, "図枠", 2)
    sheet.text(PLAN_WIDTH - 36, 40, "※架空の見本です。実在の建物の図面ではありません。", 13, "end", bold=True)
    x, y, w = PLAN_WIDTH - 396, PLAN_HEIGHT - 124, 376
    rows = [("工事名称", f"{sample['name']} 新築工事"), ("図面名称", drawing_name), ("縮尺", scale_text), ("図番", number)]
    sheet.rect(x, y, w, 104, "図枠", 1.6)
    for i, (name, value) in enumerate(rows):
        yy = y + 26 * i
        if i:
            sheet.line(x, yy, x + w, yy, "図枠", 0.8)
        sheet.text(x + 8, yy + 13, name, 9, "start")
        sheet.text(x + 68, yy + 13, value, 10.5, "start", bold=True)
    sheet.line(x + 60, y, x + 60, y + 104, "図枠", 0.8)


def plan_sheet(sample, world_y=0.0):
    W, H = sample["plan_size"]
    frames = sample["plan_frames"]
    scale = frames[0][2] / W
    sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, scale, world_y)
    number = {"a": "A-101", "b": "A-111", "c": "A-121"}[sample["id"]]
    frame_and_title(sheet, sample, sample["title"].replace(" ※架空の見本", ""), number, "S=1/100（用紙に合わせて縮小）")
    for index, (left, top, width) in frames.items():
        spec = sample["views"][index]
        plan = PlanView(sheet, spec, left, top, scale, (W, H), sample["grid"])
        plan.draw("S=1/100")
        extra = 98 if any(m["kind"] == "road" for m in spec.get("marks", [])) else 24
        title_of(sheet, left + width / 2, top + H * scale + extra, spec["name"], "S=1/100")
    if sample["id"] == "c":
        legend(sheet, 130, 790)
        north(sheet, 330, 830)
        sheet.text(420, 810, "タワー型（内廊下・中央コア）。\n機器は地下1階にまとまる例で、機器の構成は一例です。\n壁の穴の止水の有無は図から分かりません。", 11, "start")
    else:
        lx = frames[0][0] + frames[0][2] + 56
        north(sheet, lx + 40, 160)
        legend(sheet, lx, 230, aerial=sample["id"] == "b")
        kind = "板状型（外廊下）で、\n機器が地下1階にある例です。\n壁の穴の止水の有無は\n図から分かりません。" if sample["id"] == "a" else "小規模（外廊下）で、\n機器が1階にある例です。\n空中からの引込みの例です。"
        sheet.text(lx, 420, kind, 11, "start")
    return sheet


# 水の入り道の断面

def _levels(sheet, x, y, sample, second=None):
    """断面の読み方。水の位置、ピンの意味、図から分からないこと。"""
    sheet.text(x, y, "水の位置（画面の①②③と同じ）", 10.5, "start", bold=True)
    yy = y + 20
    for level in WATER_LEVELS:
        sheet.circle(x + 9, yy, 9, "水の入り道")
        sheet.text(x + 9, yy, level["label"].replace("①", "1").replace("②", "2").replace("③", "3"), 9, color="#0277bd", bold=True)
        text = level["text"]
        lines = [text[i:i + 26] for i in range(0, len(text), 26)]
        for j, line in enumerate(lines):
            sheet.text(x + 24, yy + j * 13, line, 9.5, "start")
        yy += 12 + 13 * len(lines)
    sheet.text(x, yy + 2, "破線は模式で、高さの値ではありません。", 9.5, "start", color="#0277bd", bold=True)
    sheet.text(x, yy + 15, "全部の部屋が同じ高さになるという意味でもありません。", 9.5, "start", color="#0277bd", bold=True)
    yy += 36
    if second:
        x, yy = second
    sheet.text(x, yy, "図の印", 10.5, "start", bold=True)
    yy += 16
    for pin in sample["pins"]:
        sheet.text(x, yy, f"{pin['key']}　{pin['title']}", 9.5, "start")
        yy += 14
    notes = ["青の矢印は水の入り道です。青い文字は場所の名前です。"]
    if sample["underground_feed"]:
        notes.append("壁の穴の止水の有無は、この図から分かりません。")
    notes += ["借室への引込みの経路は建物側から分からないので描いていません。", "ポンプの盤が浸かると給水が止まります。受電の箱とは別のものです。", "機器の構成は一例です。"]
    yy += 4
    for note in notes:
        sheet.text(x, yy, note, 9, "start")
        yy += 12


def _pin(sheet, x, y, key):
    sheet.circle(x, y, 11, "図枠")
    sheet.text(x, y, key, 11, bold=True)


def section_underground(sheet, sample, view, left, base):
    """地下に機器がある建物の模式断面。部屋は順に並べた展開で、実際の並びとは違う。"""
    s = view.scale
    X = lambda mm: left + mm * s
    Z = lambda mm: base - mm * s
    has_gen = sample["id"] == "c"
    wall = 300
    build_left, build_right = 10000, 37000 if has_gen else 34500
    upper_right = 27500 if has_gen else build_right
    floor_1, b1, slab = 500, -3800, 300
    tops = [floor_1 + 3400, floor_1 + 6400]
    pipe = -1500
    # 道路と地面
    sheet.line(X(0), Z(0), X(6000), Z(0), "道路", 1.6)
    sheet.line(X(6000), Z(150), X(build_left), Z(150), "道路", 1.6)
    sheet.line(X(6000), Z(0), X(6000), Z(150), "道路", 1.6)
    sheet.text(X(3000), Z(0) - 11, "公道（前面道路）", 9.5, layer="道路", bold=True)
    sheet.text(X(8200), Z(150) - 11, "歩道", 9.5, layer="道路", bold=True)
    sheet.hatch(X(0), Z(0) + 2, X(7200) - X(0), Z(-5200) - Z(0) - 2, gap=18)
    sheet.hatch(X(8300), Z(0) + 2, X(build_left) - X(8300), Z(-5200) - Z(0) - 2, gap=18)
    # 建物の床と壁
    sheet.solid_rect(X(build_left), Z(floor_1), X(upper_right) - X(build_left), slab * s, "壁")
    if upper_right < build_right:
        sheet.solid_rect(X(upper_right), Z(floor_1), X(build_right) - X(upper_right), slab * s, "壁")
    sheet.solid_rect(X(build_left), Z(tops[0]), X(upper_right) - X(build_left), slab * s, "壁")
    sheet.solid_rect(X(build_left), Z(b1), X(build_right) - X(build_left), slab * s, "壁")
    sheet.solid_rect(X(build_left), Z(tops[-1]), wall * s, Z(b1 - slab) - Z(tops[-1]), "壁")
    sheet.solid_rect(X(upper_right - wall), Z(tops[-1]), wall * s, Z(floor_1) - Z(tops[-1]), "壁")
    # 地下の右の壁は、スロープの口を開ける。
    sheet.solid_rect(X(build_right - wall), Z(floor_1), wall * s, Z(-900) - Z(floor_1), "壁")
    sheet.line(X(build_left), Z(tops[-1]), X(upper_right), Z(tops[-1]), "図枠", 1)
    middle = (X(build_left) + X(upper_right)) / 2
    sheet.text(middle, Z(tops[-1]) - 11, f"3階より上は省略（全{sample['floors']}階建て）", 9.5)
    sheet.text(middle, (Z(floor_1) + Z(tops[0])) / 2, "1階（管理員室、エントランス）" if not has_gen else "1階（防災センター、エントランスホール）", 10)
    sheet.text(middle, (Z(tops[0]) + Z(tops[1])) / 2, "2階（住戸）", 10)
    # 地下の部屋
    if has_gen:
        walls = [(10300, "受変電室"), (17000, "借室"), (20000, "発電機室"), (23300, "給水ポンプ室"), (27500, "雨水貯留槽"), (31500, "車路")]
    else:
        walls = [(10300, "電気室"), (17000, "借室"), (21500, "給水ポンプ室"), (26500, "車路")]
    for i, (x, name) in enumerate(walls):
        room_end = walls[i + 1][0] if i + 1 < len(walls) else build_right
        if i:
            sheet.solid_rect(X(x), Z(floor_1 - slab), 150 * s, Z(b1) - Z(floor_1 - slab), "壁")
        sheet.text((X(x) + X(room_end)) / 2, Z(-250), name, 10.5, bold=True)
    # 機器
    cub_x = 14000
    level_3 = b1 + 1100
    sheet.rect(X(cub_x), Z(b1 + 2600), 2700 * s, 1500 * s, "設備")
    sheet.line(X(cub_x + 300), Z(level_3), X(cub_x + 300), Z(b1), "設備")
    sheet.line(X(cub_x + 2400), Z(level_3), X(cub_x + 2400), Z(b1), "設備")
    sheet.text(X(cub_x + 1350), Z(b1 + 1850), "受電の箱\n（キュービクル）", 8.5)
    tr_x = 17600
    tr_w = 2000 if has_gen else 3200
    sheet.rect(X(tr_x), Z(b1 + 2300), tr_w * s, 1200 * s, "設備")
    sheet.text(X(tr_x + tr_w / 2 + 200), Z(b1 + 1700), "？", 14, bold=True)
    sheet.text(X(tr_x + tr_w / 2), Z(-1000), "中は建物側から\n分からない", 8)
    pump_start = walls[3][0] if has_gen else walls[2][0]
    sheet.circle(X(pump_start + 900), Z(b1 + 450), 450 * s, "設備")
    sheet.text(X(pump_start + 1700), Z(b1 + 450), "ポンプ", 8)
    sheet.rect(X(pump_start + 2600), Z(level_3 + 1000), 900 * s, 1000 * s, "設備")
    sheet.text(X(pump_start + 2300), Z(-1050), "制御盤（壁掛け）", 8)
    if has_gen:
        sheet.rect(X(20400), Z(b1 + 1300), 2500 * s, 1300 * s, "設備")
        sheet.text(X(21650), Z(b1 + 650), "発電機", 8.5)
        _water_lines(sheet, X(27650), Z(b1 + 2000), X(31500) - X(27650), 2000 * s)
    # 引込
    hh_x, hh_top, hh_bottom = 7300, 150, -2000
    sheet.rect(X(hh_x), Z(hh_top), 900 * s, (hh_top - hh_bottom) * s, "引込", 1.6)
    sheet.text(X(hh_x + 900), Z(hh_top) - 27, "歩道ぎわの蓋（HH）", 9, "end", layer="寸法", bold=True)
    sheet.line(X(hh_x + 900), Z(pipe), X(build_left), Z(pipe), "引込")
    sheet.text(X(9100), Z(pipe) + 14, "電線の管", 8.5, layer="寸法")
    sheet.circle(X(build_left + 150), Z(pipe), 6, "引込")
    sheet.text(X(build_left + 400), Z(-2340), "ケーブルを通す壁の穴", 8.5, "start", layer="寸法", bold=True)
    sheet.line(X(build_left + 300), Z(pipe), X(cub_x), Z(pipe), "引込")
    # 水の入り道
    sheet.arrow(X(4200), Z(0) + 8, X(7100), Z(-1100), "水の入り道")
    sheet.arrow(X(hh_x + 950), Z(pipe - 230), X(build_left + 1000), Z(pipe - 230), "水の入り道")
    _pin(sheet, X(build_left + 1700), Z(pipe - 230), "ア")
    _pin(sheet, X(tr_x + tr_w / 2 - 500), Z(b1 + 1700), "エ")
    _pin(sheet, X(pump_start + 2000), Z(level_3 + 500), "イ")
    # スロープ
    slope_top = 40000
    sheet.line(X(build_right), Z(b1 + 200), X(slope_top), Z(150), "道路", 1.6)
    sheet.line(X(slope_top), Z(150), X(slope_top + 2300), Z(150), "道路", 1.6)
    sheet.text(X(slope_top + 1100), Z(150) - 12, "車路の入口", 9, layer="道路", bold=True)
    mx, mz = (X(build_right) + X(slope_top)) / 2, (Z(b1 + 200) + Z(150)) / 2
    sheet.text(mx + 16, mz + 26, "車路スロープ", 9, "start", layer="道路", bold=True)
    sheet.arrow(X(slope_top) - 6, Z(150) - 8, X(build_right) - 6, Z(b1 + 900), "水の入り道")
    if has_gen:
        basin = X(31000)
        sheet.rect(basin - 9, Z(floor_1) - 12, 18, 12, "寸法", 1.6)
        sheet.text(basin, Z(floor_1) - 24, "敷地の雨水ます", 8.5, layer="寸法", bold=True)
        sheet.arrow(basin, Z(floor_1 - slab) + 2, basin, Z(b1 + 2100), "水の入り道")
        _pin(sheet, basin - 26, Z(-1400), "ウ")
    else:
        _pin(sheet, mx - 24, mz - 22, "ウ")
    # 水の位置
    marker = walls[-1][0] + 1400
    for key, z in ((2, b1 + 120), (3, level_3)):
        sheet.line(X(build_left + 300), Z(z), X(build_right - 300), Z(z), "水の位置")
        sheet.circle(X(marker), Z(z), 8.5, "水の入り道")
        sheet.text(X(marker), Z(z), str(key), 8.5, color="#0277bd", bold=True)
    sheet.circle(X(5200), Z(0) - 15, 8.5, "水の入り道")
    sheet.text(X(5200), Z(0) - 15, "1", 8.5, color="#0277bd", bold=True)
    # 高さの記号
    sheet.text(X(0) - 6, Z(0), "GL", 9, "end", layer="寸法")
    sheet.text(X(build_left) - 6, Z(floor_1) - 8, "1FL", 9, "end", layer="寸法")
    sheet.text(X(build_left) - 6, Z(b1) + 2, "地下1階FL", 9, "end", layer="寸法")


def section_hillside(sheet, sample, view, left, base):
    """機器が1階にある建物の模式断面。丘から低い側へ水が下りてくる。"""
    s = view.scale
    X = lambda mm: left + mm * s
    Z = lambda mm: base - mm * s
    build_left, build_right = 7000, 28000
    floor_1 = 300
    wall = 300
    # 地面
    sheet.line(X(0), Z(0), X(4500), Z(0), "道路", 1.6)
    sheet.line(X(4500), Z(100), X(build_left), Z(200), "道路", 1.6)
    sheet.line(X(4500), Z(0), X(4500), Z(100), "道路", 1.6)
    sheet.line(X(build_right), Z(1000), X(32000), Z(1800), "道路", 1.6)
    sheet.line(X(32000), Z(1800), X(39000), Z(6000), "道路", 1.6)
    sheet.text(X(2900), Z(0) - 12, "前の道路（低い）", 9.5, layer="道路", bold=True)
    sheet.text(X(5700), Z(100) + 14, "敷地内通路", 9, layer="道路", bold=True)
    sheet.text(X(36500), Z(6000) - 8, "丘の側（高い）", 9.5, layer="道路", bold=True)
    sheet.hatch(X(0), Z(-400), X(39000) - X(0), 46, gap=14)
    # 建物
    tops = [floor_1 + 3300 * i for i in range(1, 3)]
    for z in (floor_1, *tops[:-1]):
        sheet.solid_rect(X(build_left), Z(z), X(build_right) - X(build_left), 300 * s, "壁")
    for x in (build_left, build_right - wall):
        sheet.solid_rect(X(x), Z(tops[-1]), wall * s, Z(floor_1) - Z(tops[-1]), "壁")
    sheet.line(X(build_left), Z(tops[-1]), X(build_right), Z(tops[-1]), "図枠", 1)
    sheet.text((X(build_left) + X(build_right)) / 2, Z(tops[-1]) - 11, f"3階より上は省略（全{sample['floors']}階建て）", 9.5)
    sheet.text((X(build_left) + X(build_right)) / 2, (Z(tops[0]) + Z(tops[1])) / 2, "2階（住戸）", 10)
    # 1階の部屋
    rooms = [(7300, "共用分電盤室"), (13000, "借室"), (18000, "給水ポンプ室"), (23000, "エントランス")]
    for i, (x, name) in enumerate(rooms):
        end = rooms[i + 1][0] if i + 1 < len(rooms) else build_right
        if i:
            sheet.solid_rect(X(x), Z(tops[0] - 300), 150 * s, Z(floor_1) - Z(tops[0] - 300), "壁")
        sheet.text((X(x) + X(end)) / 2, Z(tops[0] - 300) + 13, name, 10.5, bold=True)
    # 機器
    for x, w, name in ((9000, 2600, "共用部の盤"), (19500, 2200, "制御盤")):
        sheet.path([(X(x), Z(floor_1)), (X(x), Z(floor_1 + 500))], "設備")
        sheet.path([(X(x + w), Z(floor_1)), (X(x + w), Z(floor_1 + 500))], "設備")
        sheet.rect(X(x), Z(floor_1 + 1900), w * s, 1400 * s, "設備")
        sheet.text(X(x + w / 2), Z(floor_1 + 1200), f"{name}\n（架台の上）", 8)
    sheet.rect(X(13800), Z(floor_1 + 2000), 2600 * s, 1500 * s, "設備")
    sheet.text(X(15700), Z(floor_1 + 1250), "？", 14, bold=True)
    sheet.text(X(15100), Z(floor_1 + 2280), "中は建物側から分からない", 8)
    # 扉と換気口
    sheet.solid_rect(X(build_left) - 1, Z(floor_1 + 2100), 5, 1900 * s, "図枠", "#ffffff")
    sheet.line(X(build_left), Z(floor_1 + 2100), X(build_left), Z(floor_1 + 200), "建具", 2)
    sheet.rect(X(build_left) - 2, Z(floor_1 + 80) - 8, 8, 8, "設備")
    sheet.text(X(build_left) - 8, Z(floor_1 + 1900), "坂下側出入口\n足元換気口", 8.5, "end", layer="寸法", bold=True)
    # 引込
    sheet.line(X(800), Z(0), X(800), Z(6200), "設備", 1.6)
    attach = floor_1 + 2600
    sheet.line(X(800), Z(5800), X(build_left), Z(attach), "引込")
    sheet.solid_rect(X(build_left) - 4, Z(attach) - 4, 8, 8, "図枠")
    sheet.text(X(800) + 6, Z(6000), "電柱（空中からの引込み）", 8.5, "start", layer="寸法")
    sheet.text(X(1200), Z(2300), "外壁の取付点（例）。\n借室までの経路は\n建物側から分からない", 8, "start", layer="寸法")
    # 水の入り道
    sheet.arrow(X(38000), Z(5400) - 12, X(30000), Z(1450) - 12, "水の入り道")
    sheet.arrow(X(6200), Z(600), X(build_left) + 2, Z(500), "水の入り道")
    sheet.text(X(28800), Z(5300), "雨水が坂を下り、\n建物の脇を回って低い側へ", 9, "start", layer="寸法", bold=True)
    _pin(sheet, X(5900), Z(1250), "ウ")
    _pin(sheet, X(8200), Z(floor_1 + 1500), "ア")
    _pin(sheet, X(18800), Z(floor_1 + 1500), "イ")
    _pin(sheet, X(14600), Z(floor_1 + 1250), "エ")
    # 水の位置
    for key, z in ((2, floor_1 + 120), (3, floor_1 + 500)):
        sheet.line(X(build_left + 300), Z(z), X(build_right - 300), Z(z), "水の位置")
        sheet.circle(X(26500), Z(z), 8.5, "水の入り道")
        sheet.text(X(26500), Z(z), str(key), 8.5, color="#0277bd", bold=True)
    sheet.circle(X(3000), Z(0) - 34, 8.5, "水の入り道")
    sheet.text(X(3000), Z(0) - 34, "1", 8.5, color="#0277bd", bold=True)
    sheet.text(X(0) - 6, Z(0), "GL", 9, "end", layer="寸法")


def section_sheet(sample, world_y=0.0):
    W, H = sample["plan_size"]
    number = {"a": "A-201", "b": "A-211", "c": "A-221"}[sample["id"]]
    typical = next((v for v in sample["views"] if v["name"] == "基準階平面図"), None)
    name = "竣工図 基準階平面図・模式断面図（水の入り道）"
    if sample["id"] == "a":
        sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, 840 / W, world_y)
        frame_and_title(sheet, sample, name, number, "S=1/100、断面は模式")
        PlanView(sheet, typical, 130, 110, 840 / W, (W, H), sample["grid"]).draw("S=1/100")
        title_of(sheet, 550, 436, typical["name"], "S=1/100")
        north(sheet, 1060, 130)
        _levels(sheet, 1010, 170, sample)
    elif sample["id"] == "b":
        sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, 720 / W, world_y)
        frame_and_title(sheet, sample, "竣工図 模式断面図（水の入り道）", number, "模式")
        section = View(100, 510, 0.0325)
        sheet.use(section)
        section_hillside(sheet, sample, section, 100, 510)
        sheet.use(None)
        title_of(sheet, 590, 670, "模式断面図（水の入り道）", "部屋は順に並べた展開")
        _levels(sheet, 130, 705, sample, second=(520, 705))
        sheet.text(520, 850, "基準階の平面図は、平面図の用紙（A-111）にあります。", 10, "start")
        return sheet
    else:
        scale = 330 / W
        sheet = Sheet(PLAN_WIDTH, PLAN_HEIGHT, scale, world_y)
        frame_and_title(sheet, sample, name, number, "S=1/100、断面は模式")
        PlanView(sheet, typical, 120, 110, scale, (W, H), sample["grid"]).draw("S=1/100")
        title_of(sheet, 285, 470, typical["name"], "S=1/100")
        north(sheet, 560, 150)
        _levels(sheet, 620, 90, sample)
    section = View(110, 745, 0.027)
    sheet.use(section)
    section_underground(sheet, sample, section, 110, 745)
    sheet.use(None)
    title_of(sheet, 500, 950, "模式断面図（水の入り道）", "部屋は順に並べた展開")
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
        plan = plan_sheet(sample)
        # DXF では 2 枚を上下に並べる。平面図の下に余白を空ける。
        section = section_sheet(sample, world_y=-(PLAN_HEIGHT + 100) / plan.paper.scale)
        for name, sheet in ((f"plan_{sid}", plan), (f"section_{sid}", section)):
            with open(os.path.join(OUT_DIR, f"{name}.svg"), "w", encoding="utf-8") as handle:
                handle.write(svg(sheet))
            names.append(name)
        with open(os.path.join(OUT_DIR, f"drawings_{sid}.dxf"), "wb") as handle:
            handle.write(dxf([plan, section]))
        with open(os.path.join(OUT_DIR, f"report_{sid}.txt"), "w", encoding="utf-8") as handle:
            handle.write(REPORTS[sid])
    if not os.path.exists(CHROME):
        print("Chrome がないので SVG と DXF だけ作りました。", file=sys.stderr)
        return
    for name in names:
        export(CHROME, name)
    shutil.rmtree(os.path.join(OUT_DIR, ".chrome"), ignore_errors=True)


if __name__ == "__main__":
    main()
