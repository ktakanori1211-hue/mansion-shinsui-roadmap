"use strict";

// 地図の表示だけを受け持つ。判定はしない。
const HazardMap = (() => {
  const BASE_URL = "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png";
  const RELIEF_URL = "https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png";
  const HAZARD_URL = "https://disaportaldata.gsi.go.jp/raster/{layer}/{z}/{x}/{y}.png";
  const TILE_PAGE = "https://maps.gsi.go.jp/development/ichiran.html";
  const BASE_CREDIT = `<a href="${TILE_PAGE}" target="_blank" rel="noopener">地理院タイル</a>`;
  const RELIEF_CREDIT = `<a href="${TILE_PAGE}" target="_blank" rel="noopener">色別標高図</a>（海域部は海上保安庁海洋情報部の資料を使用して作成）`;
  const HAZARD_CREDIT =
    '出典：<a href="https://disaportal.gsi.go.jp/hazardmap/copyright/opendata.html" target="_blank" rel="noopener">「ハザードマップポータルサイト」</a>';

  // タイルが返らない所に敷く斜線。透明のままだと、色がない所と同じに見えてしまう。
  const HATCH_TILE =
    "data:image/svg+xml;charset=utf-8," +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">' +
        '<defs><pattern id="h" width="16" height="16" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
        '<line x1="0" y1="0" x2="0" y2="16" stroke="#55555f" stroke-width="2"/></pattern></defs>' +
        '<rect width="256" height="256" fill="#ffffff" fill-opacity="0.35"/>' +
        '<rect width="256" height="256" fill="url(#h)"/></svg>',
    );

  const LAYER_NAMES = {
    flood_planned: "洪水（計画規模）",
    flood_max: "洪水（想定最大規模）",
    inland: "内水",
    storm_surge: "高潮",
    tsunami: "津波",
  };
  const COMPASS = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"];
  const OFFSET = { 北: [1, 0], 東: [0, 1], 南: [-1, 0], 西: [0, -1] };

  let map = null;
  let pin = null;
  let overlay = null;
  let relief = null;
  let terrainLayer = null;
  let tapLayers = {};
  let selectedKey = "flood_max";
  let onPinMoved = null;
  let onPicked = null;
  let onTap = null;
  let tapMode = null;
  let current = null;

  function pinIcon() {
    return L.divIcon({ className: "map-pin", html: '<span class="map-pin-dot"></span>', iconSize: [22, 22], iconAnchor: [11, 11] });
  }

  function init(container, handlers) {
    if (map) return;
    onPicked = handlers.picked;
    onTap = handlers.tap;
    map = L.map(container, { attributionControl: false }).setView([35.66, 139.95], 10);
    new ResizeObserver(() => map.invalidateSize()).observe(container);
    L.control.attribution({ prefix: '<a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>' }).addTo(map);
    L.tileLayer(BASE_URL, { maxZoom: 18, minZoom: 5, attribution: BASE_CREDIT }).addTo(map);
    relief = L.tileLayer(RELIEF_URL, { maxNativeZoom: 15, maxZoom: 18, minZoom: 5, opacity: 0.6, attribution: RELIEF_CREDIT });
    terrainLayer = L.layerGroup().addTo(map);
    map.on("click", (event) => {
      if (tapMode) {
        const mode = tapMode;
        setTapMode(null);
        if (pin) onTap(mode, bearingName(pin.getLatLng(), event.latlng));
        return;
      }
      if (!current || !current.site.demo) onPicked(event.latlng.lng, event.latlng.lat);
    });
  }

  function bearingName(from, to) {
    const north = to.lat - from.lat;
    const east = (to.lng - from.lng) * Math.cos((from.lat * Math.PI) / 180);
    const angle = (Math.atan2(east, north) * 180) / Math.PI;
    return COMPASS[Math.round(((angle + 360) % 360) / 45) % 8];
  }

  function setTapMode(mode) {
    tapMode = mode;
    if (map) map.getContainer().classList.toggle("map-tapping", Boolean(mode));
  }

  function setRelief(on) {
    if (!map) return;
    if (on) relief.addTo(map);
    else map.removeLayer(relief);
  }

  function showLayer(hazard) {
    if (overlay) map.removeLayer(overlay);
    overlay = null;
    if (!hazard) return;
    overlay = L.tileLayer(HAZARD_URL, {
      layer: hazard.layer,
      minZoom: 2,
      maxNativeZoom: 17,
      maxZoom: 18,
      opacity: 0.75,
      errorTileUrl: HATCH_TILE,
      attribution: HAZARD_CREDIT,
    }).addTo(map);
  }

  function statusText(hazard) {
    switch (hazard.status) {
      case "color":
        return `ピンの点：${hazard.legend}`;
      case "no_color":
        return hazard.nearby_legend ? "ピンの点：色なし（数m先に色）" : "ピンの点：色なし";
      case "unknown_color":
        return "ピンの点：読み取れず";
      default:
        return "ピンの点：データなし";
    }
  }

  function renderChoices(container, hazards) {
    container.replaceChildren(
      ...hazards.map((hazard) => {
        const label = document.createElement("label");
        label.className = hazard.status === "color" ? "layer-choice layer-colored" : "layer-choice";
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "hazard-layer";
        input.checked = hazard.key === selectedKey;
        input.addEventListener("change", () => {
          selectedKey = hazard.key;
          stopScene();
          showLayer(hazard);
        });
        const name = document.createElement("span");
        name.className = "layer-name";
        name.textContent = LAYER_NAMES[hazard.key];
        const status = document.createElement("span");
        status.className = "layer-status";
        status.textContent = statusText(hazard);
        label.append(input, name, status);
        return label;
      }),
    );
  }

  function renderLegend(container, legend) {
    const items = legend.map(({ color, label }) => {
      const item = document.createElement("span");
      item.className = "legend-item";
      const swatch = document.createElement("span");
      swatch.className = "legend-swatch";
      swatch.style.background = color;
      item.append(swatch, label);
      return item;
    });
    const hatch = document.createElement("span");
    hatch.className = "legend-item";
    const hatchSwatch = document.createElement("span");
    hatchSwatch.className = "legend-swatch legend-swatch-hatch";
    hatch.append(hatchSwatch, "地図のデータが取れていない");
    container.replaceChildren(...items, hatch);
  }

  // 地形分類の札（F-011）。サーバーが読んだ landforms の status から作るだけで、タイルを取りに行かない。
  // 取れないときの文はサーバーの立地の行（app/judge.py）と同じにする。
  const LANDFORM_MISSING = { fetch_failed: "接続できず", no_tile: "この地域のデータなし" };
  const LANDFORM_NOTE = "国土地理院 地形分類（提供実験）。分類ごとの一般的なリスクで、この敷地のリスクを示すものではありません。";

  function landformText(item) {
    if (LANDFORM_MISSING[item.status]) return `地図のデータが取れていない（${LANDFORM_MISSING[item.status]}）`;
    const codes = item.codes || [];
    if (!codes.length) return "ピンの点：どの分類にも当たらず";
    return `ピンの点：${codes.map((code, index) => `『${(item.names || [])[index] || `分類番号 ${code}`}』`).join("")}`;
  }

  function renderLandforms(container, landforms, rows) {
    if (!container) return;
    // 立地の行で水に関わる分類として札が付いた名前だけ、橙にする。
    const ground = (rows || []).find((row) => row.key === "ground");
    const marked = new Set(((ground && ground.accent && ground.accent.badges) || []).filter((badge) => badge.startsWith("地形分類：")).map((badge) => badge.slice(5)));
    const tags = (landforms || []).map((item) => {
      const missing = Boolean(LANDFORM_MISSING[item.status]);
      const names = (item.codes || []).map((code, index) => (item.names || [])[index] || `分類番号 ${code}`);
      const state = missing ? "missing" : names.some((name) => marked.has(name)) ? "marked" : names.length ? "found" : "none";
      const tag = document.createElement("span");
      tag.className = `landform-tag landform-${state}`;
      tag.title = LANDFORM_NOTE;
      const name = document.createElement("span");
      name.className = "layer-name";
      name.textContent = `地形分類（${item.label}）`;
      const status = document.createElement("span");
      status.className = "layer-status";
      status.textContent = landformText(item);
      tag.append(name, status);
      return tag;
    });
    const note = document.createElement("p");
    note.className = "landform-note";
    note.textContent = LANDFORM_NOTE;
    container.replaceChildren(...tags, ...(tags.length ? [note] : []));
    container.hidden = !tags.length;
  }

  function pinNote(site) {
    if (site.demo) {
      return "ピンは町丁の代表点で、建物の位置ではありません。見本は代表点から動かしません（建物は架空です）。";
    }
    if (site.basis === "building") {
      return "ピンの位置で読み直しました。この位置の値で、敷地を測ったものではありません。";
    }
    return "ピンは候補の点です。ここで合っていますか。建物の位置へピンを動かすか、地図を押すと、その位置で読み直します。";
  }

  // 周囲 4 方向の標高と、周囲より低い向きの目安の矢印。
  function drawTerrain(site, reading) {
    terrainLayer.clearLayers();
    const center = [site.latitude, site.longitude];
    const metresLat = 1 / 111000;
    const metresLng = 1 / (111000 * Math.cos((site.latitude * Math.PI) / 180));
    const distance = reading.elevation.distance_m;
    const lows = new Set(reading.low_directions || []);
    const highs = new Set(reading.basin ? reading.high_directions : []);
    reading.elevation.points.slice(1).forEach((point) => {
      const [north, east] = OFFSET[point.label];
      const at = [center[0] + north * distance * metresLat, center[1] + east * distance * metresLng];
      const text = point.elevation_m === null ? "—" : `${point.elevation_m}m`;
      L.marker(at, {
        interactive: false,
        keyboard: false,
        icon: L.divIcon({ className: "elevation-tag", html: `<span>${point.label} ${text}</span>`, iconSize: [64, 20], iconAnchor: [32, 10] }),
      }).addTo(terrainLayer);
      if (lows.has(point.label)) {
        L.polyline([center, at], { color: "#0b4fa8", weight: 3, dashArray: "6 4", interactive: false }).addTo(terrainLayer);
        const rotation = { 北: 0, 東: 90, 南: 180, 西: 270 }[point.label];
        L.marker([center[0] + north * distance * 0.72 * metresLat, center[1] + east * distance * 0.72 * metresLng], {
          interactive: false,
          keyboard: false,
          icon: L.divIcon({ className: "low-arrow", html: `<span style="transform:rotate(${rotation}deg)">▲</span>`, iconSize: [18, 18], iconAnchor: [9, 9] }),
        }).addTo(terrainLayer);
      }
      // 周囲の方が高い凹みでは、外からピンへ向かう矢印を出す。
      if (highs.has(point.label)) {
        L.polyline([at, center], { color: "#c2410c", weight: 3, dashArray: "6 4", interactive: false }).addTo(terrainLayer);
        const rotation = { 北: 180, 東: 270, 南: 0, 西: 90 }[point.label];
        L.marker([center[0] + north * distance * 0.4 * metresLat, center[1] + east * distance * 0.4 * metresLng], {
          interactive: false,
          keyboard: false,
          icon: L.divIcon({ className: "low-arrow inward-arrow", html: `<span style="transform:rotate(${rotation}deg)">▲</span>`, iconSize: [18, 18], iconAnchor: [9, 9] }),
        }).addTo(terrainLayer);
      }
    });
  }

  function drawTaps(directions) {
    Object.values(tapLayers).forEach((layer) => map.removeLayer(layer));
    tapLayers = {};
    if (!current) return;
    const center = [current.site.latitude, current.site.longitude];
    const angles = { 北: 0, 北東: 45, 東: 90, 南東: 135, 南: 180, 南西: 225, 西: 270, 北西: 315 };
    const scale = 0.00042;
    [
      ["water", "#c8611f", "水が来そうな側"],
      ["door", "#5b3f9e", "扉の側"],
    ].forEach(([key, color, name]) => {
      const direction = directions[key];
      if (!direction) return;
      const radians = (angles[direction] * Math.PI) / 180;
      const end = [center[0] + Math.cos(radians) * scale, center[1] + (Math.sin(radians) * scale) / Math.cos((center[0] * Math.PI) / 180)];
      const group = L.layerGroup().addTo(map);
      L.polyline([center, end], { color, weight: 4, interactive: false }).addTo(group);
      L.marker(end, {
        interactive: false,
        keyboard: false,
        icon: L.divIcon({ className: "tap-tag", html: `<span style="border-color:${color};color:${color}">${name}：${direction}</span>`, iconSize: [130, 20], iconAnchor: [65, 10] }),
      }).addTo(group);
      tapLayers[key] = group;
    });
  }

  function show(state, elements, moved) {
    onPinMoved = moved;
    stopScene();
    current = state;
    const { site, location } = state;
    elements.card.hidden = false;

    // 見本では区名の注記が地図に入らない範囲にとどめる。
    map.setMinZoom(site.demo ? 16 : 5);
    const center = [site.latitude, site.longitude];
    if (site.demo) {
      const bounds = L.latLngBounds([site.latitude - 0.004, site.longitude - 0.005], [site.latitude + 0.004, site.longitude + 0.005]);
      map.setMaxBounds(bounds);
    } else {
      map.setMaxBounds(null);
    }
    if (site.basis !== "building") map.setView(center, 17);

    if (pin) map.removeLayer(pin);
    pin = L.marker(center, { icon: pinIcon(), draggable: !site.demo, keyboard: !site.demo, title: "ピン" }).addTo(map);
    pin.on("dragend", () => {
      const { lat, lng } = pin.getLatLng();
      onPinMoved(lng, lat);
    });

    renderChoices(elements.choices, location.reading.hazards);
    renderLandforms(elements.landforms, location.reading.landforms, location.rows);
    renderLegend(elements.legend, location.reading.hazard_legend);
    elements.pinNote.textContent = pinNote(site);
    showLayer(location.reading.hazards.find((hazard) => hazard.key === selectedKey));
    drawTerrain(site, location.reading);
    drawTaps({});
  }

  // 場面の再生。地図の色がある所は深い区分から順に、色がない所は標高の低い所から順に水を広げる。
  // 色がない所の水は、建物の地面の高さまで水位を上げたときの模式で、水の量や流れは計算しない。
  const HAZARD_RANK = {
    "220,122,220": 8,
    "242,133,201": 7,
    "255,145,145": 6,
    "255,183,183": 5,
    "255,216,192": 4,
    "248,225,166": 3,
    "247,245,169": 2,
    "255,255,179": 1,
  };
  // 区分ごとの水の色。浅い区分ほど薄く、深い区分ほど濃い青にする。
  const WATER_COLORS = [
    null,
    [170, 205, 245],
    [140, 185, 240],
    [105, 160, 230],
    [75, 135, 220],
    [45, 105, 200],
    [30, 80, 175],
    [20, 55, 145],
    [15, 35, 110],
  ];
  const DEM5_URL ="https://cyberjapandata.gsi.go.jp/xyz/dem5a_png/{z}/{x}/{y}.png";
  const DEM10_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png";
  const SIM_RADIUS_M = 700;
  // 時間の再生（スライダーと再生／一時停止）。進み具合は一つの値 t（0〜1）で、塗り方は progress = t / SPREAD_END で決める。
  // t が SPREAD_END を過ぎたら広げ終えた形のまま止め、ピンの点が濡れたあとの段階3を見られるようにする。
  // 段階は時刻ではなく順番の名前。速さや時間の予測ではない。
  const PLAY_SECONDS = 8;
  const SPREAD_END = 0.85;
  // 段階1（窪地・深い所）と段階2（低い所から広がる）の境目は、ピンの点が濡れるまでの道のりの最初の4割にする（仮の分け方）。
  const STAGE1_SHARE = 0.4;
  const STAGE_NAMES = ["窪地・深い所にたまる", "低い所から広がる（道路も冠水しうる）", "建物の前に迫る"];
  const STAGE_NOT_REACHED = "ピンの点には届かない（安全という意味ではない）";
  const TIMELINE_NOTE = "時刻や速さの予測ではなく、水が広がる順番の模式です。";
  let sim = null;

  function tileUrl(template, coords, layer) {
    return template.replace("{layer}", layer || "").replace("{z}", coords.z).replace("{x}", coords.x).replace("{y}", coords.y);
  }

  function loadPixels(url) {
    return new Promise((resolve) => {
      const image = new Image();
      image.crossOrigin = "anonymous";
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 256;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        context.drawImage(image, 0, 0, 256, 256);
        resolve(context.getImageData(0, 0, 256, 256).data);
      };
      image.onerror = () => resolve(null);
      image.src = url;
    });
  }

  // 標高タイルの値。データのない所は NaN にする。
  function elevationAt(data, i) {
    if (data[i + 3] === 0) return NaN;
    const value = data[i] * 65536 + data[i + 1] * 256 + data[i + 2];
    if (value === 8388608) return NaN;
    return (value < 8388608 ? value : value - 16777216) * 0.01;
  }

  async function readTile(coords, layers, useDem) {
    const rank = new Uint8Array(65536);
    const elevation = new Float32Array(65536).fill(NaN);
    const hazards = await Promise.all(layers.map((layer) => loadPixels(tileUrl(HAZARD_URL, coords, layer))));
    hazards.filter(Boolean).forEach((data) => {
      for (let p = 0; p < 65536; p += 1) {
        const i = p * 4;
        if (!data[i + 3]) continue;
        const r = HAZARD_RANK[`${data[i]},${data[i + 1]},${data[i + 2]}`] || 0;
        if (r > rank[p]) rank[p] = r;
      }
    });
    if (useDem) {
      const dem = await loadPixels(tileUrl(coords.z >= 15 ? DEM5_URL : DEM10_URL, coords));
      if (dem) for (let p = 0; p < 65536; p += 1) elevation[p] = elevationAt(dem, p * 4);
    }
    return { rank, elevation };
  }

  function paint(tile, progress) {
    const { rank, elevation } = tile.data;
    const image = tile.context.createImageData(256, 256);
    const pixels = image.data;
    const rankLine = sim.maxRank - progress * (sim.maxRank - 1);
    const level = sim.low + progress * (sim.high - sim.low);
    for (let p = 0; p < 65536; p += 1) {
      const i = p * 4;
      if (rank[p] && rank[p] >= rankLine) {
        const [r, g, b] = WATER_COLORS[rank[p]];
        pixels[i] = r;
        pixels[i + 1] = g;
        pixels[i + 2] = b;
        pixels[i + 3] = 200;
      } else if (sim.useDem && elevation[p] <= level) {
        pixels[i] = 40;
        pixels[i + 1] = 170;
        pixels[i + 2] = 210;
        pixels[i + 3] = 130;
      }
    }
    tile.context.putImageData(image, 0, 0);
  }

  function stopScene() {
    if (!sim) return;
    cancelAnimationFrame(sim.frame);
    map.removeLayer(sim.layer);
    if (sim.control) map.removeControl(sim.control);
    sim = null;
  }

  // ピンの点が、何番目の進み具合で塗られるか。地図の色なら区分が塗られる所、標高の模式なら水位がピンの点の標高に届く所。
  // どちらでも塗られないときは null。
  function pinWetProgress() {
    const found = sim.pin;
    let best = null;
    const take = (value) => {
      if (value === null || Number.isNaN(value)) return;
      best = best === null ? value : Math.min(best, value);
    };
    if (found && found.rank) take(sim.maxRank <= 1 ? 0 : Math.min(1, Math.max(0, (sim.maxRank - found.rank) / (sim.maxRank - 1))));
    if (sim.useDem) {
      // 水位はピンの標高（sim.high）まで上げるので、遅くとも広げ終えた所で届く。タイルの画素がそれより低ければ、その分早く届く。
      const height = found && !Number.isNaN(found.elevation) ? Math.min(found.elevation, sim.high) : sim.high;
      if (sim.high <= sim.low || height <= sim.low) take(0);
      else take((height - sim.low) / (sim.high - sim.low));
    }
    return best;
  }

  // 段階の境目（t の値）。段階3はピンの点が濡れる所から。届かないときは広げ終えた所から「届かない」にする。
  function stageBounds() {
    const wetAt = sim.pinWet === null ? null : sim.pinWet * SPREAD_END;
    const first = STAGE1_SHARE * (wetAt === null ? SPREAD_END : wetAt);
    return { first, wetAt, last: wetAt === null ? SPREAD_END : wetAt };
  }

  function stageAt(t) {
    const { first, last } = stageBounds();
    if (t >= last) return 3;
    return t >= first ? 2 : 1;
  }

  function buildTimeline() {
    const box = document.createElement("div");
    box.className = "map-timeline timeline-bar";
    const row = document.createElement("div");
    row.className = "timeline-row";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timeline-play";
    const range = document.createElement("input");
    range.type = "range";
    range.min = "0";
    range.max = "1000";
    range.step = "1";
    range.className = "timeline-range";
    range.setAttribute("aria-label", "水が広がる順番");
    row.append(button, range);
    const strip = document.createElement("div");
    strip.className = "timeline-strip";
    const note = document.createElement("p");
    note.className = "timeline-note";
    note.textContent = TIMELINE_NOTE;
    box.append(row, strip, note);
    button.addEventListener("click", () => (sim && sim.playing ? pauseTimeline() : playTimeline()));
    range.addEventListener("input", () => {
      pauseTimeline();
      setTimeline(Number(range.value) / 1000);
    });
    L.DomEvent.disableClickPropagation(box);
    L.DomEvent.disableScrollPropagation(box);
    return { box, button, range, strip };
  }

  // 段階の帯。幅は段階の長さ（進み具合の割合）で、今の段階だけ濃くする。
  function renderStrip() {
    const ui = sim.ui;
    const { first, wetAt, last } = stageBounds();
    const spans = [first, last - first, 1 - last];
    const stage = stageAt(sim.t);
    ui.strip.replaceChildren(
      ...spans.map((span, index) => {
        const item = document.createElement("span");
        item.className = `timeline-stage${index + 1 === stage ? " is-current" : ""}${index === 2 && wetAt === null ? " is-not-reached" : ""}`;
        item.style.flexGrow = String(Math.max(span, 0));
        item.hidden = span <= 0.001 && index + 1 !== stage;
        const name = index === 2 && wetAt === null ? STAGE_NOT_REACHED : STAGE_NAMES[index];
        item.textContent = `${index + 1} ${name}`;
        item.title = item.textContent;
        return item;
      }),
    );
  }

  function updateTimelineUi() {
    if (!sim || !sim.ui) return;
    sim.ui.range.value = String(Math.round(sim.t * 1000));
    sim.ui.button.textContent = sim.playing ? "❚❚ 一時停止" : sim.t >= 1 ? "↺ 最初から再生" : "▶ 再生";
    const stage = stageAt(sim.t);
    if (stage !== sim.shownStage || !sim.ui.strip.childElementCount) {
      sim.shownStage = stage;
      renderStrip();
    }
  }

  // 進み具合 t（0〜1）で描く。タイルは読み直さず、読んだ値から塗り直すだけ。
  function setTimeline(t) {
    if (!sim || !sim.ready) return;
    sim.t = Math.min(1, Math.max(0, t));
    const progress = Math.round(Math.min(1, sim.t / SPREAD_END) * 120) / 120;
    if (progress !== sim.progress) {
      sim.progress = progress;
      sim.tiles.forEach((tile) => paint(tile, progress));
    }
    updateTimelineUi();
  }

  function playTimeline() {
    if (!sim || !sim.ready) return;
    if (sim.t >= 1) setTimeline(0);
    sim.playing = true;
    sim.last = performance.now();
    const mine = sim;
    const step = (now) => {
      if (sim !== mine || !sim.playing) return;
      // 画面が裏に回って止まっていたときに一気に進まないよう、1回に進める量を抑える。
      const seconds = Math.min(0.1, Math.max(0, (now - sim.last) / 1000));
      sim.last = now;
      setTimeline(sim.t + seconds / PLAY_SECONDS);
      if (sim.t >= 1) {
        pauseTimeline();
        return;
      }
      sim.frame = requestAnimationFrame(step);
    };
    sim.frame = requestAnimationFrame(step);
    updateTimelineUi();
  }

  function pauseTimeline() {
    if (!sim) return;
    sim.playing = false;
    cancelAnimationFrame(sim.frame);
    updateTimelineUi();
  }

  // 確かめる用：今の進み具合と段階の境目。
  function timeline() {
    if (!sim) return null;
    const { first, wetAt } = stageBounds();
    return { ready: Boolean(sim.ready), t: sim.t, progress: sim.progress, stage: stageAt(sim.t), stage2From: first, stage3From: wetAt, pinWet: sim.pinWet, maxRank: sim.maxRank, useDem: sim.useDem, playing: Boolean(sim.playing), tiles: sim.tiles.length };
  }

  // scene: { layers, useDem }。読み込みが終わると onDone({ hadColor, hadDem }) を呼び、時間の再生を始める。
  function playScene(scene, onDone) {
    if (!map || !current) return;
    stopScene();
    if (overlay) map.removeLayer(overlay);
    overlay = null;
    document.querySelectorAll('input[name="hazard-layer"]').forEach((input) => {
      input.checked = false;
    });
    const { site, location } = current;
    const center = L.latLng(site.latitude, site.longitude);
    const bounds = center.toBounds(SIM_RADIUS_M * 2);
    map.fitBounds(bounds, { maxZoom: 16 });
    const tiles = [];
    const Layer = L.GridLayer.extend({
      createTile(coords, done) {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 256;
        const tile = { canvas, context: canvas.getContext("2d"), data: null };
        readTile(coords, scene.layers, scene.useDem).then((data) => {
          tile.data = data;
          tiles.push(tile);
          // ピンの点の画素を覚える（段階3の境目に使う）。細かいズームのタイルを優先する。
          const point = map.project(center, coords.z);
          if (Math.floor(point.x / 256) === coords.x && Math.floor(point.y / 256) === coords.y && sim && sim.layer === this && (!sim.pin || sim.pin.z <= coords.z)) {
            const index = Math.floor(point.y - coords.y * 256) * 256 + Math.floor(point.x - coords.x * 256);
            sim.pin = { z: coords.z, rank: data.rank[index], elevation: data.elevation[index] };
          }
          // 途中で地図を動かして読んだタイルは、その時点の進み具合で描く。
          if (sim && sim.layer === this && sim.ready) paint(tile, sim.progress);
          done(null, canvas);
        });
        return canvas;
      },
    });
    const layer = new Layer({ bounds, maxNativeZoom: 15, minNativeZoom: 13, maxZoom: 18, opacity: 0.85, attribution: HAZARD_CREDIT });
    const pinElevation = location.reading.elevation.points[0].elevation_m;
    sim = { layer, tiles, frame: 0, maxRank: 1, low: 0, high: 0, t: 0, progress: 0, pin: null, pinWet: null, useDem: scene.useDem && pinElevation !== null };
    const mine = sim;
    layer.once("load", () => {
      if (sim !== mine) return;
      let maxRank = 0;
      const heights = [];
      tiles.forEach(({ data }) => {
        for (let p = 0; p < 65536; p += 1) {
          if (data.rank[p] > maxRank) maxRank = data.rank[p];
          if (p % 16 === 0 && !Number.isNaN(data.elevation[p])) heights.push(data.elevation[p]);
        }
      });
      heights.sort((a, b) => a - b);
      sim.maxRank = Math.max(maxRank, 1);
      sim.high = pinElevation ?? 0;
      sim.low = heights.length ? Math.min(heights[Math.floor(heights.length * 0.02)], sim.high) : sim.high;
      sim.pinWet = pinWetProgress();
      sim.ready = true;
      sim.ui = buildTimeline();
      const Control = L.Control.extend({ options: { position: "topright" }, onAdd: () => mine.ui.box });
      sim.control = new Control().addTo(map);
      sim.progress = -1;
      setTimeline(0);
      // 結果の文は読み込みの時点で決まるので、再生を止めても「広がっています」のままにならないよう、ここで返す。
      onDone({ hadColor: maxRank > 0, hadDem: sim.useDem });
      playTimeline();
    });
    layer.addTo(map);
  }

  function refresh() {
    if (map) map.invalidateSize();
  }

  return { init, show, setRelief, setTapMode, drawTaps, refresh, playScene, stopScene, timeline, setTimeline, playTimeline, pauseTimeline };
})();

// 土地の形のミニグラフ。地図の標高データの値で、敷地を測ったものではない。
const TerrainChart = (() => {
  function range(reading) {
    const values = [...reading.profile.ns, ...reading.profile.ew].map(([, value]) => value).filter((value) => value !== null);
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (max - min < 1) {
      const middle = (max + min) / 2;
      min = middle - 0.5;
      max = middle + 0.5;
    }
    return { min, max };
  }

  function line(title, points, leftName, rightName, { min, max }, highs) {
    const valid = points.filter(([, value]) => value !== null);
    const box = document.createElement("figure");
    box.className = "terrain-chart";
    const caption = document.createElement("figcaption");
    caption.textContent = title;
    box.append(caption);
    if (valid.length < 3) {
      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = "標高のデータが足りず、描けません。";
      box.append(note);
      return box;
    }
    const width = 320;
    const height = 96;
    const pad = { left: 24, right: 24, top: 20, bottom: 18 };
    const xs = points.length - 1;
    const x = (index) => pad.left + (index / xs) * (width - pad.left - pad.right);
    const y = (value) => pad.top + ((max - value) / (max - min)) * (height - pad.top - pad.bottom);
    const coords = points.map(([, value], index) => (value === null ? null : `${x(index).toFixed(1)},${y(value).toFixed(1)}`)).filter(Boolean);
    const center = points.findIndex(([distance]) => distance === 0);
    const dots = points
      .map(([, value], index) =>
        value === null
          ? ""
          : `<circle cx="${x(index)}" cy="${y(value)}" r="${index === center ? 5.5 : 3}" fill="${index === center ? "#0b4fa8" : "#6b5b3e"}"/>` +
            `<text x="${x(index)}" y="${y(value) - 8}" font-size="${index === center ? 13 : 11}" font-weight="${index === center ? 700 : 400}" text-anchor="middle" fill="${index === center ? "#0b4fa8" : "#1a1a1c"}">${value}</text>`,
      )
      .join("");
    const bottom = height - pad.bottom;
    // 周囲の方が高い向きに、外からピンへ向かう矢印を引く。
    const pinValue = points[center][1];
    const marker = `inward-${leftName}`;
    // 高いかどうかは 50m 先で見ている。100m 先がさらに高いときだけ、そこから引く。
    const startOf = (side) => {
      const near = points[center + side];
      const far = points[center + side * 2];
      return far && far[1] !== null && near[1] !== null && far[1] > near[1] ? center + side * 2 : center + side;
    };
    const arrows = [
      [leftName, -1],
      [rightName, 1],
    ]
      .filter(([name]) => highs.includes(name) && pinValue !== null)
      .map(([, side]) => {
        const index = startOf(side);
        const startX = x(index);
        const startY = y(points[index][1]) + 13;
        const endX = x(center) + side * 13;
        const endY = y(pinValue) + 3;
        return `<line x1="${startX}" y1="${Math.min(startY, bottom - 2)}" x2="${endX}" y2="${endY}" stroke="#c2410c" stroke-width="3" marker-end="url(#${marker})"/>`;
      })
      .join("");
    box.insertAdjacentHTML(
      "beforeend",
      `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${title}">
        <defs><marker id="${marker}" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#c2410c"/></marker></defs>
        <polygon points="${pad.left},${bottom} ${coords.join(" ")} ${width - pad.right},${bottom}" fill="#e4e0d6"/>
        <polyline points="${coords.join(" ")}" fill="none" stroke="#6b5b3e" stroke-width="2"/>
        ${arrows}
        ${dots}
        <text x="${pad.left}" y="${height - 6}" font-size="12" text-anchor="middle" fill="#5a5a60">${leftName}</text>
        <text x="${x(center)}" y="${height - 6}" font-size="12" font-weight="700" text-anchor="middle" fill="#0b4fa8">ピン</text>
        <text x="${width - pad.right}" y="${height - 6}" font-size="12" text-anchor="middle" fill="#5a5a60">${rightName}</text>
      </svg>`,
    );
    return box;
  }

  function callout(reading) {
    const low = reading.low_directions || [];
    const box = document.createElement("div");
    const title = document.createElement("strong");
    const text = document.createElement("p");
    if (reading.basin) {
      box.className = "terrain-callout callout-basin";
      title.textContent = "⚠ 周囲より低い凹み（目安）";
      text.textContent = `周囲（${reading.high_directions.join("・")}）の方が高く、この場所に向かって水が集まりやすい凹み（低い土地）の形です`;
    } else if (low.length) {
      box.className = "terrain-callout callout-low";
      title.textContent = `周囲より低い向きの目安：${low.join("・")}`;
      text.textContent = "水が流れる向きの予測ではありません";
    } else {
      box.className = "terrain-callout callout-flat";
      title.textContent = "はっきり低い向きは見つからず";
      text.textContent = "くぼ地や低い土地ではないという意味ではありません";
    }
    box.append(title, text);
    return box;
  }

  function render(container, reading, site) {
    container.hidden = false;
    const grid = document.createElement("div");
    grid.className = "terrain-grid";
    const scale = range(reading);
    const highs = reading.basin ? reading.high_directions : [];
    grid.append(line("南北の形", reading.profile.ns, "北", "南", scale, highs), line("東西の形", reading.profile.ew, "西", "東", scale, highs));
    const more = document.createElement("details");
    more.className = "fold";
    const summary = document.createElement("summary");
    summary.textContent = "条件と出典を開く";
    const note = document.createElement("p");
    note.textContent = `${site.basis === "representative" ? "町丁の代表点の値で、建物の位置の値ではありません。" : "ピンの位置の値です。"}単位は m で、ピンの周り100mの地図の標高データの値です。敷地を測ったものではありません。低い向きや凹みは50m先の4点で見た目安で、点の距離（50m、100m）は仮のものです。どの道路かまでは分かりません。2つの図の縦の幅はそろえて広げてあり、差は実際より大きく見えます。水が流れる向きや、雨や浸水の深さの予測ではありません。くぼ地の目安は「敷地の高低差」の行で別に見ます。出典：国土地理院 標高APIを加工して作成`;
    more.append(summary, note);
    container.replaceChildren(callout(reading), grid, more);
  }

  return { render };
})();
