"""架空の見本の竣工図風の平面図を、コードで描く。python3 -m scripts.draw_plans

通り芯、寸法線、扉の開閉記号、階段、EV、スロープの勾配の矢印、図面枠を描き、
SVG に書き出す。PDF は手元の Chrome、PNG は macOS の sips で作る。
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
import sys
import time

from app.samples import PLAN_HEIGHT, PLAN_WIDTH, REPORTS, SAMPLES, VIEW_ORIGINS, VIEW_SIZE

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "samples")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FONT = 'font-family="Hiragino Sans, Yu Gothic, Noto Sans JP, sans-serif"'
INK = "#111111"
THIN = 'stroke="#111111" stroke-width="0.8" fill="none"'
GRID = 'stroke="#c0392b" stroke-width="0.6" stroke-dasharray="14 3 2 3" fill="none"'
DIM = 'stroke="#2d5f9a" stroke-width="0.6" fill="none"'
DIM_TEXT = 'fill="#2d5f9a" font-size="9"'

X_AXES = [0, 1 / 3, 2 / 3, 1]
Y_AXES = [0, 1 / 2, 1]
SPAN_X = 7200
SPAN_Y = 8400


def text(x, y, value, size=11, anchor="middle", extra=""):
    lines = str(value).split("\n")
    out = []
    for i, line in enumerate(lines):
        dy = (i - (len(lines) - 1) / 2) * (size + 2)
        out.append(
            f'<text x="{x:.1f}" y="{y + dy + size / 3:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{INK}" {FONT} {extra}>{html.escape(line)}</text>'
        )
    return "".join(out)


class View:
    def __init__(self, index, spec):
        self.left, self.top = VIEW_ORIGINS[index]
        self.w, self.h = VIEW_SIZE
        self.spec = spec

    def x(self, value):
        return self.left + value * self.w

    def y(self, value):
        return self.top + value * self.h

    def grid(self):
        parts = []
        for i, axis in enumerate(X_AXES):
            x = self.x(axis)
            parts.append(f'<line x1="{x}" y1="{self.top - 62}" x2="{x}" y2="{self.top + self.h + 30}" {GRID}/>')
            parts.append(f'<circle cx="{x}" cy="{self.top - 74}" r="12" {THIN}/>')
            parts.append(text(x, self.top - 74, f"X{i + 1}", 10))
        for i, axis in enumerate(Y_AXES):
            y = self.y(axis)
            parts.append(f'<line x1="{self.left - 62}" y1="{y}" x2="{self.left + self.w + 24}" y2="{y}" {GRID}/>')
            parts.append(f'<circle cx="{self.left - 74}" cy="{y}" r="12" {THIN}/>')
            parts.append(text(self.left - 74, y, f"Y{i + 1}", 10))
        return "".join(parts)

    def dimensions(self):
        parts = []
        y = self.top - 38
        parts.append(f'<line x1="{self.x(0)}" y1="{y}" x2="{self.x(1)}" y2="{y}" {DIM}/>')
        for i, axis in enumerate(X_AXES):
            x = self.x(axis)
            parts.append(f'<line x1="{x - 4}" y1="{y + 4}" x2="{x + 4}" y2="{y - 4}" {DIM}/>')
            if i < 3:
                mid = self.x(axis + 1 / 6)
                parts.append(f'<text x="{mid}" y="{y - 4}" text-anchor="middle" {DIM_TEXT} {FONT}>{SPAN_X:,}</text>')
        x = self.left - 38
        parts.append(f'<line x1="{x}" y1="{self.y(0)}" x2="{x}" y2="{self.y(1)}" {DIM}/>')
        for i, axis in enumerate(Y_AXES):
            yy = self.y(axis)
            parts.append(f'<line x1="{x - 4}" y1="{yy + 4}" x2="{x + 4}" y2="{yy - 4}" {DIM}/>')
            if i < 2:
                mid = self.y(axis + 1 / 4)
                parts.append(
                    f'<text x="{x - 5}" y="{mid}" text-anchor="middle" transform="rotate(-90 {x - 5} {mid})" '
                    f'{DIM_TEXT} {FONT}>{SPAN_Y:,}</text>'
                )
        return "".join(parts)

    def room(self, room):
        x, y = self.x(room["x"]), self.y(room["y"])
        w, h = room["w"] * self.w, room["h"] * self.h
        parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{"url(#hatch)" if room.get("hatch") else "#ffffff"}" stroke="{INK}" stroke-width="4"/>']
        symbol = room.get("symbol")
        if symbol == "ev":
            parts.append(f'<line x1="{x + 6}" y1="{y + 6}" x2="{x + w - 6}" y2="{y + h - 6}" {THIN}/>')
            parts.append(f'<line x1="{x + w - 6}" y1="{y + 6}" x2="{x + 6}" y2="{y + h - 6}" {THIN}/>')
            parts.append(f'<rect x="{x + 6}" y="{y + 6}" width="{w - 12}" height="{h - 12}" {THIN}/>')
        if symbol == "stair":
            steps = 12
            for i in range(1, steps):
                yy = y + h * i / steps
                parts.append(f'<line x1="{x + 3}" y1="{yy}" x2="{x + w - 3}" y2="{yy}" {THIN}/>')
            parts.append(f'<line x1="{x + w / 2}" y1="{y + h - 8}" x2="{x + w / 2}" y2="{y + 10}" stroke="{INK}" stroke-width="1" marker-end="url(#arrow)"/>')
            parts.append(text(x + w / 2, y + h - 18, "UP", 8, extra='font-weight="600"'))
        if symbol == "slope":
            parts.append(f'<line x1="{x + w - 26}" y1="{y + h - 26}" x2="{x + 34}" y2="{y + 34}" stroke="{INK}" stroke-width="1.6" marker-end="url(#arrow)"/>')
            parts.append(text(x + w - 56, y + 40, "勾配 1/6 下り", 9))
            for i in range(1, 7):
                xx = x + w * i / 7
                parts.append(f'<line x1="{xx}" y1="{y + 2}" x2="{xx}" y2="{y + h - 2}" stroke="#999999" stroke-width="0.5"/>')
        door = room.get("door")
        if door:
            size = min(34, w * 0.34)
            dx = x + w * 0.5
            if door == "top":
                parts.append(f'<rect x="{dx}" y="{y - 3}" width="{size}" height="6" fill="#ffffff" stroke="none"/>')
                parts.append(f'<line x1="{dx}" y1="{y}" x2="{dx}" y2="{y + size}" stroke="{INK}" stroke-width="1.2"/>')
                parts.append(f'<path d="M {dx} {y + size} A {size} {size} 0 0 0 {dx + size} {y}" {THIN}/>')
            else:
                yy = y + h
                parts.append(f'<rect x="{dx}" y="{yy - 3}" width="{size}" height="6" fill="#ffffff" stroke="none"/>')
                parts.append(f'<line x1="{dx}" y1="{yy}" x2="{dx}" y2="{yy - size}" stroke="{INK}" stroke-width="1.2"/>')
                parts.append(f'<path d="M {dx} {yy - size} A {size} {size} 0 0 1 {dx + size} {yy}" {THIN}/>')
        label_y = y + h / 2
        if symbol in ("stair", "ev"):
            parts.append(f'<rect x="{x + w / 2 - 15}" y="{label_y - 9}" width="30" height="18" fill="#ffffff"/>')
        if symbol == "slope":
            label_y = y + h - 24
        parts.append(text(x + w / 2, label_y, room["label"], 12 if w > 80 else 9, extra='font-weight="600"'))
        return "".join(parts)

    def mark(self, mark):
        kind = mark["kind"]
        if kind == "sidewalk":
            y1, y2 = self.y(1.04), self.y(1.2)
            return (
                f'<line x1="{self.x(-0.04)}" y1="{y1}" x2="{self.x(1.04)}" y2="{y1}" {THIN}/>'
                f'<line x1="{self.x(-0.04)}" y1="{y2}" x2="{self.x(1.04)}" y2="{y2}" {THIN}/>'
                + text(self.x(0.62), self.y(1.12), f'{mark["label"]}（前面道路側）', 10)
            )
        x, y = self.x(mark["x"]), self.y(mark["y"])
        if kind == "conduit":
            return (
                f'<line x1="{x}" y1="{y}" x2="{self.x(mark["x2"])}" y2="{self.y(mark["y2"])}" stroke="#2d5f9a" stroke-width="1.6" stroke-dasharray="7 4"/>'
                + text(x + 8, (y + self.y(mark["y2"])) / 2, mark["label"], 9, "start")
            )
        if kind == "hh":
            return f'<rect x="{x - 11}" y="{y - 11}" width="22" height="22" fill="#ffffff" stroke="#2d5f9a" stroke-width="1.6"/><line x1="{x - 11}" y1="{y}" x2="{x + 11}" y2="{y}" stroke="#2d5f9a"/>' + text(x + 16, y, mark["label"], 9, "start")
        if kind == "conduit_hole":
            return f'<circle cx="{x}" cy="{y}" r="7" fill="#ffffff" stroke="#2d5f9a" stroke-width="1.6"/>' + text(x + 12, y + 16, mark["label"], 9, "start")
        if kind == "basin":
            return f'<rect x="{x - 9}" y="{y - 9}" width="18" height="18" fill="#ffffff" stroke="#2d5f9a" stroke-width="1.6"/><line x1="{x - 9}" y1="{y - 9}" x2="{x + 9}" y2="{y + 9}" stroke="#2d5f9a"/><line x1="{x + 9}" y1="{y - 9}" x2="{x - 9}" y2="{y + 9}" stroke="#2d5f9a"/>' + text(x, y + 19, mark["label"], 9)
        if kind == "door_low":
            return f'<rect x="{x - 30}" y="{y - 2}" width="60" height="5" fill="#2d5f9a"/>' + text(x, y + 16, mark["label"], 9)
        return ""

    def draw(self):
        rooms = "".join(self.room(room) for room in self.spec["rooms"])
        marks = "".join(self.mark(mark) for mark in self.spec.get("marks", []))
        title = text(self.x(0.5), self.y(1.27), self.spec["name"] + "　S=1/100", 13, extra='font-weight="600"')
        rule = f'<line x1="{self.x(0.28)}" y1="{self.y(1.29)}" x2="{self.x(0.72)}" y2="{self.y(1.29)}" stroke="{INK}" stroke-width="1"/>'
        return self.grid() + self.dimensions() + rooms + marks + title + rule


def title_block(sample):
    x, y = PLAN_WIDTH - 470, PLAN_HEIGHT - 110
    rows = [
        ("工事名称", f"{sample['name']} 新築工事"),
        ("図面名称", sample["title"]),
        ("縮尺・図番", "S=1/100　A-" + {"a": "101", "b": "102", "c": "103"}[sample["id"]]),
    ]
    parts = [f'<rect x="{x}" y="{y}" width="450" height="90" fill="#ffffff" stroke="{INK}" stroke-width="1.6"/>']
    for i, (name, value) in enumerate(rows):
        yy = y + 30 * i
        if i:
            parts.append(f'<line x1="{x}" y1="{yy}" x2="{x + 450}" y2="{yy}" {THIN}/>')
        parts.append(text(x + 8, yy + 15, name, 9, "start"))
        parts.append(text(x + 80, yy + 15, value, 11, "start", 'font-weight="600"'))
    parts.append(f'<line x1="{x + 72}" y1="{y}" x2="{x + 72}" y2="{y + 90}" {THIN}/>')
    return "".join(parts)


def svg(sample):
    views = "".join(View(i, spec).draw() for i, spec in enumerate(sample["views"]))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {PLAN_WIDTH} {PLAN_HEIGHT}" width="{PLAN_WIDTH}" height="{PLAN_HEIGHT}">'
        '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#111111"/></marker>'
        '<pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="10" stroke="#777777" stroke-width="1"/></pattern></defs>'
        f'<rect width="{PLAN_WIDTH}" height="{PLAN_HEIGHT}" fill="#ffffff"/>'
        f'<rect x="16" y="16" width="{PLAN_WIDTH - 32}" height="{PLAN_HEIGHT - 32}" fill="none" stroke="{INK}" stroke-width="2"/>'
        + text(40, 50, "※架空の見本です。実在の建物の図面ではありません。", 13, "start", 'font-weight="600"')
        + views
        + title_block(sample)
        + "</svg>"
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
    for sample in SAMPLES.values():
        name = f"plan_{sample['id']}"
        with open(os.path.join(OUT_DIR, f"{name}.svg"), "w", encoding="utf-8") as handle:
            handle.write(svg(sample))
        with open(os.path.join(OUT_DIR, f"report_{sample['id']}.txt"), "w", encoding="utf-8") as handle:
            handle.write(REPORTS[sample["id"]])
    if not os.path.exists(CHROME):
        print("Chrome がないので SVG だけ作りました。", file=sys.stderr)
        return
    for sample in SAMPLES.values():
        export(CHROME, f"plan_{sample['id']}")
    shutil.rmtree(os.path.join(OUT_DIR, ".chrome"), ignore_errors=True)


if __name__ == "__main__":
    main()
