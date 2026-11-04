"use strict";

// ②建物の「時間経過で再生する」。一つの時間の軸 t（0〜3）が、水の位置①②③（App.setWater）と、
// 3D の水の高さ、断面図の重ね絵（水の面と入り道の矢印）を一緒に動かす。
// 浸かるか・止まるかは、サーバーの scenario（App.building.scenarios["<水の位置>:<対策>"] の wet / stopped）のまま見せ、ここでは計算し直さない。
// 段の間の水の高さは、断面図の基準の座標（web/samples/section_*.json。scripts/draw_plans.py が図と同じ値から書き出す）の間を混ぜるだけ。
const SectionAnim = (() => {
  const NOTE = "実際の浸水速度の予測ではなく、水が順番に入る仕組みの模式です。";
  const SVG_NS = "http://www.w3.org/2000/svg";
  // 段ごとに、時間の軸のうち水が上がっていく割合。残りは、その段に達した形のまま止める。
  const RISE = 0.7;
  const PLAY_SECONDS = 16;
  // 入り道の矢印を出し始める水の位置（続いた値）。外の水が入口に届いてから矢印を出す。
  const ROUTE_FROM = { hill: 0.15, slope: 0.85, hole: 0.85, door: 0.85, basin: 1.5 };
  const RAISED_TEXT = "付け替えた盤（高さは見積りと現地調査で決める）";
  const DRY_TEXT = "盤は浸からない";
  const PROTECTED_TEXT = "守られる（壁の穴を塞いだ）";
  const FALLBACK_NAMES ={ 1: "前の道路に達した", 2: "一番低い床に達した", 3: "盤・受電の箱の下端に達した" };

  let t = 3;
  let playing = false;
  let frame = 0;
  let last = 0;
  let syncing = false;
  let anchors = null;
  let anchorsUrl = "";
  const cache = {};
  let shownKind = "plan";
  let overlay = null;
  const bars = [];

  // t から、今の段 k、段の中で上がった割合 r、続いた水の位置 flow、画面の水の位置（①②③）を出す。
  function phase(value) {
    const k = Math.min(3, Math.floor(value) + 1);
    const r = Math.min(1, (value - (k - 1)) / RISE);
    return { k, r, flow: k - 1 + r, level: r >= 1 ? k : Math.max(1, k - 1) };
  }

  function ready() {
    return Boolean(App.building && App.building.scenarios);
  }

  function scenarioAt(level, measure) {
    return App.building.scenarios[`${level}:${measure}`];
  }

  // 盤・受電の箱の部屋などに水が入るか。水の位置③のときの scenario の wet に、その部屋の鍵があるかで決める。
  function reached(key) {
    const top = scenarioAt(3, App.measure);
    return Boolean(top && top.wet.includes(key));
  }

  function stageName(level) {
    return (anchors && anchors.stage_names && anchors.stage_names[level]) || FALLBACK_NAMES[level];
  }

  // ---- 時間の物語（2026-11-04 作り直し）----
  // 水位の①②③ではなく、住民が過ごす時間の順（大雨が近づいたとき → 当日 → 翌朝 → 数日〜1週間 → 約2か月〜本復旧）で見せる。
  // 時間の段の名前はサーバーの五段の表の列と同じ。各段の暮らしの状態は、サーバーの scenario（services と table）のまま出し、計算し直さない。
  // 当日の中だけ、水が①②③の順に上がる（phase）。翌朝は外の水が引いても地下に水が残り、数日後は水を抜いても機械は止まったまま。
  const PHASES = [
    { key: "before", name: "大雨が近づいたとき" },
    { key: "day", name: "水が来た当日" },
    { key: "morning", name: "水が引いた翌朝" },
    { key: "week", name: "数日〜1週間" },
    { key: "months", name: "約2か月〜本復旧" },
  ];
  const PHASE_LINES = {
    before: "外の道路に水がたまり始める。建物の中はまだ使える",
    day: "スロープや壁の穴から地下へ水が入り、エレベーター、続いて水と電気が止まる",
    morning: "外の道路は乾いても、地下には水が残る。水を抜くまで機械室に入れない",
    week: "水を抜いても、浸かった機械は止まったまま。点検と修理を待つ",
    months: "浸かった盤や部品が届いて付け替わるまで、止まったままのことがある",
  };
  // 住民の暮らしで何が困るか（サーバーの services の名前ごと）。判定は言わず、状態はサーバーのまま。
  const LIFE_OF = [
    [/給水/, "水・トイレ・風呂"],
    [/エレベーター/, "エレベーター（高い階は階段）"],
    [/廊下/, "廊下の照明"],
    [/各戸の電気/, "家の電気（冷蔵庫・冷房）"],
  ];
  const STATE_TEXT = { stopped: "止まる", running: "使える", unknown: "東京電力しだい" };
  const STORY_MAX = PHASES.length;
  let story = 1.99;

  function lifeName(label) {
    const found = LIFE_OF.find(([pattern]) => pattern.test(label));
    return found ? found[1] : label;
  }

  // 物語の時間（0〜5）から、段、外の水と中の水の続いた位置（0〜3）、①②③の水の位置を出す。
  function storyAt(value) {
    const idx = Math.min(STORY_MAX - 1, Math.max(0, Math.floor(value)));
    const sub = Math.min(1, Math.max(0, value - idx));
    if (idx === 0) return { idx, out: Math.min(1, sub / 0.6), inn: 0, t: 1, level: 1 };
    if (idx === 1) {
      const within = 1 + 2 * Math.min(1, sub / 0.85);
      const ph = phase(within);
      return { idx, out: ph.flow, inn: ph.flow, t: within, level: ph.level };
    }
    if (idx === 2) return { idx, out: 0, inn: 3, t: 3, level: 3 };
    return { idx, out: 0, inn: 0, t: 3, level: 3 };
  }

  // 再生のボタンとスライダー、5つの時間の札、今の段の暮らしの欄。図の窓のすぐ下に一本だけ置く。
  function makeBar(where, withLegend) {
    const box = document.createElement("div");
    box.className = "timeline-bar section-timeline story-bar";
    const row = document.createElement("div");
    row.className = "timeline-row";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timeline-play";
    const range = document.createElement("input");
    range.type = "range";
    range.min = "0";
    range.max = String(STORY_MAX * 100);
    range.step = "1";
    range.className = "timeline-range";
    range.setAttribute("aria-label", "時間の順番");
    const count = document.createElement("span");
    count.className = "timeline-count";
    row.append(button, range, count);
    const strip = document.createElement("div");
    strip.className = "timeline-strip story-strip";
    const life = document.createElement("div");
    life.className = "story-life";
    const note = document.createElement("p");
    note.className = "timeline-note";
    note.textContent = NOTE;
    box.append(row, strip, life);
    if (withLegend) box.append(legend());
    box.append(note);
    button.addEventListener("click", () => (playing ? pause() : play()));
    range.addEventListener("input", () => {
      pause();
      setStory(Number(range.value) / 100);
    });
    where(box);
    const bar = { box, button, range, strip, count, life };
    bars.push(bar);
    return bar;
  }

  function legend() {
    const row = document.createElement("p");
    row.className = "timeline-legend";
    [
      ["swatch-water", "水"],
      ["swatch-wet", "浸かる"],
      ["swatch-stopped", "止まる"],
    ].forEach(([name, text]) => {
      const swatch = document.createElement("span");
      swatch.className = `timeline-swatch ${name}`;
      const label = document.createElement("span");
      label.textContent = text;
      row.append(swatch, label);
    });
    // 破線の輪郭は二つの意味で使う。1行で言う。
    const dashed = document.createElement("span");
    dashed.className = "timeline-legend-line";
    const swatch = document.createElement("span");
    swatch.className = "timeline-swatch swatch-sealed";
    dashed.append(swatch, " 破線の輪郭：付け替える前の盤の位置／壁の穴を塞いで守られる部屋");
    row.append(dashed);
    return row;
  }

  // 段ごとの札：名前と、その段の暮らしの一言（止まる数はサーバーの scenario のまま）。
  function phaseSummary(index) {
    const measure = App.measure;
    const first = scenarioAt(1, measure);
    const top = scenarioAt(3, measure);
    const count = (scenario) => scenario.services.filter((service) => service.state === "stopped").length;
    if (index === 0) return count(first) ? `止まる ${count(first)}／${first.services.length}` : "まだ使える";
    if (index === 1) return `止まる ${count(top)}／${top.services.length}`;
    if (index === 2) return "外は乾いても、地下に水";
    if (index === 3) return `止まったまま ${count(top)}／${top.services.length}`;
    return "部品が届くまで";
  }

  // 今の段の暮らしの欄：止まるもの（大きく）、その段の目安（サーバーの五段の表の、その列の文）、人がすること（畳み）。
  function renderLife(bar, now) {
    const scenario = scenarioAt(now.level, App.measure);
    const top = scenarioAt(3, App.measure);
    const head = document.createElement("p");
    head.className = "story-head";
    const name = document.createElement("b");
    name.textContent = PHASES[now.idx].name;
    head.append(name, `　${PHASE_LINES[PHASES[now.idx].key]}`);
    const tiles = document.createElement("ul");
    tiles.className = "story-tiles";
    scenario.services.forEach((service) => {
      const item = document.createElement("li");
      item.className = `story-tile is-${service.state}`;
      const label = document.createElement("b");
      label.textContent = lifeName(service.label);
      const state = document.createElement("span");
      state.textContent = now.idx >= 4 && service.state === "stopped" ? "部品が届くまで止まる" : now.idx >= 2 && service.state === "stopped" ? "止まったまま" : STATE_TEXT[service.state] || service.state;
      item.append(label, state);
      tiles.append(item);
    });
    const notes = document.createElement("ul");
    notes.className = "story-notes";
    const people = [];
    (top.table || []).forEach((row) => {
      const cell = row.cells[now.idx];
      if (!cell || cell === "—") return;
      if (row.label === "人がすること") {
        people.push(cell);
        return;
      }
      if (now.idx === 0) return;
      const line = document.createElement("li");
      const label = document.createElement("b");
      label.textContent = `${row.label}：`;
      line.append(label, cell);
      notes.append(line);
    });
    const parts = [head, tiles];
    if (notes.childElementCount) parts.push(notes);
    if (people.length) {
      const more = document.createElement("details");
      more.className = "fold story-people";
      const summary = document.createElement("summary");
      summary.textContent = "このとき人がすること";
      const text = document.createElement("p");
      text.textContent = people.join("");
      more.append(summary, text);
      if (now.idx === 0) more.open = true;
      parts.push(more);
    }
    bar.life.replaceChildren(...parts);
  }

  function renderBars() {
    const now = storyAt(story);
    bars.forEach((bar) => {
      bar.range.value = String(Math.round(story * 100));
      bar.button.textContent = playing ? "❚❚ 一時停止" : story >= STORY_MAX - 0.01 ? "↺ 最初から見る" : "▶ 時間の順に見る";
      bar.count.textContent = "";
      if (!ready()) return;
      const key = `${now.idx}:${App.measure}:${now.level}`;
      if (bar.strip.dataset.key !== key) {
        bar.strip.dataset.key = key;
        bar.strip.replaceChildren(
          ...PHASES.map((item, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `timeline-stage story-stage${index === now.idx ? " is-current" : ""}${index < now.idx ? " is-past" : ""}`;
            const name = document.createElement("span");
            name.className = "stage-name";
            name.textContent = item.name;
            const result = document.createElement("span");
            const summary = phaseSummary(index);
            result.className = `stage-result${/止ま|地下に水|部品/.test(summary) ? " has-stop" : ""}`;
            result.textContent = summary;
            button.append(name, result);
            button.title = `${item.name}の様子を見る`;
            button.setAttribute("aria-pressed", String(index === now.idx));
            button.addEventListener("click", () => {
              pause();
              setStory(index === 1 ? 1.99 : index + 0.99);
            });
            return button;
          }),
        );
        renderLife(bar, now);
      }
    });
  }

  // ---- 断面図の重ね絵 ----

  function svg(name, attrs = {}, parent = null) {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (parent) parent.append(node);
    return node;
  }

  function lerp(a, b, f) {
    return a + (b - a) * Math.min(1, Math.max(0, f));
  }

  function insideY(flow) {
    if (flow <= 1) return null;
    const { floor_y: floor, levels } = anchors;
    return flow <= 2 ? lerp(floor, levels["2"], flow - 1) : lerp(levels["2"], levels["3"], flow - 2);
  }

  function outsideY(flow, bottom) {
    const out = anchors.outside_levels;
    if (flow <= 0) return null;
    if (flow <= 1) return lerp(bottom, out["1"], flow);
    return flow <= 2 ? lerp(out["1"], out["2"], flow - 1) : lerp(out["2"], out["3"], flow - 2);
  }

  function points(list) {
    return list.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  }

  function buildOverlay() {
    const fit = document.getElementById("plan-fit");
    if (!fit) return null;
    if (overlay) overlay.root.remove();
    const root = svg("svg", { class: "section-overlay", viewBox: `0 0 ${anchors.width} ${anchors.height}`, preserveAspectRatio: "none", "aria-hidden": "true" });
    const defs = svg("defs", {}, root);
    const marker = svg("marker", { id: "flow-head", markerWidth: 8, markerHeight: 8, refX: 5, refY: 4, orient: "auto", markerUnits: "strokeWidth" }, defs);
    svg("path", { d: "M0,0 L8,4 L0,8 z", class: "flow-head" }, marker);
    const hatch = svg("pattern", { id: "wet-hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
    svg("rect", { width: 6, height: 6, class: "wet-hatch-bg" }, hatch);
    svg("line", { x1: 0, y1: 0, x2: 0, y2: 6, class: "wet-hatch-line" }, hatch);
    const water = svg("g", { class: "ov-water" }, root);
    const outside = anchors.outside.map((part) => ({ part, node: svg("polygon", { class: "ov-outside" }, water), bottom: Math.max(...part.profile.map(([, y]) => y)) }));
    const handhole = anchors.handhole ? svg("rect", { class: "ov-inside" }, water) : null;
    const rooms = anchors.rooms.map((room) => ({ room, node: svg("rect", { class: "ov-inside" }, water), seal: svg("rect", { class: "ov-seal" }, root) }));
    const equipment = Object.entries(anchors.equipment).map(([key, shape]) => {
      const node = shape.rect
        ? svg("rect", { x: shape.rect[0], y: shape.rect[1], width: shape.rect[2], height: shape.rect[3], class: "ov-eq" }, root)
        : svg("circle", { cx: shape.circle[0], cy: shape.circle[1], r: shape.circle[2], class: "ov-eq" }, root);
      return { key, node };
    });
    const routes = anchors.routes.map((route) => ({ route, node: svg("polyline", { class: "ov-route", "marker-end": "url(#flow-head)" }, root), block: route.block ? svg("g", { class: "ov-block" }, root) : null }));
    routes.forEach(({ route, block }) => {
      if (!block) return;
      const [x, y] = route.block;
      svg("circle", { cx: x, cy: y, r: 9 }, block);
      svg("path", { d: `M${x - 5},${y - 5} L${x + 5},${y + 5} M${x + 5},${y - 5} L${x - 5},${y + 5}` }, block);
    });
    // 盤を高くするとき：元の位置は破線の輪郭にし、水面より上に描き直す。高さの数字は出さない。
    const raised = buildRaised(root);
    // 壁の穴を塞いで乾いたままの部屋に出す印。
    rooms.forEach((item) => {
      if (item.room.role !== "power") return;
      const width = item.room.x1 - item.room.x0;
      const band = anchors.floor_y - anchors.levels["3"];
      const size = Math.max(9, Math.min(15, (width * 0.92) / PROTECTED_TEXT.length, band * 0.95 || 15));
      item.badge = svg("text", { class: "ov-badge", x: (item.room.x0 + item.room.x1) / 2, y: (anchors.levels["3"] + anchors.floor_y) / 2, "font-size": size.toFixed(1) }, root);
      item.badge.textContent = PROTECTED_TEXT;
    });
    fit.append(root);
    overlay = { root, outside, handhole, rooms, equipment, routes, raised };
    return overlay;
  }

  // 付け替えた盤の位置。水の位置③の線より上で、部屋の天井（と部屋の名前）にかからない所に置く。
  // 図の上の置き場所で、付け替える高さを示すものではない。
  function raisedRect() {
    const [x, , w, h] = anchors.equipment.panel.rect;
    const water = anchors.levels["3"];
    const limit = anchors.ceiling_y + 30;
    // 部屋が低い見本（B）では、盤の箱を小さめにして、水面との間をはっきり空ける。
    const height = Math.max(8, Math.min(h, (water - limit) * 0.6));
    return [x, limit, w, height];
  }

  function buildRaised(root) {
    if (!anchors.equipment.panel || !anchors.equipment.panel.rect) return null;
    const [ox, oy, ow, oh] = anchors.equipment.panel.rect;
    const [x, y, w, h] = raisedRect();
    const group = svg("g", { class: "ov-raised" }, root);
    svg("rect", { class: "ov-raised-ghost", x: ox, y: oy, width: ow, height: oh }, group);
    const box = svg("rect", { class: "ov-raised-box", x, y, width: w, height: h }, group);
    const center = x + w / 2;
    const labelY = Math.max(anchors.floor_y + 42, 655);
    // 札は建物の下に置き、盤の右の端から細い線でつなぐ（図の文字に重ねない）。
    svg("polyline", { class: "ov-raised-leader", points: `${x + w},${y + h / 2} ${x + w + 5},${y + h / 2} ${x + w + 5},${labelY - 14}` }, group);
    const tag = svg("text", { class: "ov-tag", x: center, y: labelY, "font-size": 16 }, group);
    tag.textContent = RAISED_TEXT;
    // 「盤は浸からない」は札の下に出す（盤と水面の間には図のピンがあり、重なるため）。
    const dry = svg("text", { class: "ov-badge", x: center, y: labelY + 20, "font-size": 15 }, group);
    dry.textContent = DRY_TEXT;
    return { group, box, dry, bottom: y + h };
  }

  function drawOverlay(state) {
    if (!overlay || !anchors || !ready()) return;
    overlay.root.style.display = shownKind === "section" ? "" : "none";
    if (shownKind !== "section") return;
    // 外の水（道路・蓋の中・入り道の矢印）と中の水（部屋）を分けて描く。翌朝は外が引いても中に残る。
    const flow = state.out ?? state.flow;
    const inFlow = state.inn ?? state.flow;
    const scenario = App.scenario();
    const wet = new Set(scenario.wet);
    const stopped = new Set(scenario.stopped);
    const powerDry = !reached("hv");
    // 外の水：地面の線と水の面の間を塗る。
    overlay.outside.forEach(({ part, node, bottom }) => {
      const surface = outsideY(flow, bottom);
      if (surface === null || surface >= bottom) {
        node.setAttribute("points", "");
        return;
      }
      const profile = part.profile;
      const xs = [profile[0][0], profile[profile.length - 1][0]];
      const under = [...profile].reverse().map(([x, y]) => [x, Math.max(y, surface)]);
      node.setAttribute("points", points([[xs[0], surface], [xs[1], surface], ...under]));
    });
    // 歩道ぎわの蓋の中：外の水が上がるにつれて下からたまる。
    if (overlay.handhole) {
      const [x, y, w, h] = anchors.handhole;
      const filled = h * Math.min(1, Math.max(0, flow / 0.85));
      Object.entries({ x, y: y + h - filled, width: w, height: filled }).forEach(([key, value]) => overlay.handhole.setAttribute(key, String(value)));
    }
    // 建物の中：一番低い床の続きの部屋は、対策にかかわらず水が入る（スロープ・扉から）。
    // 盤・受電の箱の部屋は scenario で浸かるときだけ。借室の中は描かない（3D と同じ）。
    const surface = insideY(inFlow);
    overlay.rooms.forEach(({ room, node, seal }) => {
      const flooded = room.role === "floor" || (room.role === "power" && !powerDry);
      const top = surface === null || !flooded ? anchors.floor_y : surface;
      Object.entries({ x: room.x0, y: top, width: room.x1 - room.x0, height: anchors.floor_y - top }).forEach(([key, value]) => node.setAttribute(key, String(value)));
      const sealed = room.role === "power" && powerDry;
      seal.style.display = sealed ? "" : "none";
      if (sealed) Object.entries({ x: room.x0 + 1, y: anchors.ceiling_y + 1, width: room.x1 - room.x0 - 2, height: anchors.floor_y - anchors.ceiling_y - 2 }).forEach(([key, value]) => seal.setAttribute(key, String(value)));
    });
    // 設備：止まる想定は橙、浸かる想定は斜線。どちらも今の水の位置の scenario のまま。
    const raising = App.measure === "raise" && Boolean(overlay.raised);
    overlay.equipment.forEach(({ key, node }) => {
      const moved = key === "panel" && raising;
      node.classList.toggle("is-stopped", !moved && stopped.has(key));
      node.classList.toggle("is-wet", !moved && wet.has(key));
    });
    // 盤を高くする：付け替えた盤に、止まる・浸かるを scenario のまま付ける。水がその高さに届かないあいだ「盤は浸からない」。
    if (overlay.raised) {
      const { group, box, dry, bottom } = overlay.raised;
      group.style.display = raising ? "" : "none";
      box.classList.toggle("is-stopped", stopped.has("panel"));
      box.classList.toggle("is-wet", wet.has("panel"));
      dry.style.display = raising && inFlow > 1 && !wet.has("panel") && (surface === null || surface > bottom) ? "" : "none";
    }
    // 壁の穴を塞いで乾いたままの部屋に「守られる」。建物に水が来てから出す。
    overlay.rooms.forEach(({ room, badge }) => {
      if (badge) badge.style.display = room.role === "power" && powerDry && Math.max(flow, inFlow) >= 1 ? "" : "none";
    });
    // 入り道の矢印。塞いだ壁の穴は、穴の手前で止めて × を出す。スロープと扉からの道は、対策にかかわらず流す。
    overlay.routes.forEach(({ route, node, block }) => {
      const shown = flow >= (ROUTE_FROM[route.key] ?? 0.85);
      const blocked = Boolean(route.guard) && !reached(route.guard);
      let list = route.points;
      if (blocked && route.block) {
        const stop = list.findIndex(([x, y]) => x === route.block[0] && y === route.block[1]);
        list = stop > 0 ? list.slice(0, stop + 1) : list;
      }
      node.setAttribute("points", shown ? points(list) : "");
      node.classList.toggle("is-blocked", blocked);
      if (block) block.style.display = blocked ? "" : "none";
    });
  }

  async function loadAnchors(sample) {
    const png = sample && sample.plan && sample.plan.section_png;
    if (!png) return;
    const url = png.replace(/\.png$/, ".json");
    if (url === anchorsUrl && overlay) return;
    anchorsUrl = url;
    try {
      // 同じ図の座標は一度だけ読む（読み込み中に二度呼ばれても、同じ約束を待つ）。
      if (!cache[url]) {
        cache[url] = fetch(url).then((response) => {
          if (!response.ok) throw new Error(String(response.status));
          return response.json();
        });
        cache[url].catch(() => delete cache[url]);
      }
      const loaded = await cache[url];
      if (anchorsUrl !== url) return;
      anchors = loaded;
      buildOverlay();
      render();
      // 図面のビューアーが、断面図を図のある範囲（anchors.focus）に寄せられるように知らせる。
      window.dispatchEvent(new CustomEvent("section-anchors", { detail: anchors }));
    } catch (error) {
      anchors = null;
      if (overlay) overlay.root.remove();
      overlay = null;
    }
  }

  // ---- 時間の軸 ----

  function render() {
    const now = storyAt(story);
    t = now.t;
    renderBars();
    if (ready() && window.Model3D && !window.Model3D.failed && window.Model3D.setFlow) window.Model3D.setFlow(now.out, now.inn);
    drawOverlay(now);
  }

  // 物語の時間を動かす。①②③の水の位置（App.setWater）は、その段の scenario を選ぶためだけに合わせる。
  function setStory(value) {
    story = Math.min(STORY_MAX, Math.max(0, value));
    const now = storyAt(story);
    if (ready() && App.water !== now.level) {
      syncing = true;
      try {
        App.setWater(now.level);
      } finally {
        syncing = false;
      }
    }
    render();
  }

  // 前の版の呼び方（①②③の水の位置）も残す：①→大雨が近づいたとき、②③→当日のその水位。
  function setTime(value) {
    const level = Math.min(3, Math.max(0, value));
    setStory(level <= 1 ? 0.99 : 1 + ((level - 1) / 2) * 0.85);
  }

  function play() {
    if (!ready()) return;
    if (story >= STORY_MAX - 0.01) setStory(0);
    playing = true;
    last = performance.now();
    const step = (now) => {
      if (!playing) return;
      // 画面が裏に回って止まっていたときに一気に進まないよう、1回に進める量を抑える。
      const seconds = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;
      setStory(story + (seconds * STORY_MAX) / PLAY_SECONDS);
      if (story >= STORY_MAX - 0.01) {
        setStory(STORY_MAX - 0.01);
        pause();
        return;
      }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    render();
  }

  function pause() {
    if (!playing) return;
    playing = false;
    cancelAnimationFrame(frame);
    render();
  }

  // チャットや答えの組み直しで App.water が変わったら、物語の時間をその水位の当日に合わせる。
  function followApp() {
    if (syncing || !ready()) return;
    if (storyAt(story).level !== App.water) {
      playing = false;
      cancelAnimationFrame(frame);
      setTime(App.water);
      return;
    }
    // 対策を替えたときなど：段の札と暮らしの欄を作り直す。
    bars.forEach((bar) => delete bar.strip.dataset.key);
    render();
  }

  // 平面図のタブ（plan.js の showDrawing）から呼ぶ。断面図のときだけ重ね絵と断面図の上の再生を出す。
  function showDrawing(kind, sample) {
    shownKind = kind;
    loadAnchors(sample);
    render();
  }

  function init() {
    // ②は一枚のカードにまとめたので、再生のバーも一本だけ（断面図・3D・平面図のどれを見ていても同じ時間の軸）。
    // 図の窓のすぐ下に置き、図を見ながら①②③を押せるようにする。
    const viewer = document.getElementById("sim-viewer") || document.getElementById("control-caption");
    if (viewer) makeBar((box) => viewer.after(box), true);
    if (typeof App.applyScenario === "function") {
      const original = App.applyScenario;
      App.applyScenario = function applyScenarioWithTimeline(...args) {
        const result = original.apply(this, args);
        followApp();
        return result;
      };
    }
    // 手で水の位置を選んだら、再生を止める。
    document.getElementById("water-controls")?.addEventListener("change", () => pause());
    window.addEventListener("building-shown", () => {
      if (App.building) loadAnchors(App.building.sample);
      render();
    });
    window.addEventListener("model3d-ready", render);
    render();
  }

  init();

  // 確かめる用：今の時間の軸と、断面図の重ね絵の状態。
  function debug() {
    const state = phase(t);
    const read = (node) => (node ? { points: node.getAttribute("points"), y: node.getAttribute("y"), height: node.getAttribute("height"), cls: node.getAttribute("class"), shown: node.style.display !== "none" } : null);
    return {
      t,
      ...state,
      water: App.water,
      measure: App.measure,
      playing,
      anchors: anchors ? anchors.sample : null,
      shownKind,
      overlay: overlay
        ? {
            outside: overlay.outside.map(({ node }) => read(node)),
            handhole: read(overlay.handhole),
            rooms: overlay.rooms.map(({ room, node, seal }) => ({ name: room.name, water: read(node), sealed: seal.style.display !== "none" })),
            equipment: overlay.equipment.map(({ key, node }) => ({ key, cls: node.getAttribute("class") })),
            routes: overlay.routes.map(({ route, node }) => ({ key: route.key, ...read(node) })),
          }
        : null,
    };
  }

  return { setTime, play, pause, showDrawing, debug, phase, get time() { return t; } };
})();
