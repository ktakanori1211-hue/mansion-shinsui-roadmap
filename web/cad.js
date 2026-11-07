/* 架空の建物の竣工図を、建築 CAD の線で描く（平面図と断面図）。
 * 依存なし・DOM に触らない。window.CAD / globalThis.CAD = { plan, section, esc }。
 * 寸法は mm で持ち、描くときだけ px にする。返す svg は <svg> の中身だけ（外側は呼ぶ側が包む）。
 * 描く建物はすべて架空。実在の建物を指す文字は入れない。
 */
(function () {
  var root = typeof globalThis !== "undefined" ? globalThis : (typeof window !== "undefined" ? window : this);

  // 線の色と太さ（単色の墨の図面。寸法だけ少し薄く、引込管は青）
  var INK = "#111", DIM = "#444", AXIS = "#9a9a9a", FEED = "#1565c0", WHITE = "#fff";
  var FONT = "'Hiragino Sans','Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif";
  var OUTER = 300, INNER = 150, COLUMN = 800; // 外壁・内壁の厚さと柱の一辺（mm）
  var OPEN_AIR = { soil: 1, garden: 1 };      // 壁を立てない「部屋」
  var FILL = { power: "#fdf0e3", water: "#e5f0fa", lift: "#ece9f5", car: "#ececec" };
  var KIND = {
    elec: "power", tr: "power", panel_room: "power", gen: "power",
    pump: "water", water_tank: "water", tank: "water",
    ev: "lift", ev_1f: "lift", stair: "lift", stair_1f: "lift", ev_pit_room: "lift",
    park: "car", park_1f: "car", aisle: "car", slope: "car", parking_flat: "car",
  };
  var MACHINE = { cubicle: 1, transformer: 1, pump: 1, pump_stand: 1, panel_stand: 1, water_tank: 1, generator: 1 };
  var uid = 0;

  // 文字と数の整形

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmt(mm) { return String(Math.round(mm)).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
  function n(v) { return Math.round(v * 10) / 10; }
  function attrs(o) {
    var s = "";
    for (var k in o) if (o[k] !== undefined && o[k] !== null && o[k] !== "") s += " " + k + '="' + o[k] + '"';
    return s;
  }
  // 部屋の名前の 1 行目。括弧の中は落とす（「借室（東京電力…」→「借室」）。
  function shortLabel(label) {
    var first = String(label || "").split("\n")[0];
    var plain = first.replace(/[（(].*$/, "").trim();
    return plain || first.replace(/[（）()]/g, "");
  }
  function fitSize(text, widthPx, largest, smallest) {
    var longest = Math.max(1, String(text).length);
    return Math.max(smallest, Math.min(largest, widthPx * 0.9 / longest));
  }

  // 線を貯めるペン。o: c=色 w=太さ d=破線 f=塗り s=文字の大きさ a=寄せ b=太字 r=回転

  function Pen() { this.out = []; }
  Pen.prototype.add = function (s) { this.out.push(s); };
  Pen.prototype.line = function (x1, y1, x2, y2, o) {
    o = o || {};
    this.add("<line" + attrs({ x1: n(x1), y1: n(y1), x2: n(x2), y2: n(y2), stroke: o.c || INK, "stroke-width": o.w || 0.7, "stroke-dasharray": o.d }) + "/>");
  };
  Pen.prototype.rect = function (x, y, w, h, o) {
    if (w <= 0 || h <= 0) return;
    o = o || {};
    var stroke = o.c !== undefined ? o.c : (o.f ? "none" : INK);
    this.add("<rect" + attrs({ x: n(x), y: n(y), width: n(w), height: n(h), fill: o.f || "none", stroke: stroke, "stroke-width": o.w || 0.7, "stroke-dasharray": o.d, "class": o.cls, "data-room": o.room }) + "/>");
  };
  Pen.prototype.box = function (x0, y0, x1, y1, o) { this.rect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0), o); };
  Pen.prototype.circle = function (cx, cy, r, o) {
    o = o || {};
    this.add("<circle" + attrs({ cx: n(cx), cy: n(cy), r: n(r), fill: o.f || "none", stroke: o.c !== undefined ? o.c : INK, "stroke-width": o.w || 0.7, "stroke-dasharray": o.d }) + "/>");
  };
  Pen.prototype.poly = function (pts, o) {
    o = o || {};
    var p = pts.map(function (q) { return n(q[0]) + "," + n(q[1]); }).join(" ");
    this.add("<" + (o.close ? "polygon" : "polyline") + attrs({ points: p, fill: o.f || "none", stroke: o.c !== undefined ? o.c : INK, "stroke-width": o.w || 0.7, "stroke-dasharray": o.d, "stroke-linejoin": "round" }) + "/>");
  };
  Pen.prototype.text = function (x, y, value, o) {
    o = o || {};
    var size = o.s || 8, lines = String(value == null ? "" : value).split("\n");
    var t = "<text" + attrs({ x: n(x), y: n(y), "font-size": n(size), "text-anchor": o.a || "middle", "font-weight": o.b ? "700" : null, fill: o.c || INK, "dominant-baseline": "central", transform: o.r ? "rotate(" + o.r + " " + n(x) + " " + n(y) + ")" : null, "paint-order": o.halo ? "stroke" : null, stroke: o.halo ? WHITE : null, "stroke-width": o.halo ? 2.5 : null, "stroke-linejoin": o.halo ? "round" : null }) + ">";
    if (lines.length === 1) t += esc(lines[0]);
    else lines.forEach(function (line, i) { t += "<tspan" + attrs({ x: n(x), dy: i ? n(size * 1.15) : n(-(lines.length - 1) * size * 1.15 / 2) }) + ">" + esc(line) + "</tspan>"; });
    this.add(t + "</text>");
  };
  // 円弧。中心 (cx,cy) から見た点 a → 点 b を、短い方の弧で結ぶ。
  Pen.prototype.arc = function (cx, cy, a, b, o) {
    o = o || {};
    var r = Math.hypot(a[0] - cx, a[1] - cy);
    var cross = (a[0] - cx) * (b[1] - cy) - (a[1] - cy) * (b[0] - cx);
    this.add("<path" + attrs({ d: "M" + n(a[0]) + " " + n(a[1]) + " A" + n(r) + " " + n(r) + " 0 0 " + (cross > 0 ? 1 : 0) + " " + n(b[0]) + " " + n(b[1]), fill: "none", stroke: o.c || INK, "stroke-width": o.w || 0.6 }) + "/>");
  };
  Pen.prototype.arrow = function (x1, y1, x2, y2, o) {
    o = o || {};
    var head = o.h || 6, ang = Math.atan2(y2 - y1, x2 - x1);
    this.line(x1, y1, x2, y2, o);
    this.poly([[x2, y2], [x2 - head * Math.cos(ang - 0.4), y2 - head * Math.sin(ang - 0.4)], [x2 - head * Math.cos(ang + 0.4), y2 - head * Math.sin(ang + 0.4)]], { f: o.c || INK, c: "none", close: true });
  };
  // 斜線（土）と横線（水）の模様。塗りに url(#id) で使う。
  Pen.prototype.pattern = function (id, kind) {
    var body = kind === "water"
      ? '<line x1="0" y1="4" x2="8" y2="4" stroke="' + DIM + '" stroke-width="0.5"/>'
      : '<line x1="0" y1="8" x2="8" y2="0" stroke="#777" stroke-width="0.5"/>';
    this.add('<defs><pattern id="' + id + '" patternUnits="userSpaceOnUse" width="8" height="8">' + body + "</pattern></defs>");
    return "url(#" + id + ")";
  };
  // 寸法の斜めの印（45 度の短い線）
  Pen.prototype.tick = function (x, y) { this.line(x - 2.5, y + 2.5, x + 2.5, y - 2.5, { c: DIM, w: 0.6 }); };
  Pen.prototype.bubble = function (x, y, label, r) {
    this.circle(x, y, r || 9, { w: 0.7 });
    this.text(x, y, label, { s: (r || 9) * 0.85 });
  };
  Pen.prototype.north = function (x, y) {
    this.circle(x, y, 10, { w: 0.8 });
    this.poly([[x, y - 13], [x - 4, y + 7], [x + 4, y + 7]], { f: INK, c: "none", close: true });
    this.text(x, y - 20, "N", { s: 8, b: true });
  };
  Pen.prototype.title = function (x, y, text) {
    this.text(x, y, text, { s: 11, b: true });
    this.line(x - 100, y + 9, x + 100, y + 9, { w: 0.9 });
  };
  Pen.prototype.svg = function () { return this.out.join("\n"); };

  // ----------------------------------------------------------------- 平面図

  function structural(room) { return !OPEN_AIR[room.key] && !room.outdoor && room.symbol !== "garden"; }

  // 通り芯：部屋の端を集め、300 mm 以内は一つにし、多いときは近い所から間引く。
  function gridLines(rooms, size, axis, cap) {
    var vals = [0, size];
    rooms.forEach(function (r) { if (structural(r)) vals.push(r.mm[axis], r.mm[axis + 2]); });
    vals.sort(function (a, b) { return a - b; });
    var out = [];
    vals.forEach(function (v) { if (!out.length || v - out[out.length - 1] > 300) out.push(v); });
    if (size - out[out.length - 1] <= 300) out[out.length - 1] = size; else out.push(size);
    for (var j = 1; j < out.length - 1;) { if (out[j] - out[j - 1] < 1500 || out[j + 1] - out[j] < 1500) out.splice(j, 1); else j++; }
    while (out.length > cap) {
      var best = 1, gap = Infinity;
      for (var i = 1; i < out.length - 1; i++) {
        var g = Math.min(out[i] - out[i - 1], out[i + 1] - out[i]);
        if (g < gap) { gap = g; best = i; }
      }
      out.splice(best, 1);
    }
    return out;
  }

  // 建具の一覧。住戸は玄関扉と窓を足す。
  function openingsOf(rooms) {
    var found = [];
    rooms.forEach(function (room) {
      var m = room.mm, specs = (room.openings || []).slice();
      if (room.unit_door) specs.push(room.unit_door);
      if (room.unit && !room.unit_door) {
        specs.push({ side: "top", at: m[0] + (m[2] - m[0]) * 0.7, kind: "door", w: 900 });
        specs.push({ side: "bottom", at: (m[0] + m[2]) / 2, kind: "window", w: (m[2] - m[0]) * 0.55 });
      }
      specs.forEach(function (sp) {
        var h = sp.side === "top" || sp.side === "bottom";
        found.push({ side: sp.side, at: sp.at, kind: sp.kind || "door", w: sp.w || 900, axis: h ? "h" : "v", pos: h ? (sp.side === "top" ? m[1] : m[3]) : (sp.side === "left" ? m[0] : m[2]), room: room });
      });
    });
    return found;
  }

  function PlanDraw(rooms, size, px, s) {
    this.rooms = rooms; this.W = size[0]; this.H = size[1]; this.px = px; this.s = s; this.pen = new Pen();
  }
  PlanDraw.prototype.line = function (x1, y1, x2, y2, o) { var a = this.px(x1, y1), b = this.px(x2, y2); this.pen.line(a[0], a[1], b[0], b[1], o); };
  PlanDraw.prototype.box = function (x0, y0, x1, y1, o) { var a = this.px(x0, y0), b = this.px(x1, y1); this.pen.box(a[0], a[1], b[0], b[1], o); };
  PlanDraw.prototype.solid = function (x0, y0, x1, y1, color) { this.box(x0, y0, x1, y1, { f: color || INK, c: "none" }); };
  PlanDraw.prototype.label = function (x, y, text, o) { var p = this.px(x, y); this.pen.text(p[0], p[1], text, o); };

  // 壁：部屋の辺を集めて重なりをまとめ、建具の所だけ抜く。外周は 300、内側は 150。
  PlanDraw.prototype.walls = function (openings) {
    var edges = {}, self = this;
    this.rooms.forEach(function (r) {
      if (!structural(r)) return;
      var m = r.mm;
      [["h", m[1], m[0], m[2]], ["h", m[3], m[0], m[2]], ["v", m[0], m[1], m[3]], ["v", m[2], m[1], m[3]]].forEach(function (e) {
        (edges[e[0] + ":" + e[1]] = edges[e[0] + ":" + e[1]] || []).push([e[2], e[3]]);
      });
    });
    Object.keys(edges).forEach(function (key) {
      var axis = key.charAt(0), pos = Number(key.slice(2));
      var merged = [];
      edges[key].sort(function (a, b) { return a[0] - b[0]; }).forEach(function (sp) {
        if (merged.length && sp[0] <= merged[merged.length - 1][1]) merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], sp[1]);
        else merged.push([sp[0], sp[1]]);
      });
      var cuts = openings.filter(function (o) { return o.axis === axis && o.pos === pos; })
        .map(function (o) { return [o.at - o.w / 2, o.at + o.w / 2]; }).sort(function (a, b) { return a[0] - b[0]; });
      var limit = axis === "h" ? self.H : self.W;
      var t = pos === 0 || pos === limit ? OUTER : INNER;
      merged.forEach(function (span) {
        var cursor = span[0];
        cuts.forEach(function (cut) {
          if (cut[1] <= cursor || cut[0] >= span[1]) return;
          self.wall(axis, pos, cursor, cut[0], t);
          cursor = cut[1];
        });
        self.wall(axis, pos, cursor, span[1], t);
      });
    });
    openings.forEach(function (o) { self.opening(o); });
  };
  PlanDraw.prototype.wall = function (axis, pos, start, end, t) {
    if (end <= start) return;
    if (axis === "h") this.solid(start, pos - t / 2, end, pos + t / 2);
    else this.solid(pos - t / 2, start, pos + t / 2, end);
  };
  // 建具。inward は部屋の内側へ向く向き（上辺なら下 +1）。
  PlanDraw.prototype.opening = function (o) {
    var pen = this.pen, half = o.w / 2, a = o.at - half, b = o.at + half;
    var inward = { top: 1, left: 1, bottom: -1, right: -1 }[o.side];
    var h = o.axis === "h";
    var p1 = h ? this.px(a, o.pos) : this.px(o.pos, a), p2 = h ? this.px(b, o.pos) : this.px(o.pos, b);
    var nx = h ? 0 : inward, ny = h ? inward : 0; // 内側の向き（px）
    if (o.kind === "shutter") pen.line(p1[0], p1[1], p2[0], p2[1], { w: 0.9, d: "4 2" });
    else if (o.kind === "open") pen.line(p1[0], p1[1], p2[0], p2[1], { w: 0.4 });
    else if (o.kind === "sliding") {
      var mx = (p1[0] + p2[0]) / 2, my = (p1[1] + p2[1]) / 2;
      pen.line(p1[0] + nx * 1.6, p1[1] + ny * 1.6, mx + (h ? 2 : 0) + nx * 1.6, my + (h ? 0 : 2) + ny * 1.6, { w: 0.7 });
      pen.line(mx - (h ? 2 : 0) - nx * 1.6, my - (h ? 0 : 2) - ny * 1.6, p2[0] - nx * 1.6, p2[1] - ny * 1.6, { w: 0.7 });
    } else if (o.kind === "window") {
      pen.line(p1[0] - nx * 1.2, p1[1] - ny * 1.2, p2[0] - nx * 1.2, p2[1] - ny * 1.2, { w: 0.5 });
      pen.line(p1[0] + nx * 1.2, p1[1] + ny * 1.2, p2[0] + nx * 1.2, p2[1] + ny * 1.2, { w: 0.5 });
    } else if (o.kind === "double") {
      var leaf = o.w * this.s / 2;
      this.leaf(p1, [nx, ny], h ? [1, 0] : [0, 1], leaf);
      this.leaf(p2, [nx, ny], h ? [-1, 0] : [0, -1], leaf);
    } else this.leaf(p1, [nx, ny], h ? [1, 0] : [0, 1], o.w * this.s);
  };
  // 片開きの扉と軌跡。hinge を軸に、壁から部屋の内側へ 90 度開く。along は反対の枠へ向く向き。
  PlanDraw.prototype.leaf = function (hinge, inward, along, size) {
    var tip = [hinge[0] + inward[0] * size, hinge[1] + inward[1] * size];
    var jamb = [hinge[0] + along[0] * size, hinge[1] + along[1] * size];
    this.pen.line(hinge[0], hinge[1], tip[0], tip[1], { w: 0.8 });
    this.pen.arc(hinge[0], hinge[1], tip, jamb, { w: 0.5 });
  };
  // 柱：通り芯の交点のうち、建物のある所。
  PlanDraw.prototype.columns = function (xs, ys) {
    var size = this.W === this.H ? 1100 : COLUMN, self = this;
    var inside = this.rooms.filter(structural).map(function (r) { return r.mm; });
    this.cols = [];
    xs.forEach(function (x) {
      ys.forEach(function (y) {
        if (!inside.some(function (m) { return m[0] <= x && x <= m[2] && m[1] <= y && y <= m[3]; })) return;
        var left = Math.min(Math.max(x - size / 2, 0), self.W - size), top = Math.min(Math.max(y - size / 2, 0), self.H - size);
        self.cols.push([left, top, left + size, top + size]);
      });
    });
    this.cols.forEach(function (c) { self.solid(c[0], c[1], c[2], c[3]); });
  };
  // 柱に重なるか（b は mm の [x0,y0,x1,y1]）
  PlanDraw.prototype.hitsColumn = function (b) { return (this.cols || []).some(function (c) { return c[0] < b[2] && c[2] > b[0] && c[1] < b[3] && c[3] > b[1]; }); };
  PlanDraw.prototype.inRoom = function (b, m) { return b[0] >= m[0] && b[2] <= m[2] && b[1] >= m[1] && b[3] <= m[3]; };
  // 記号の説明の字。中央 → 左右へずらす → 一行上 → 一行下の順に、柱に重ならず部屋に入る所へ置く。
  PlanDraw.prototype.caption = function (room, x, y, text, o) {
    var size = (o && o.s) || 8, tw = text.length * size / this.s, th = size * 1.2 / this.s, dx = tw / 2 + COLUMN / 2 + 150;
    var shifts = [[0, 0], [dx, 0], [-dx, 0], [0, -th * 1.3], [0, th * 1.3]];
    for (var i = 0; i < shifts.length; i++) {
      var cx = x + shifts[i][0], cy = y + shifts[i][1], b = [cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2];
      if (this.inRoom(b, room.mm) && !this.hitsColumn(b)) { this.label(cx, cy, text, o); return; }
    }
    this.label(x, y, text, o);
  };
  // 機器の箱。柱に重なるなら、柱の分だけ左右か上へずらす。
  PlanDraw.prototype.boxAvoid = function (room, x0, y0, x1, y1, o) {
    var d = COLUMN + 100, shifts = [[0, 0], [d, 0], [-d, 0], [0, -d]];
    for (var i = 0; i < shifts.length; i++) {
      var b = [x0 + shifts[i][0], y0 + shifts[i][1], x1 + shifts[i][0], y1 + shifts[i][1]];
      if (this.inRoom(b, room.mm) && !this.hitsColumn(b)) { this.box(b[0], b[1], b[2], b[3], o); return; }
    }
    this.box(x0, y0, x1, y1, o);
  };
  // 部屋の名前。幅に入らなければ折り返し、柱に重なるなら上下へずらす。
  PlanDraw.prototype.roomLabel = function (room, ry) {
    var m = room.mm, w = (m[2] - m[0]) * this.s, h = (m[3] - m[1]) * this.s, text = shortLabel(room.label), self = this;
    if (!text) return;
    var size = Math.min(fitSize(text, w, 11, 8), Math.max(8, h * 0.5));
    var per = Math.max(1, Math.floor(w * 0.95 / size)), lines = [];
    for (var i = 0; i < text.length && lines.length < 3; i += per) lines.push(text.slice(i, i + per));
    var tw = Math.min(text.length, per) * size, th = lines.length * size * 1.15;
    var tries = [ry, ry - 0.12, ry + 0.12, ry - 0.24, ry + 0.24], pick = ry;
    for (var k = 0; k < tries.length; k++) {
      var cy = m[1] + (m[3] - m[1]) * tries[k], x0 = (m[0] + m[2]) / 2 - tw / 2 / this.s, x1 = (m[0] + m[2]) / 2 + tw / 2 / this.s;
      var y0 = cy - th / 2 / this.s, y1 = cy + th / 2 / this.s;
      var hit = (this.cols || []).some(function (c) { return c[0] < x1 && c[2] > x0 && c[1] < y1 && c[3] > y0; });
      if (!hit && y0 >= m[1] && y1 <= m[3]) { pick = tries[k]; break; }
    }
    this.label((m[0] + m[2]) / 2, m[1] + (m[3] - m[1]) * pick, lines.join("\n"), { s: size });
  };

  // 部屋の中の記号。知らない symbol は何も描かない。
  PlanDraw.prototype.symbol = function (room) {
    var m = room.mm, x0 = m[0], y0 = m[1], x1 = m[2], y1 = m[3], kind = room.symbol;
    var cx = (x0 + x1) / 2, w = x1 - x0, h = y1 - y0, i, s = this.s, self = this;
    var small = { s: 6.5, c: DIM };
    if (kind === "cubicle") {
      this.boxAvoid(room, x0 + w * 0.15, y1 - h * 0.34, x1 - w * 0.15, y1 - h * 0.1, { w: 0.8 });
      this.caption(room, cx, y1 - h * 0.22, "キュービクル", small);
    } else if (kind === "transformer") {
      this.boxAvoid(room, x0 + w * 0.22, y1 - h * 0.34, x1 - w * 0.22, y1 - h * 0.1, { w: 0.8 });
      this.caption(room, cx, y1 - h * 0.22, "？", { s: 11, b: true });
    } else if (kind === "pump" || kind === "pump_stand") {
      var r = Math.min(w, h) * 0.07;
      [-1.7, 1.7].forEach(function (k) { var p = self.px(cx + k * r, y1 - h * 0.22); self.pen.circle(p[0], p[1], r * s, { w: 0.8 }); self.pen.line(p[0] - r * s * 0.6, p[1], p[0] + r * s * 0.6, p[1], { w: 0.5 }); });
      this.boxAvoid(room, x0 + w * 0.08, y1 - h * 0.34, x0 + w * 0.22, y1 - h * 0.1, { w: 0.8 });
      if (kind === "pump_stand") this.box(x0 + w * 0.05, y1 - h * 0.38, x1 - w * 0.05, y1 - h * 0.11, { w: 0.5, d: "3 2" });
      this.caption(room, cx, y1 - h * 0.44, kind === "pump" ? "ポンプ・制御盤（壁掛け）" : "ポンプ・制御盤（架台）", small);
    } else if (kind === "panel_stand") {
      this.boxAvoid(room, x0 + w * 0.15, y1 - h * 0.34, x1 - w * 0.15, y1 - h * 0.14, { w: 0.8 });
      this.box(x0 + w * 0.1, y1 - h * 0.38, x1 - w * 0.1, y1 - h * 0.11, { w: 0.5, d: "3 2" });
      this.caption(room, cx, y1 - h * 0.24, "主開閉器盤（架台）", small);
    } else if (kind === "water_tank") {
      this.box(x0 + w * 0.2, y1 - h * 0.42, x1 - w * 0.2, y1 - h * 0.12, { w: 0.8 });
      this.box(x0 + w * 0.24, y1 - h * 0.39, x1 - w * 0.24, y1 - h * 0.15, { w: 0.4 });
      this.caption(room, cx, y1 - h * 0.27, "受水槽", small);
    } else if (kind === "generator") {
      this.boxAvoid(room, x0 + w * 0.15, y1 - h * 0.32, x1 - w * 0.15, y1 - h * 0.08, { w: 0.8 });
      this.caption(room, cx, y1 - h * 0.2, "発電機", small);
    } else if (kind === "pit" || kind === "parking") {
      var bays = Math.max(3, Math.floor(w / 2400)), bw = (w - 600) / bays;
      for (i = 0; i < bays; i++) this.box(x0 + 300 + i * bw + 150, y0 + h * 0.5, x0 + 300 + (i + 1) * bw - 150, y1 - 300, kind === "pit" ? { w: 0.5, d: "3 2" } : { w: 0.5 });
    } else if (kind === "parking_flat") {
      var nb = Math.max(1, Math.floor(w / 2500));
      for (i = 1; i < nb; i++) this.line(x0 + i * w / nb, y0 + h * 0.15, x0 + i * w / nb, y1 - 150, { w: 0.5 });
    } else if (kind === "bike") {
      for (i = 1; i < Math.floor(w / 900); i++) this.line(x0 + i * 900, y1 - h * 0.34, x0 + i * 900, y1 - 150, { w: 0.4 });
    } else if (kind === "slope") {
      for (i = 1; i < 8; i++) this.line(x0 + 200, y0 + h * i / 8, x1 - 200, y0 + h * i / 8, { w: 0.4, c: DIM });
      var a1 = this.px(cx + w * 0.3, y0 + h * 0.16), a2 = this.px(cx + w * 0.3, y1 - h * 0.16);
      this.pen.arrow(a1[0], a1[1], a2[0], a2[1], { w: 0.8, h: 6 });
      this.label(cx - w * 0.14, y1 - h * 0.22, "勾配 1/6 DN", small);
    } else if (kind === "ev" || kind === "ev_bank") {
      var cars = kind === "ev_bank" ? 2 : 1;
      for (i = 0; i < cars; i++) {
        var ew = w / cars, ex = x0 + i * ew, ch = Math.min(h * 0.68, ew);
        this.box(ex + 250, y0 + 250, ex + ew - 250, y0 + ch, { w: 0.7 });
        this.line(ex + 250, y0 + 250, ex + ew - 250, y0 + ch, { w: 0.5 });
        this.line(ex + ew - 250, y0 + 250, ex + 250, y0 + ch, { w: 0.5 });
      }
    } else if (kind === "stair") {
      var landing = y0 + h * 0.2, steps = Math.max(2, Math.floor((y1 - landing) / 300));
      this.line(cx, landing, cx, y1 - 200, { w: 0.5 });
      for (i = 0; i < steps; i++) { var ty = landing + i * (y1 - 200 - landing) / steps; this.line(x0 + 150, ty, x1 - 150, ty, { w: 0.5 }); }
      var u1 = this.px((x0 + cx) / 2, y1 - 500), u2 = this.px((x0 + cx) / 2, landing + 200);
      this.pen.arrow(u1[0], u1[1], u2[0], u2[1], { w: 0.7, h: 4 });
      this.label((cx + x1) / 2, y1 - 500, "DN", { s: 5.5 });
      this.label(cx, y1 - 230, "UP " + steps + "段", { s: 5.5 });
    } else if (kind === "eps" || kind === "ps" || kind === "mb") {
      this.box(x0 + 150, y0 + 150, x1 - 150, y1 - 150, { w: 0.6 });
      this.label(cx, (y0 + y1) / 2, kind.toUpperCase(), { s: 6.5 });
    } else if (kind === "garden") {
      var rr = Math.min(w, h) * 0.2, k = 0;
      for (var gx = x0 + rr * 1.4; gx < x1 - rr; gx += rr * 2.6, k++) {
        var gp = this.px(gx, y0 + h * (k % 2 ? 0.36 : 0.62));
        this.pen.circle(gp[0], gp[1], rr * s, { w: 0.5, c: "#666" });
        this.pen.circle(gp[0], gp[1], rr * s * 0.55, { w: 0.4, c: "#666", d: "2 2" });
      }
    } else if (kind === "entrance_steps") {
      var count = 3 + (h > 1800 ? 1 : 0);
      for (i = 0; i <= count; i++) this.line(x0 + 100, y0 + h * (0.25 + 0.5 * i / count), x1 - 100, y0 + h * (0.25 + 0.5 * i / count), { w: 0.5 });
      var s1 = this.px(cx, y1 - h * 0.15), s2 = this.px(cx, y0 + h * 0.15);
      this.pen.arrow(s1[0], s1[1], s2[0], s2[1], { w: 0.7, h: 4 });
      this.label(cx + w * 0.3, (y0 + y1) / 2, "UP " + count + "段", { s: 6 });
    }
  };
  // 住戸：MB の箱（扉と窓は壁の建具として抜いてある）。
  PlanDraw.prototype.unit = function (room) {
    var m = room.mm, w = m[2] - m[0];
    this.box(m[0] + w * 0.12, m[1] + 100, m[0] + w * 0.42, m[1] + 700, { w: 0.6 });
    this.label(m[0] + w * 0.27, m[1] + 400, "MB", { s: 6 });
  };
  PlanDraw.prototype.balconies = function () {
    var units = this.rooms.filter(function (r) { return r.unit; }).map(function (r) { return r.mm; }), self = this;
    if (!units.length) return;
    var bottom = Math.max.apply(null, units.map(function (u) { return u[3]; }));
    var end = Math.min(bottom + 1500, this.H);
    if (end - bottom < 400) return;
    units.forEach(function (u) { self.box(u[0] + 80, bottom, u[2] - 80, end, { w: 0.6 }); self.label((u[0] + u[2]) / 2, (bottom + end) / 2, "バルコニー", { s: 6.5, c: DIM }); });
    this.box(units[0][0] + 300, bottom + 300, units[0][0] + 900, bottom + 900, { w: 0.6 });
  };

  // 図の外：道路と歩道の帯、敷地境界、出入口の印。
  PlanDraw.prototype.road = function (mark, entranceX) {
    var W = this.W, H = this.H, pen = this.pen, s = this.s, margin = 1000;
    var left = this.px(-margin, 0)[0], right = this.px(W + margin, 0)[0], top = this.px(0, 0)[1];
    var siteBottom = this.px(0, H + margin)[1], walk = siteBottom + 2500 * s;
    pen.line(left, siteBottom, right, siteBottom, { w: 1.1, d: "9 3 1.5 3" });
    pen.line(left - 24, siteBottom + 1.6, right + 8, siteBottom + 1.6, { c: "#555", w: 0.6 });
    pen.line(left - 24, walk, right + 8, walk, { c: "#555", w: 0.8 });
    var lx = this.px(W * 0.72, 0)[0];
    if (mark.slope) {
      pen.text(lx, (siteBottom + walk) / 2, mark.label || "敷地内通路", { s: 8, c: "#555" });
      pen.text(right + 6, top + 8, "丘の側（高い）", { s: 7.5, a: "start", b: true, c: "#555" });
      pen.text(right + 12, walk, "前の道路（低い）", { s: 7.5, a: "start", b: true, c: "#555" });
      pen.arrow(right + 16, top, right + 16, this.px(0, H)[1], { c: "#555", w: 0.8, h: 6 });
    } else {
      pen.text(lx, (siteBottom + walk) / 2, "歩道", { s: 8, b: true, c: "#555" });
      pen.text(this.px(W * 0.9, 0)[0], walk + 10, "前の道路", { s: 8, b: true, c: "#555" });
    }
    pen.poly([[entranceX, siteBottom - 6], [entranceX - 5, siteBottom + 3], [entranceX + 5, siteBottom + 3]], { f: INK, c: "none", close: true });
    pen.text(entranceX, siteBottom + 11, "出入口", { s: 7, c: DIM });
  };
  PlanDraw.prototype.mark = function (mark) {
    var pen = this.pen, W = this.W, H = this.H;
    var p = this.px((mark.x || 0) * W, (mark.y || 0) * H), x = p[0], y = p[1];
    var q = this.px((mark.x2 || 0) * W, (mark.y2 || 0) * H);
    var dim = { s: 7.5, a: "start", c: DIM };
    if (mark.kind === "conduit") {
      pen.line(x, y, q[0], q[1], { c: FEED, w: 1.3, d: "5 3" });
      var top = Math.min(y, q[1]), bottom = Math.max(y, q[1]);
      var ly = this.siteY != null && this.siteY - top >= 12 && this.siteY < bottom ? (top + this.siteY) / 2 : (top + bottom) / 2;
      pen.text(x + 6, ly, mark.label || "引込管路", { s: 7.5, a: "start", c: DIM, halo: true });
    } else if (mark.kind === "hh") {
      pen.rect(x - 9, y - 9, 18, 18, { c: FEED, w: 1.1 });
      pen.rect(x - 6, y - 6, 12, 12, { c: FEED, w: 0.6 });
      pen.text(x + 14, y, mark.label || "HH", { s: 7.5, a: "start", c: DIM, b: true });
    } else if (mark.kind === "conduit_hole") {
      pen.circle(x, y, 5, { c: FEED, w: 1.1 });
      pen.circle(x, y, 1.5, { f: FEED, c: "none" });
      pen.text(x + 9, y + 11, mark.label || "壁の穴", { s: 7.5, a: "start", c: DIM, b: true });
    } else if (mark.kind === "basin") {
      pen.rect(x - 7, y - 7, 14, 14, { w: 1.1 });
      pen.line(x - 7, y - 7, x + 7, y + 7, { w: 0.6 }); pen.line(x + 7, y - 7, x - 7, y + 7, { w: 0.6 });
      pen.text(x, y + 15, mark.label || "雨水ます", { s: 7.5, c: DIM });
    } else if (mark.kind === "pole") {
      pen.circle(x, y, 4, { w: 0.9 }); pen.circle(x, y, 1.2, { f: INK, c: "none" });
      pen.line(x, y, q[0], q[1], { c: FEED, w: 1.1, d: "6 2 1 2" });
      pen.text(x - 7, y + 2, mark.label || "電柱", { s: 7.5, a: "end", c: DIM });
    } else if (mark.kind === "door_low") {
      for (var i = -1; i <= 1; i++) pen.rect(x + 12 + i * 7, y - 2.2, 5, 4.4, { w: 0.6 });
      pen.text(x, y + 12, mark.label || "出入口・足元換気口", { s: 7.5, c: DIM, b: true });
    }
  };

  function plan(sample, viewIndex, opts) {
    opts = opts || {};
    var view = ((sample && sample.views) || [])[viewIndex || 0] || { name: "", rooms: [], marks: [] };
    var rooms = (view.rooms || []).filter(function (r) { return r && r.mm && r.mm.length === 4; });
    var marks = view.marks || [];
    var W = 0, H = 0;
    rooms.forEach(function (r) { W = Math.max(W, r.mm[2]); H = Math.max(H, r.mm[3]); });
    if (!W || !H) { W = W || 10000; H = H || 10000; }
    var compact = !!opts.compact, wPx = 700;
    var ML = compact ? 36 : 74, MT = compact ? 40 : 72, MR = 18;
    var s = (wPx - ML - MR) / W;
    var hasRoad = marks.some(function (m) { return m.kind === "road"; });
    var belowMm = 0;
    marks.forEach(function (m) { belowMm = Math.max(belowMm, ((m.y || 0) - 1) * H, ((m.y2 || 0) - 1) * H); });
    if (hasRoad) belowMm = Math.max(belowMm, 1000 + 2500 + 1500);
    else if (belowMm > 0 || marks.some(function (m) { return m.y === 1; })) belowMm += 1100;
    var MB = belowMm * s + 34;
    var h = Math.round(MT + H * s + MB);
    var px = function (x, y) { return [ML + x * s, MT + y * s]; };
    var d = new PlanDraw(rooms, [W, H], px, s), pen = d.pen;
    var id = ++uid, soilFill = pen.pattern("cadSoil" + id, "soil"), waterFill = pen.pattern("cadWater" + id, "water");
    var xs = gridLines(rooms, W, 0, 8), ys = gridLines(rooms, H, 1, 5);
    var left = ML, top = MT, right = ML + W * s, bottom = MT + H * s;
    var boxes = {}, outMarks = [];

    // 部屋の下地（種類の薄い色、土の斜線、水の横線）。rect は呼ぶ側が色やピンを重ねる目印。
    rooms.forEach(function (r) {
      var m = r.mm, p = px(m[0], m[1]), kind = KIND[r.key];
      var fill = r.hatch ? (r.key === "tank" ? waterFill : soilFill) : (kind ? FILL[kind] : (r.outdoor || OPEN_AIR[r.key] ? "none" : WHITE));
      boxes[r.key] = { x: n(p[0]), y: n(p[1]), w: n((m[2] - m[0]) * s), h: n((m[3] - m[1]) * s) };
      pen.rect(p[0], p[1], (m[2] - m[0]) * s, (m[3] - m[1]) * s, { f: fill, c: "none", cls: "cad-room", room: esc(r.key) });
    });
    // 通り芯（細い一点鎖線）
    xs.forEach(function (x) { var v = px(x, 0)[0]; pen.line(v, top - (compact ? 13 : 53), v, bottom + 6, { c: AXIS, w: 0.5, d: "10 2.5 1.5 2.5" }); });
    ys.forEach(function (y) { var v = px(0, y)[1]; pen.line(left - (compact ? 13 : 53), v, right + 6, v, { c: AXIS, w: 0.5, d: "10 2.5 1.5 2.5" }); });
    // 部屋の中身と名前
    var openings = openingsOf(rooms);
    d.columns(xs, ys);
    rooms.forEach(function (r) {
      var m = r.mm;
      if (r.outdoor) d.line(m[0], m[1] + 100, m[2], m[1] + 100, { w: 0.5 });
      d.symbol(r);
      if (r.unit) d.unit(r);
      var ry = 0.5, sym = r.symbol;
      if (MACHINE[sym]) ry = 0.3; else if (sym === "pit" || sym === "parking" || sym === "bike" || sym === "slope") ry = 0.26;
      else if (sym === "ev" || sym === "ev_bank") ry = 0.8; else if (sym === "stair") ry = 0.1; else if (sym === "entrance_steps") ry = 0.12;
      if (sym === "eps" || sym === "ps" || sym === "mb") return;
      d.roomLabel(r, ry);
    });
    d.walls(openings);
    d.balconies();
    // 外壁の建具は、呼ぶ側が止水板を重ねられるよう位置を返す。
    openings.forEach(function (o) {
      var limit = o.axis === "h" ? H : W;
      if (o.pos !== 0 && o.pos !== limit) return;
      var p = o.axis === "h" ? px(o.at - o.w / 2, o.pos) : px(o.pos, o.at - o.w / 2);
      outMarks.push({ kind: "opening", side: o.side, x: n(p[0]), y: n(p[1]), w: n(o.w * s), openingKind: o.kind, room: o.room.key });
    });
    // 図の外の印。道路の帯は出入口（下辺の引き戸）の位置に印を置く。
    var entrance = openings.filter(function (o) { return o.side === "bottom" && o.pos === H && o.kind === "sliding"; })[0];
    d.siteY = hasRoad ? px(0, H + 1000)[1] : null;
    marks.forEach(function (m) {
      if (m.kind === "road") d.road(m, entrance ? px(entrance.at, 0)[0] : px(W * 0.46, 0)[0]);
      else d.mark(m);
      var e = m.kind === "road" ? { kind: "road", y: n(px(0, H + 1000)[1]) } : { kind: m.kind, x: n(px((m.x || 0) * W, 0)[0]), y: n(px(0, (m.y || 0) * H)[1]) };
      if (m.kind !== "road" && m.x2 !== undefined) { e.x2 = n(px(m.x2 * W, 0)[0]); e.y2 = n(px(0, (m.y2 || 0) * H)[1]); }
      outMarks.push(e);
    });
    // 通り芯の丸と寸法線（2 段：通りの間と全体）
    var bx = compact ? 22 : 62, t1 = 24, t2 = 40;
    xs.forEach(function (x, i) { pen.bubble(px(x, 0)[0], top - bx, "X" + (i + 1)); });
    ys.forEach(function (y, i) { pen.bubble(left - bx, px(0, y)[1], "Y" + (i + 1)); });
    if (!compact) {
      pen.line(left, top - t1, right, top - t1, { c: DIM, w: 0.5 }); pen.line(left, top - t2, right, top - t2, { c: DIM, w: 0.5 });
      xs.forEach(function (x, i) {
        var v = px(x, 0)[0];
        pen.tick(v, top - t1);
        if (i < xs.length - 1) pen.text((v + px(xs[i + 1], 0)[0]) / 2, top - t1 - 5, fmt(xs[i + 1] - x), { s: 7, c: DIM });
      });
      pen.tick(left, top - t2); pen.tick(right, top - t2);
      pen.text((left + right) / 2, top - t2 - 5, fmt(W), { s: 7.5, c: DIM });
      pen.line(left - t1, top, left - t1, bottom, { c: DIM, w: 0.5 }); pen.line(left - t2, top, left - t2, bottom, { c: DIM, w: 0.5 });
      ys.forEach(function (y, i) {
        var v = px(0, y)[1];
        pen.tick(left - t1, v);
        if (i < ys.length - 1) pen.text(left - t1 - 5, (v + px(0, ys[i + 1])[1]) / 2, fmt(ys[i + 1] - y), { s: 7, c: DIM, r: -90 });
      });
      pen.tick(left - t2, top); pen.tick(left - t2, bottom);
      pen.text(left - t2 - 5, (top + bottom) / 2, fmt(H), { s: 7.5, c: DIM, r: -90 });
    }
    pen.north(wPx / 2 + 150, h - 15);
    pen.title(wPx / 2, h - 12, (opts.title || view.name || "平面図") + "　S=1/100");
    return { svg: pen.svg(), w: wPx, h: h, rooms: boxes, marks: outMarks, px: px };
  }

  // ----------------------------------------------------------------- 断面図

  var SEC_W = { elec: 4400, tr: 3600, panel_room: 3600, pump: 4200, water_tank: 4200, ev: 2400, stair: 3000, park: 5400, gen: 3600, tank: 4200, hall: 3600 };
  var SEC_KIND = { elec: "power", tr: "power", panel_room: "power", gen: "power", pump: "water", water_tank: "water", tank: "water", ev: "lift", stair: "lift", park: "car" };
  var MOUNT = { "床置き": 300, "壁掛け": 1000, "架台の上": 600 };

  function section(spec) {
    spec = spec || {};
    var floors = Math.min(80, Math.max(1, Math.floor(Number(spec.floors) || 1)));
    var basement = spec.basement ? 1 : 0, feed = !!spec.undergroundFeed, hasSlope = !!spec.hasSlope;
    var pit = !!(spec.pit || basement);
    var mount = MOUNT[spec.panelMount], mountKnown = mount !== undefined;
    if (!mountKnown) mount = 600;
    var list = (spec.rooms || []).filter(function (r) { return r && r.key; }).map(function (r) { return { key: r.key, label: r.label || r.key }; });
    if (!basement) list.unshift({ key: "hall", label: "エントランス" });
    if (!list.length) list.push({ key: "hall", label: "エントランス" });

    // mm の座標。x は道路の左端が 0、z は GL が 0 で上が正。
    var ROAD = 4500, BX0 = 8000, cursor = BX0 + OUTER, rooms = [];
    list.forEach(function (r) { var wmm = SEC_W[r.key] || 3600; rooms.push({ key: r.key, label: r.label, x0: cursor, x1: cursor + wmm }); cursor += wmm + INNER; });
    var BX1 = cursor - INNER + OUTER;
    var slopeTop = BX1 + 6000, rightMm = hasSlope ? slopeTop + 2200 : BX1 + 1500;
    var LOW = basement ? -4500 : 500, F1 = 500, F2 = F1 + 3600;   // 一番低い床、1FL、2FL（ここより上は縮める）
    var PIT = pit ? LOW - 1500 : LOW, bottomMm = Math.min(PIT, 0) - 900;
    var ceiling = basement ? F1 - OUTER : F2 - INNER;             // 機械室の天井（上の床の下面）

    // 縮尺。横と機械室の階は同じ縮尺、2FL より上の階は収まるよう縮める。
    var wPx = 700, ML = 66, MR = 10, TOP = 26, BOT = 36;
    var sx = (wPx - ML - MR) / rightMm;
    var zonePx = (F2 - bottomMm) * sx, parapetPx = 600 * sx;
    var shown = [];                                                // 2FL より上の、描く階
    for (var k = 2; k <= floors; k++) if (floors <= 12 || k <= 8 || k >= floors - 2) shown.push(k);
    var brk = floors > 12 ? 1 : 0, nUp = shown.length;
    var fuTrue = 2900 * sx;
    var hNat = TOP + parapetPx + (nUp + brk) * fuTrue + zonePx + BOT;
    // 機械室の階（盤の高さが読める所）に高さの4割以上を使い、上の階は縮める（画面で見るのは足元のため）。
    var h = Math.min(0.95 * wPx, hNat);
    if (zonePx / h < 0.42) h = zonePx / 0.42;
    var fu = nUp ? Math.min(fuTrue, Math.max(12, (h - TOP - BOT - zonePx - parapetPx) / (nUp + brk))) : fuTrue;
    h = Math.round(TOP + parapetPx + (nUp + brk) * fu + zonePx + BOT);
    var squeezed = fu < fuTrue - 0.5;
    var yF2 = TOP + parapetPx + (nUp + brk) * fu;
    var X = function (mm) { return ML + mm * sx; };
    var Z = function (mm) { return yF2 + (F2 - mm) * sx; };        // 機械室の階（F2 以下）
    var floorY = [];                                                 // 描く階の y（上の階は縮めた位置）
    shown.forEach(function (fl, i) { floorY.push({ k: fl, y: yF2 - i * fu - (brk && fl > 8 ? fu : 0) }); });
    var yRoof = TOP + parapetPx;
    var pen = new Pen(), id = ++uid, soilFill = pen.pattern("cadSoil" + id, "soil"), waterFill = pen.pattern("cadWater" + id, "water");
    var out = { rooms: {}, levels: {}, routes: [], floorsY: [] };
    var byKey = {};
    rooms.forEach(function (r) { byKey[r.key] = r; });

    // 土と地盤
    var groundR = hasSlope ? [[X(BX1), Z(LOW + 300)], [X(slopeTop), Z(150)], [X(rightMm), Z(150)], [X(rightMm), Z(bottomMm)], [X(BX1), Z(bottomMm)]]
      : [[X(BX1), Z(150)], [X(rightMm), Z(150)], [X(rightMm), Z(bottomMm)], [X(BX1), Z(bottomMm)]];
    pen.poly([[X(0), Z(0)], [X(ROAD), Z(0)], [X(ROAD), Z(150)], [X(BX0), Z(150)], [X(BX0), Z(bottomMm)], [X(0), Z(bottomMm)]], { f: soilFill, c: "none", close: true });
    pen.poly(groundR, { f: soilFill, c: "none", close: true });
    pen.rect(X(BX0), Z(LOW - OUTER), X(BX1) - X(BX0), Z(bottomMm) - Z(LOW - OUTER), { f: soilFill, c: "none" });
    pen.poly([[X(0), Z(0)], [X(ROAD), Z(0)], [X(ROAD), Z(150)], [X(BX0), Z(150)]], { c: "#555", w: 1 });
    pen.poly(groundR.slice(0, hasSlope ? 3 : 2), { c: "#555", w: 1 });
    pen.text(X(ROAD / 2), Z(0) - 9, "前の道路", { s: 8, b: true, c: "#555" });
    pen.text(X(ROAD + 1700), Z(150) - 8, "歩道", { s: 7.5, c: "#555" });
    pen.text(X(ROAD * 0.25), Z(0) + 8, "GL±0", { s: 6.5, c: DIM });
    if (hasSlope) {
      pen.text(X(slopeTop + 1100), Z(150) - 9, "車路の入口", { s: 7.5, b: true, c: "#555" });
      pen.text((X(BX1) + X(slopeTop)) / 2 + 10, (Z(LOW + 300) + Z(150)) / 2 + 12, "車路スロープ", { s: 7.5, a: "start", c: "#555" });
    }

    // 機械室の階：部屋の薄い色、床と天井、壁
    rooms.forEach(function (r) {
      var kind = SEC_KIND[r.key];
      var box = { x: n(X(r.x0)), y: n(Z(ceiling)), w: n((r.x1 - r.x0) * sx), h: n(Z(LOW) - Z(ceiling)) };
      out.rooms[r.key] = box;
      pen.rect(box.x, box.y, box.w, box.h, { f: kind ? FILL[kind] : WHITE, c: "none", cls: "cad-room", room: esc(r.key) });
    });
    if (pit) {
      ["ev", "park"].forEach(function (key) {
        var r = byKey[key];
        if (!r) return;
        pen.rect(X(r.x0), Z(LOW), (r.x1 - r.x0) * sx, Z(PIT) - Z(LOW), { f: WHITE, c: "none" });
        pen.rect(X(r.x0 - INNER), Z(PIT), (r.x1 - r.x0 + INNER * 2) * sx, OUTER * sx, { f: INK, c: "none" });
        pen.text(X((r.x0 + r.x1) / 2), Z(PIT + 600), "ピット", { s: 6, c: DIM });
      });
    }
    pen.rect(X(BX0), Z(LOW), X(BX1) - X(BX0), OUTER * sx, { f: INK, c: "none" });              // 一番低い床
    if (basement) pen.rect(X(BX0), Z(F1), X(BX1) - X(BX0), OUTER * sx, { f: INK, c: "none" }); // 1 階の床
    rooms.forEach(function (r, i) { if (i) pen.rect(X(r.x0 - INNER), Z(ceiling), INNER * sx, Z(LOW) - Z(ceiling), { f: INK, c: "none" }); });
    // 外壁（左は玄関、右は車路の所を抜く）
    var doorTop = F1 + 2100;
    pen.rect(X(BX0), yRoof - parapetPx, OUTER * sx, Z(doorTop) - yRoof + parapetPx, { f: INK, c: "none" });
    pen.rect(X(BX0), Z(F1), OUTER * sx, Z(LOW - OUTER) - Z(F1), { f: INK, c: "none" });
    if (hasSlope) {
      pen.rect(X(BX1 - OUTER), yRoof - parapetPx, OUTER * sx, Z(LOW + 2400) - yRoof + parapetPx, { f: INK, c: "none" });
      pen.rect(X(BX1 - OUTER), Z(LOW), OUTER * sx, Z(LOW - OUTER) - Z(LOW), { f: INK, c: "none" });
    } else pen.rect(X(BX1 - OUTER), yRoof - parapetPx, OUTER * sx, Z(LOW - OUTER) - yRoof + parapetPx, { f: INK, c: "none" });
    // 玄関の段（歩道 +150 から 1FL +500 へ 3 段）と扉
    var steps = 3, sx0 = BX0 - 1500;
    var stair = [[X(sx0), Z(150)]];
    for (var si = 1; si <= steps; si++) { var zz = 150 + (F1 - 150) * si / steps; stair.push([X(sx0 + 1500 * (si - 1) / steps), Z(zz)]); stair.push([X(sx0 + 1500 * si / steps), Z(zz)]); }
    pen.poly(stair, { w: 0.9 });
    pen.line(X(BX0 + OUTER / 2), Z(F1), X(BX0 + OUTER / 2), Z(doorTop), { w: 1 });
    pen.text(X(BX0 - 700), Z(F1) + 12, "UP " + steps + "段", { s: 6, c: DIM });
    // 1 階（地下がある建物）のホール
    if (basement) {
      pen.text((X(BX0) + X(BX1)) / 2, (Z(F1) + Z(F2)) / 2, "1階　エントランスホール", { s: 8, b: true });
      pen.rect(X(BX0), Z(F2), X(BX1) - X(BX0), INNER * sx, { f: INK, c: "none" });
    } else pen.rect(X(BX0), Z(F2), X(BX1) - X(BX0), INNER * sx, { f: INK, c: "none" });

    // 上の階：床、ベランダの手すり、窓の線、階の名前
    var slab = Math.max(1.6, 150 * fu / 2900);
    floorY.forEach(function (f, i) {
      pen.rect(X(BX0), f.y, X(BX1) - X(BX0), slab, { f: INK, c: "none" });
      var yTop = i + 1 < floorY.length && !(brk && f.k === 8) ? floorY[i + 1].y : f.y - fu;
      var sill = f.y - (f.y - yTop) * 0.3, head = f.y - (f.y - yTop) * 0.72;                     // 窓（外壁を抜く）
      pen.rect(X(BX1 - OUTER), head, OUTER * sx, sill - head, { f: WHITE, c: "none" });
      pen.line(X(BX1 - OUTER / 2), head, X(BX1 - OUTER / 2), sill, { w: 0.5 });
      pen.rect(X(BX1), f.y, 1200 * sx, slab, { f: INK, c: "none" });                                     // バルコニーの床と手すり
      pen.line(X(BX1 + 1200), f.y, X(BX1 + 1200), f.y - Math.max(3, 1100 * fu / 2900), { w: 0.6 });
      pen.line(X(BX1 + 1050), f.y - Math.max(3, 1100 * fu / 2900), X(BX1 + 1200), f.y - Math.max(3, 1100 * fu / 2900), { w: 0.9 });
    });
    if (brk) {
      var yb = floorY[6].y - fu, zig = [], zx = X(BX0 - 800);
      [0, 6].forEach(function (off) { zig = []; for (var j = 0; j <= 20; j++) zig.push([zx + (X(BX1 + 1400) - zx) * j / 20, yb - fu * 0.5 - off + (j % 2 ? 2.4 : -2.4)]); pen.poly(zig, { w: 0.7 }); });
      pen.rect(zx, yb - fu * 0.5 - 5, X(BX1 + 1400) - zx, 4.5, { f: WHITE, c: "none" });
      pen.text((X(BX0) + X(BX1)) / 2, yb - fu * 0.5 - 1, "9〜" + (floors - 3) + "階は省略", { s: 6.5, c: DIM });
    }
    // 屋上とパラペット
    pen.rect(X(BX0), yRoof, X(BX1) - X(BX0), slab, { f: INK, c: "none" });
    pen.line(X(BX0), yRoof - parapetPx, X(BX0 + OUTER), yRoof - parapetPx, { w: 1 });
    pen.line(X(BX1 - OUTER), yRoof - parapetPx, X(BX1), yRoof - parapetPx, { w: 1 });

    // 階の名前の丸と階高の寸法（左）
    var levels = [{ label: basement ? "B1FL" : "1FL", y: Z(LOW), mm: LOW }];
    if (basement) levels.push({ label: "1FL", y: Z(F1), mm: F1 });
    floorY.forEach(function (f) { levels.push({ label: f.k + "FL", y: f.y, mm: F2 + (f.k - 2) * 2900 }); });
    levels.push({ label: "RFL", y: yRoof, mm: F2 + (floors - 1) * 2900 });
    var dx = 56, PITCH = 18;
    pen.line(dx, Z(LOW), dx, yRoof, { c: DIM, w: 0.5 });
    // 名前を出す階：1FL・B1FL・2FL・RFL・最上階を先に置き、置いた名前と 18 px 未満の階は飛ばす（線は全部残す）
    var rank = { "1FL": 0, "B1FL": 1, "2FL": 2, "RFL": 3 };
    rank[floors + "FL"] = 4;
    var order = levels.map(function (lv, i) { return i; }).sort(function (a, b) {
      var ra = rank[levels[a].label] !== undefined ? rank[levels[a].label] : 9, rb = rank[levels[b].label] !== undefined ? rank[levels[b].label] : 9;
      return ra - rb || a - b;
    });
    var placed = [], named = {};
    order.forEach(function (i) {
      if (placed.every(function (y) { return Math.abs(y - levels[i].y) >= PITCH; })) { placed.push(levels[i].y); named[i] = true; }
    });
    levels.forEach(function (lv, i) {
      out.floorsY.push({ label: lv.label, y: n(lv.y) });
      pen.tick(dx, lv.y);
      if (!named[i]) return;
      pen.bubble(18, lv.y, "Z" + (i + 1), 8.5);
      pen.text(28, lv.y - 5, lv.label, { s: 5.5, a: "start", c: DIM });
      pen.line(26.5, lv.y, X(BX0), lv.y, { c: AXIS, w: 0.5, d: "6 2 1 2" });
    });
    // 階高：間が 18 px あれば一つずつ、縮めた同じ階高の続きは括弧で「2,900×n」
    var isBreak = function (i) { return brk && levels[i].label === (floors - 2) + "FL"; };
    for (var gi = 1; gi < levels.length;) {
      var mm = levels[gi].mm - levels[gi - 1].mm;
      if (isBreak(gi)) { gi++; continue; }
      if (levels[gi - 1].y - levels[gi].y >= PITCH) { pen.text(dx - 4, (levels[gi - 1].y + levels[gi].y) / 2, fmt(mm), { s: 6.5, c: DIM, r: -90 }); gi++; continue; }
      var gj = gi;
      while (gj + 1 < levels.length && !isBreak(gj + 1) && levels[gj + 1].mm - levels[gj].mm === mm && levels[gj].y - levels[gj + 1].y < PITCH) gj++;
      var yBot = levels[gi - 1].y, yTop = levels[gj].y, count = gj - gi + 1;
      pen.line(dx - 9, yBot, dx - 9, yTop, { c: DIM, w: 0.5 }); pen.line(dx - 9, yBot, dx - 5, yBot, { c: DIM, w: 0.5 }); pen.line(dx - 9, yTop, dx - 5, yTop, { c: DIM, w: 0.5 });
      pen.text(dx - 13, (yBot + yTop) / 2, fmt(mm) + (count > 1 ? "×" + count : ""), { s: 6.5, c: DIM, r: -90 });
      gi = gj + 1;
    }

    // 機械室の中身
    var fitText = function (r, text, zz, o) { pen.text(X((r.x0 + r.x1) / 2), Z(zz), text, Object.assign({ s: fitSize(text, (r.x1 - r.x0) * sx, 8, 6), c: DIM }, o || {})); };
    rooms.forEach(function (r) {
      var x0 = r.x0, x1 = r.x1, cx = (x0 + x1) / 2, key = r.key;
      fitText(r, shortLabel(r.label), ceiling - 500, { b: true, c: INK, s: fitSize(shortLabel(r.label), (x1 - x0) * sx, 9, 6.5) });
      if (key === "elec") {
        pen.rect(X(x0 + 600), Z(LOW + 2300), (x1 - x0 - 1200) * sx, 1800 * sx, { w: 0.9 });
        pen.line(X(x0 + 800), Z(LOW), X(x0 + 800), Z(LOW + 500), { w: 0.9 }); pen.line(X(x1 - 800), Z(LOW), X(x1 - 800), Z(LOW + 500), { w: 0.9 });
        fitText(r, "キュービクル", LOW + 1400);
      } else if (key === "tr") {
        pen.rect(X(x0 + 500), Z(LOW + 1800), (x1 - x0 - 1000) * sx, 1300 * sx, { w: 0.9 });
        pen.text(X(cx), Z(LOW + 1150), "？", { s: 13, b: true });
      } else if (key === "panel_room" || key === "pump") {
        var pw = key === "pump" ? 700 : 900, pxm = key === "pump" ? x1 - 1300 : cx - pw / 2;
        if (key === "pump") {
          [900, 1800].forEach(function (off) { pen.circle(X(x0 + off), Z(LOW + 350), 350 * sx, { w: 0.9 }); pen.line(X(x0 + off - 200), Z(LOW + 350), X(x0 + off + 200), Z(LOW + 350), { w: 0.5 }); });
          pen.text(X(x0 + 1350), Z(LOW + 1000), "ポンプ", { s: 6, c: DIM });
        }
        pen.rect(X(pxm), Z(LOW + mount + 1000), pw * sx, 1000 * sx, { w: 0.9, d: mountKnown ? null : "3 2" });
        if (spec.panelMount === "架台の上") { pen.line(X(pxm + 100), Z(LOW), X(pxm + 100), Z(LOW + mount), { w: 0.7 }); pen.line(X(pxm + pw - 100), Z(LOW), X(pxm + pw - 100), Z(LOW + mount), { w: 0.7 }); }
        pen.text(X(pxm + pw / 2), Z(LOW + mount + 500), mountKnown ? "盤" : "？", { s: 6.5, c: mountKnown ? DIM : INK, b: !mountKnown });
        pen.text(X(pxm + pw / 2), Z(LOW + mount + 1000) - 5, spec.panelMount || "形は未確認", { s: 5.5, c: DIM });
      } else if (key === "water_tank") {
        pen.rect(X(x0 + 400), Z(LOW + 2800), (x1 - x0 - 800) * sx, 2200 * sx, { w: 0.9, f: waterFill, c: INK });
        [x0 + 600, x1 - 600].forEach(function (lx) { pen.line(X(lx), Z(LOW), X(lx), Z(LOW + 600), { w: 0.9 }); });
        fitText(r, "受水槽", LOW + 1700, { c: INK });
      } else if (key === "gen") {
        pen.rect(X(x0 + 500), Z(LOW + 1500), (x1 - x0 - 1000) * sx, 1500 * sx, { w: 0.9 });
        fitText(r, "発電機", LOW + 750);
      } else if (key === "tank") {
        pen.rect(X(x0), Z(LOW + 2200), (x1 - x0) * sx, 2200 * sx, { f: waterFill, c: "none" });
        fitText(r, "満水線", LOW + 2400, { s: 6 });
      } else if (key === "park") {
        [LOW + 100, LOW + 1900].forEach(function (zz) { pen.line(X(x0 + 300), Z(zz), X(x1 - 300), Z(zz), { w: 0.8 }); });
        if (pit) pen.line(X(x0 + 300), Z(PIT + 300), X(x1 - 300), Z(PIT + 300), { w: 0.8 });
        fitText(r, "パレット", LOW + 1000, { s: 6 });
      } else if (key === "ev") {
        var shaftTop = yRoof - parapetPx - 2000 * sx;
        pen.line(X(x0), Z(PIT), X(x0), shaftTop, { w: 0.6 }); pen.line(X(x1), Z(PIT), X(x1), shaftTop, { w: 0.6 });
        pen.rect(X(x0), shaftTop, (x1 - x0) * sx, yRoof - shaftTop, { w: 0.9, f: WHITE, c: INK });
        pen.text(X(cx), (shaftTop + yRoof) / 2, "EV機械室", { s: 6, c: DIM });
        pen.rect(X(x0 + 300), Z(LOW + 2300), (x1 - x0 - 600) * sx, 2300 * sx, { w: 0.8 });
        pen.line(X(x0 + 300), Z(LOW + 2300), X(x1 - 300), Z(LOW), { w: 0.5 }); pen.line(X(x1 - 300), Z(LOW + 2300), X(x0 + 300), Z(LOW), { w: 0.5 });
      } else if (key === "stair") {
        var top = basement ? F1 : F2, treads = 12, pts = [[X(x0 + 200), Z(LOW)]];
        for (var t = 1; t <= treads; t++) { pts.push([X(x0 + 200 + (x1 - x0 - 400) * (t - 1) / treads), Z(LOW + (top - LOW) * t / treads)]); pts.push([X(x0 + 200 + (x1 - x0 - 400) * t / treads), Z(LOW + (top - LOW) * t / treads)]); }
        pen.poly(pts, { w: 0.7 });
      } else if (key === "hall") {
        fitText(r, "風除室", LOW + 1200, { s: 6 });
      }
    });

    // 引込（HH → 管 → 壁の穴 → 部屋の中）
    var holeZ = Math.max(-1400, LOW + 500), hhX = ROAD + 900, hhW = 1100, hhC = hhX + hhW / 2;
    if (feed) {
      pen.rect(X(hhX), Z(150), hhW * sx, 2100 * sx, { c: FEED, w: 1.2, f: WHITE });
      pen.text(X(hhC), Z(-700), spec.feedUnknown ? "HH（未確認）" : "HH", { s: 6.5, c: FEED, b: true });
      var pts = [[hhC, 150], [hhC, -1400]];
      if (holeZ !== -1400) pts.push([BX0 - 700, -1400], [BX0 - 700, holeZ]);
      pts.push([BX0 + OUTER / 2, holeZ], [BX0 + 900, holeZ], [BX0 + 900, LOW + 700]);
      for (var c = 1; c < pts.length - 2; c++) pen.line(X(pts[c][0]), Z(pts[c][1]), X(pts[c + 1][0]), Z(pts[c + 1][1]), { c: FEED, w: 1.3, d: "5 3" });
      pen.circle(X(BX0 + OUTER / 2), Z(holeZ), 3.5, { c: FEED, w: 1.1, f: WHITE });
      pen.text(X(BX0 + 500), Z(holeZ) + 8, "ケーブルを通す壁の穴", { s: 6, a: "start", c: DIM, b: true });
      out.routes.push({ key: "hole", points: pts.map(function (p) { return [n(X(p[0])), n(Z(p[1]))]; }), block: [n(X(BX0 + OUTER / 2)), n(Z(holeZ))] });
    }
    if (hasSlope) {
      out.routes.push({ key: "slope", points: [[slopeTop + 1500, 150], [slopeTop, 150], [BX1 - OUTER, LOW + 300], [BX1 - 1800, LOW + 300]].map(function (p) { return [n(X(p[0])), n(Z(p[1]))]; }), block: [n(X(slopeTop)), n(Z(150))] });
    }
    var door = [[BX0 - 2500, 150], [BX0 - 1500, 150], [BX0, F1], [BX0 + 1200, F1]];
    if (basement) { var st = byKey.stair || byKey.ev; var sxm = st ? (st.x0 + st.x1) / 2 : BX0 + 1800; door.push([sxm, F1], [sxm, LOW + 200]); }
    out.routes.push({ key: "door", points: door.map(function (p) { return [n(X(p[0])), n(Z(p[1]))]; }), block: [n(X(BX0)), n(Z(F1))] });

    // 水の位置 ①道路 ②一番低い床 +250 ③+500
    out.levels = { 1: n(Z(0)), 2: n(Z(LOW + 250)), 3: n(Z(LOW + 500)) };
    pen.title(wPx / 2, h - 12, "断面図" + (squeezed ? "　S=1/100（2階より上は縮めて描く）" : "　S=1/100"));
    return { svg: pen.svg(), w: wPx, h: h, rooms: out.rooms, levels: out.levels, routes: out.routes, floorsY: out.floorsY };
  }

  var CAD = { plan: plan, section: section, esc: esc };
  root.CAD = CAD;
  if (typeof window !== "undefined") window.CAD = CAD;
})();
