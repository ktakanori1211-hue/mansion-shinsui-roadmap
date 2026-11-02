"use strict";

const form = document.getElementById("address-form");
const addressInput = document.getElementById("address");
const addressError = document.getElementById("address-error");
const locationBody = document.getElementById("location-body");
const sheetAddress = document.getElementById("sheet-address");
const sheetLocation = document.getElementById("sheet-location");
const sheetBasis = document.getElementById("sheet-basis");
const sheetBasisAddress = document.getElementById("sheet-basis-address");
const sheetBasisRows = document.getElementById("sheet-basis-rows");
const stepAddress = document.getElementById("step-address");
const stepLocation = document.getElementById("step-location");
const mapElements = {
  card: document.getElementById("map-card"),
  map: document.getElementById("map"),
  choices: document.getElementById("layer-choices"),
  legend: document.getElementById("map-legend"),
  pinNote: document.getElementById("map-pin-note"),
};

// 判定表の免責の固定の文。言い換えず、折りたたまない。
const FIXED_NOTES = [
  "浸水実績は自治体の公表データを独自に集計・加工したもので、自治体の公式証明ではない",
  "本シートは予報ではなく、現時点の静的な整理である",
];

const VERDICT_LEGEND = [
  ["risk", "リスクあり（確定）", "公開データと入力で確定したもの"],
  ["unconfirmed", "未確認（調査が必要）", "まだ分からないもの。危険という意味ではありません"],
  ["clear", "問題なし", "五つの項目がそろって当たらなかったもの"],
];

let currentLabel = "";

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function verdictTag(verdict, label) {
  return element("span", label, `tag tag-${verdict}`);
}

function detailItems(row) {
  const list = element("ul", undefined, "row-details");
  [...row.records, ...row.details].forEach((line) => list.append(element("li", line)));
  if (row.confirm_by) {
    const item = element("li", undefined, "row-confirm");
    item.append(element("strong", "誰が確かめるか："), row.confirm_by);
    list.append(item);
  }
  return list;
}

// 一段目は札と結論。二段目は条件と出典で、画面では開いて読む。
function firstTier(row) {
  const head = element("div", undefined, "row-head");
  head.append(verdictTag(row.verdict, row.verdict_label), element("span", row.label, "row-label"));
  return [head, element("p", row.headline, "row-headline")];
}

function screenRow(row) {
  const article = element("article", undefined, "row");
  const more = element("details", undefined, "row-more");
  more.append(element("summary", "条件と出典、誰が確かめるか"), detailItems(row));
  article.append(...firstTier(row), more);
  return article;
}

// 紙のおもてには札と結論と誰が確かめるかを置き、条件と出典は別紙へ分ける。
function sheetRow(row) {
  const article = element("article", undefined, "row");
  article.append(...firstTier(row));
  if (row.confirm_by) {
    const confirm = element("p", undefined, "row-confirm-sheet");
    confirm.append(element("strong", "誰が確かめるか："), row.confirm_by);
    article.append(confirm);
  }
  return article;
}

// 別紙には条件と出典を折りたたまずに全文出す。
function basisRow(row) {
  const article = element("article", undefined, "row");
  const head = element("div", undefined, "row-head");
  head.append(verdictTag(row.verdict, row.verdict_label), element("span", row.label, "row-label"));
  article.append(head);
  if (row.records.length) {
    const records = element("ul", undefined, "record-list");
    row.records.forEach((line) => records.append(element("li", line)));
    article.append(records);
  }
  const list = element("ul", undefined, "row-details");
  row.details.forEach((line) => list.append(element("li", line)));
  article.append(list);
  return article;
}

function verdictLegend() {
  const legend = element("div", undefined, "verdict-legend");
  VERDICT_LEGEND.forEach(([verdict, label, meaning]) => {
    const item = element("p", undefined, "verdict-legend-item");
    item.append(verdictTag(verdict, label), meaning);
    legend.append(item);
  });
  return legend;
}

function fixedNotes() {
  const notes = element("div", undefined, "fixed-notes");
  FIXED_NOTES.forEach((line) => notes.append(element("p", line, "fixed-note")));
  return notes;
}

function renderLocation(state) {
  const { site, location } = state;
  currentLabel = site.label;
  locationBody.replaceChildren(
    verdictLegend(),
    element("p", location.basis_note, "basis-note"),
    ...location.rows.map(screenRow),
    fixedNotes(),
  );
  sheetAddress.textContent = `住所：${site.label}`;
  sheetLocation.replaceChildren(
    ...location.rows.map(sheetRow),
    element("p", "条件と出典は別紙に書いています。", "sheet-pointer"),
  );
  sheetBasisAddress.textContent = `住所：${site.label}`;
  sheetBasisRows.replaceChildren(
    element("p", location.basis_note, "basis-note"),
    ...location.rows.map(basisRow),
  );
  sheetBasis.hidden = false;
  stepAddress.dataset.state = "done";
  stepLocation.dataset.state = "current";
  HazardMap.show(state, mapElements, movePin);
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
    element("p", "住所を入れると、ここに五つの項目の判定が出ます。", "hint"),
  );
  sheetAddress.textContent = "住所：まだ入っていません";
  sheetLocation.replaceChildren(
    element("p", "住所を入れると、公開データの値が出ます。", "placeholder"),
  );
  sheetBasis.hidden = true;
  stepAddress.dataset.state = "current";
  stepLocation.dataset.state = "waiting";
  HazardMap.hide(mapElements.card);
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

function movePin(longitude, latitude) {
  lookUp({ address: currentLabel, longitude, latitude });
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

// 別紙だけを渡されても読めるよう、免責の固定の文を同じものにする。
sheetBasis.append(document.querySelector(".disclaimer").cloneNode(true));

loadDemoPoints();
