"use strict";

const form = document.getElementById("address-form");
const addressInput = document.getElementById("address");
const addressError = document.getElementById("address-error");
const locationBody = document.getElementById("location-body");
const sheetAddress = document.getElementById("sheet-address");
const sheetLocation = document.getElementById("sheet-location");
const stepAddress = document.getElementById("step-address");
const stepLocation = document.getElementById("step-location");

const SOURCE_NOTE =
  "出典：国土地理院(住所検索、標高、地形分類)、ハザードマップポータルサイト。読み取った値を加工して表示しています。";

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function hazardText(hazard) {
  switch (hazard.status) {
    case "color":
      return `凡例の「${hazard.legend}」の色`;
    case "no_color":
      return "色がない";
    case "no_tile":
      return "地図のデータが取れていない";
    case "unknown_color":
      return "凡例にない色で、読み取れていない";
    default:
      return "地図のデータが取れていない(接続できず)";
  }
}

function landformText(landform) {
  if (landform.status === "found") {
    return landform.names.map((name, i) => name || `分類番号 ${landform.codes[i]}`).join("、");
  }
  if (landform.status === "none") return "この点に分類がない";
  return "地図のデータが取れていない";
}

function elevationText(point) {
  return point.elevation_m === null ? "取れていない" : `${point.elevation_m}m`;
}

function buildReadingsTable(result) {
  const table = element("table", undefined, "readings");
  const body = table.createTBody();
  const addRow = (name, value) => {
    const row = body.insertRow();
    row.append(element("th", name), element("td", value));
  };

  const [center, ...around] = result.elevation.points;
  addRow("標高", elevationText(center));
  addRow(
    `周囲${result.elevation.distance_m}m`,
    around.map((p) => `${p.label} ${elevationText(p)}`).join("、"),
  );
  result.hazards.forEach((hazard) => addRow(hazard.label, hazardText(hazard)));
  result.landforms.forEach((landform) => addRow(landform.label, landformText(landform)));
  return table;
}

function readingNotes() {
  return [
    element(
      "p",
      "住所検索で得た代表点の値で、建物の位置の値ではありません。標高は地図の標高データの値で、敷地を測ったものではありません。ここでは値を並べるだけで、判定はまだしていません。",
      "source",
    ),
    element(
      "p",
      "国の地形分類は地形分類ごとの一般的なリスクを示すもので、この敷地のリスクを示すものではありません。",
      "source",
    ),
    element("p", SOURCE_NOTE, "source"),
  ];
}

function renderLocation(result) {
  locationBody.replaceChildren(buildReadingsTable(result), ...readingNotes());
  sheetAddress.textContent = `住所：${result.label}`;
  sheetLocation.replaceChildren(buildReadingsTable(result), ...readingNotes());
  stepAddress.dataset.state = "done";
  stepLocation.dataset.state = "current";
}

function setBusy(busy) {
  document.querySelectorAll("#step-address button").forEach((button) => {
    button.disabled = busy;
  });
  if (busy) {
    addressError.hidden = true;
    locationBody.replaceChildren(element("p", "公開データを読んでいます。", "hint"));
  }
}

function showError(message) {
  addressError.textContent = message;
  addressError.hidden = false;
  locationBody.replaceChildren(
    element("p", "住所を入れると、ここに公開データの値が出ます。", "hint"),
  );
  sheetAddress.textContent = "住所：まだ入っていません";
  sheetLocation.replaceChildren(
    element("p", "住所を入れると、公開データの値が出ます。", "placeholder"),
  );
  stepAddress.dataset.state = "current";
  stepLocation.dataset.state = "waiting";
}

async function lookUp(params) {
  setBusy(true);
  try {
    const response = await fetch(`/api/location?${new URLSearchParams(params)}`);
    const body = await response.json();
    if (!response.ok) {
      showError(body.error);
      return;
    }
    renderLocation(body);
  } catch (error) {
    showError("サーバーに接続できませんでした。起動しているか確かめてください。");
  } finally {
    setBusy(false);
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  lookUp({ address: addressInput.value });
});

document.getElementById("print-button").addEventListener("click", () => window.print());

async function loadDemoPoints() {
  try {
    const response = await fetch("/api/demo-points");
    const points = await response.json();
    const buttons = document.getElementById("demo-buttons");
    points.forEach((point) => {
      const button = element("button", point.label);
      button.type = "button";
      button.addEventListener("click", () => {
        addressInput.value = "";
        lookUp({ demo: point.id });
      });
      buttons.append(button);
    });
    document.getElementById("demo-points").hidden = false;
  } catch (error) {
    // デモのボタンが出なくても、住所の入力は使える。
  }
}

loadDemoPoints();
