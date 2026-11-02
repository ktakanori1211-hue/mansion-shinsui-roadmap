"use strict";

// 地図の表示だけを受け持つ。判定はしない。
const HazardMap = (() => {
  const BASE_URL = "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png";
  const HAZARD_URL = "https://disaportaldata.gsi.go.jp/raster/{layer}/{z}/{x}/{y}.png";
  const BASE_CREDIT =
    '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">地理院タイル</a>';
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

  let map = null;
  let pin = null;
  let overlay = null;
  let selectedKey = "flood_max";
  let onPinMoved = null;

  function pinIcon() {
    return L.divIcon({
      className: "map-pin",
      html: '<span class="map-pin-dot"></span>',
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });
  }

  function ensureMap(container) {
    if (map) return;
    map = L.map(container, { attributionControl: false });
    L.control.attribution({ prefix: '<a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>' }).addTo(map);
    L.tileLayer(BASE_URL, { maxZoom: 18, minZoom: 5, attribution: BASE_CREDIT }).addTo(map);
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
        return hazard.nearby_legend ? `ピンの点：色なし（数m先に色）` : "ピンの点：色なし";
      case "unknown_color":
        return "ピンの点：読み取れず";
      default:
        return "ピンの点：データなし";
    }
  }

  function renderChoices(container, hazards) {
    const choices = hazards.map((hazard) => {
      const label = document.createElement("label");
      label.className = "layer-choice";
      label.dataset.status = hazard.status;
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
    });
    container.replaceChildren(...choices);
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
      return "ピンは町丁の代表点で、建物の位置ではありません。デモは代表点から動かしません（建物の条件は架空です）。";
    }
    if (site.basis === "building") {
      return "ピンの位置で読み直しました。この位置の値で、敷地を測ったものではありません。";
    }
    return "ピンは町丁の代表点です。ここで合っていますか。建物の位置へピンを動かすと、その位置で読み直します。";
  }

  // state は共通のデータ。elements は描く先の要素。
  function show(state, elements, moved) {
    onPinMoved = moved;
    const { site, location } = state;
    elements.card.hidden = false;
    const isNew = !map;
    ensureMap(elements.map);

    // デモでは区名の注記が地図に入らない範囲にとどめる。
    map.setMinZoom(site.demo ? 16 : 12);
    const center = [site.latitude, site.longitude];
    if (site.demo) {
      const bounds = L.latLngBounds(center, center).pad(0).extend([site.latitude - 0.004, site.longitude - 0.005]);
      map.setMaxBounds(bounds.extend([site.latitude + 0.004, site.longitude + 0.005]));
    } else {
      map.setMaxBounds(null);
    }
    if (site.basis !== "building") map.setView(center, 17);
    if (isNew) map.invalidateSize();

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
  }

  function hide(card) {
    card.hidden = true;
  }

  return { show, hide };
})();
