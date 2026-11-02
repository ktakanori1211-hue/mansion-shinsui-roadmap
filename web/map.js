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
        label.className = "layer-choice";
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "hazard-layer";
        input.checked = hazard.key === selectedKey;
        input.addEventListener("change", () => {
          selectedKey = hazard.key;
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
    renderLegend(elements.legend, location.reading.hazard_legend);
    elements.pinNote.textContent = pinNote(site);
    showLayer(location.reading.hazards.find((hazard) => hazard.key === selectedKey));
    drawTerrain(site, location.reading);
    drawTaps({});
  }

  function refresh() {
    if (map) map.invalidateSize();
  }

  return { init, show, setRelief, setTapMode, drawTaps, refresh };
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

  function line(title, points, leftName, rightName, { min, max }) {
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
    const height = 120;
    const pad = { left: 36, right: 14, top: 14, bottom: 26 };
    const xs = points.length - 1;
    const x = (index) => pad.left + (index / xs) * (width - pad.left - pad.right);
    const y = (value) => pad.top + ((max - value) / (max - min)) * (height - pad.top - pad.bottom);
    const coords = points.map(([, value], index) => (value === null ? null : `${x(index).toFixed(1)},${y(value).toFixed(1)}`)).filter(Boolean);
    const center = points.findIndex(([distance]) => distance === 0);
    const dots = points
      .map(([, value], index) =>
        value === null
          ? ""
          : `<circle cx="${x(index)}" cy="${y(value)}" r="${index === center ? 5 : 3}" fill="${index === center ? "#0b4fa8" : "#5a5a60"}"/>` +
            `<text x="${x(index)}" y="${y(value) - 7}" font-size="10" text-anchor="middle" fill="#1a1a1c">${value}</text>`,
      )
      .join("");
    const bottom = height - pad.bottom;
    box.insertAdjacentHTML(
      "beforeend",
      `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${title}">
        <polygon points="${pad.left},${bottom} ${coords.join(" ")} ${width - pad.right},${bottom}" fill="#e4e0d6"/>
        <polyline points="${coords.join(" ")}" fill="none" stroke="#6b5b3e" stroke-width="2"/>
        ${dots}
        <text x="${pad.left}" y="${height - 8}" font-size="11" text-anchor="middle" fill="#5a5a60">${leftName}</text>
        <text x="${x(center)}" y="${height - 8}" font-size="11" text-anchor="middle" fill="#0b4fa8">ピン</text>
        <text x="${width - pad.right}" y="${height - 8}" font-size="11" text-anchor="middle" fill="#5a5a60">${rightName}</text>
      </svg>`,
    );
    return box;
  }

  function render(container, reading, site) {
    container.hidden = false;
    const heading = document.createElement("h3");
    heading.textContent = "ピンの周り100mの標高（地図の標高データ。単位は m）";
    const grid = document.createElement("div");
    grid.className = "terrain-grid";
    const scale = range(reading);
    grid.append(line("南北の形（北 → ピン → 南）", reading.profile.ns, "北", "南", scale), line("東西の形（西 → ピン → 東）", reading.profile.ew, "西", "東", scale));
    const low = reading.low_directions || [];
    const summary = document.createElement("p");
    summary.className = "terrain-note strong";
    summary.textContent = low.length
      ? `周囲より低い向きの目安（ピンより低い点がある向き）：${low.join("・")}。水が流れる向きの予測ではありません。`
      : "ピンより低い点がある向きは、50m先の4点では見つかりませんでした。くぼ地や低い土地ではないという意味ではありません。くぼ地の目安は「敷地の高低差」の行で別に見ます。";
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = `${site.basis === "representative" ? "町丁の代表点の値で、建物の位置の値ではありません。" : "ピンの位置の値です。"}地図の標高データの値で、敷地を測ったものではありません。点の距離（50m、100m）は仮の目安で、どの道路かまでは分かりません。2つの図の縦の幅はそろえて広げてあり、差は実際より大きく見えます。雨や浸水の深さの予測ではありません。出典：国土地理院 標高APIを加工して作成`;
    container.replaceChildren(heading, grid, summary, note);
  }

  return { render };
})();
