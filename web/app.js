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
  ["clear", "問題なし", "確かめた結果、当たらなかったもの"],
];

let currentLabel = "";

// 画面どうしが共有する状態。判定はサーバーが返したものだけを読む。
const App = {
  sampleId: null,
  locationState: null,
  building: null,
  confirmed: [],
  water: 3,
  measure: "plate",

  roomName(key) {
    return { elec: "電気室（受電の箱の部屋）", pump: "ポンプの部屋", panel_room: "おおもとのスイッチ盤の部屋", tank: "地下の貯留タンク", gen: "非常用発電機の部屋", park: "機械式駐車場の掘り込み", slope: "車路スロープ" }[key] || key;
  },

  async loadBuilding() {
    const response = await fetch("/api/building", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_id: this.sampleId, confirmed: this.confirmed, location_rows: this.locationState.location.rows }),
    });
    this.building = await response.json();
  },

  async startBuilding() {
    this.confirmed = [];
    this.water = 3;
    this.measure = "plate";
    await this.loadBuilding();
    document.getElementById("plan-card").hidden = false;
    document.getElementById("model-card").hidden = false;
    document.getElementById("sim-card").hidden = false;
    document.getElementById("consult-card").hidden = false;
    document.getElementById("chat-toggle").hidden = !document.getElementById("chat").hidden;
    document.getElementById("plan-stage").hidden = true;
    document.getElementById("plan-message").textContent = "";
    document.getElementById("plan-rooms").replaceChildren();
    document.getElementById("pin-card").hidden = true;
    document.getElementById("consult-body").replaceChildren();
    document.getElementById("step-building").dataset.state = "current";
    this.renderBuildingStep();
    PlanPanel.offerSample();
    SimPanel.reset();
    ModelPanel.renderControls();
    this.loadModel();
    this.refresh();
  },

  renderBuildingStep() {
    const sample = this.building.sample;
    const body = document.getElementById("building-body");
    const report = document.createElement("textarea");
    report.id = "report-input";
    report.rows = 5;
    report.setAttribute("aria-label", "点検報告書の文");
    const load = element("button", "架空の点検報告書を読み込む");
    load.type = "button";
    load.addEventListener("click", async () => {
      report.value = await (await fetch(sample.report)).text();
    });
    const read = element("button", "書類を読む", "primary");
    read.type = "button";
    const found = element("div", undefined, "report-found");
    read.addEventListener("click", async () => {
      const response = await fetch("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: report.value }) });
      const result = await response.json();
      found.replaceChildren(element("p", result.message, "hint"));
      const list = element("ul", undefined, "row-details");
      result.findings.forEach((item) => list.append(element("li", `「${item.word}」→ ${item.item}：${item.effect}`)));
      found.append(list);
    });
    body.replaceChildren(
      element("p", `${sample.name}　${sample.floors}階建て ${sample.units}戸（${sample.kind}。建物は架空）`),
      element("p", "右の「平面図と確かめる場所」で図面を読み込みます。点検報告書はここに貼ります。", "hint"),
      report,
      load,
      read,
      found,
    );
  },

  loadModel() {
    if (!window.Model3D) return;
    window.Model3D.load({ ...this.building.sample, confirmedRooms: this.confirmed });
    this.applyScenario();
  },

  scenario() {
    return this.building.scenarios[`${this.water}:${this.measure}`];
  },

  applyScenario() {
    const scenario = this.scenario();
    ModelPanel.render(scenario);
    if (window.Model3D && !window.Model3D.failed && window.Model3D.sample) {
      window.Model3D.apply({ water: this.water, measure: this.measure, scenario });
    }
  },

  setWater(level) {
    this.water = level;
    document.querySelectorAll('input[name="water"]').forEach((node) => {
      node.checked = Number(node.value) === level;
    });
    this.applyScenario();
  },

  setMeasure(key) {
    this.measure = key;
    document.querySelectorAll('input[name="measure"]').forEach((node) => {
      node.checked = node.value === key;
    });
    this.applyScenario();
  },

  focus(key) {
    if (window.Model3D && !window.Model3D.failed) window.Model3D.focus(key);
    ModelPanel.highlightFocus(["elec", "tr", "pump", "ev", "panel_room"].includes(key));
  },

  selectPin(key) {
    const pin = (PlanPanel.pins.length ? PlanPanel.pins : this.building.sample.pins).find((item) => item.key === key);
    if (!pin) return;
    PlanPanel.showPin(pin);
    document.getElementById("pin-card").hidden = false;
    this.focus(pin.focus);
  },

  verdictForPin(pin) {
    const byPin = { tr: "tr", pump: "water", elec: "entry", slope: "entry", tank: "tank", panel_room: "power", door: "entry" };
    const item = this.building.equipment.find((row) => row.key === byPin[pin.target]);
    return item ? { verdict: item.verdict, label: item.verdict_label } : { verdict: "unconfirmed", label: "未確認（調査が必要）" };
  },

  afterPlanRead() {
    document.getElementById("step-result").dataset.state = "current";
  },

  async setConfirmed(kind, value) {
    this.confirmed = value ? [...new Set([...this.confirmed, kind])] : this.confirmed.filter((item) => item !== kind);
    await this.loadBuilding();
    this.refresh();
    this.loadModel();
  },

  refresh() {
    const rows = this.building.equipment;
    const body = document.getElementById("result-body");
    const lead = element("p", this.building.top_line.lead, "top-lead");
    body.replaceChildren(lead, ...rows.map(screenRow));
    this.applyScenario();
    SimPanel.render();
    SheetPanel.render();
  },

  chatContext() {
    if (!this.building) return { sample_id: this.sampleId };
    return {
      sample_id: this.building.sample.id,
      subsidy: this.building.sample.subsidy,
      name: this.building.sample.name,
      site: this.locationState.site.label,
      location: this.locationState.location.rows.map((row) => ({ label: row.label, verdict: row.verdict_label, summary: row.summary, confirm_by: row.confirm_by })),
      equipment: rowsForChat(this.building.equipment),
      places: this.building.sample.pins.map((pin) => ({ key: pin.key, title: pin.title, how_water: pin.how_water, check: pin.check, who: pin.who })),
      water: this.water,
      measure: this.measure,
    };
  },

  applyAction(action) {
    if (action.type === "focus") this.focus(action.target);
    if (action.type === "water") this.setWater(action.level);
    if (action.type === "measure") this.setMeasure(action.key);
  },
};

function rowsForChat(rows) {
  return rows.map((row) => ({ label: row.label, verdict: row.verdict_label, summary: row.summary, confirm_by: row.confirm_by }));
}

window.App = App;
window.addEventListener("model3d-ready", () => {
  if (App.building) App.loadModel();
});

async function showClaudeStatus() {
  try {
    const response = await fetch("/api/status");
    const status = await response.json();
    document.getElementById("claude-status").textContent = status.claude
      ? "Claude の API に接続する設定です。"
      : "API キーが未設定です。Claude を使う所は、説明カードやプログラムの定型文で動きます（画面にその旨を出します）。";
  } catch (error) {
    // 表示できなくても動く。
  }
}
showClaudeStatus();

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
  [...(row.records || []), ...row.details].forEach((line) => list.append(element("li", line)));
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

// 紙のおもては細い表にする。一番大事な「何が止まるか」以降に場所を残すため。全文は別紙に出す。
function sheetTable(rows) {
  const table = element("table", undefined, "slim-table");
  const header = table.createTHead().insertRow();
  ["見たもの", "判定", "分かったこと", "誰が確かめるか"].forEach((name) => header.append(element("th", name)));
  const body = table.createTBody();
  rows.forEach((row) => {
    const line = body.insertRow();
    line.append(element("td", row.label));
    const verdict = line.insertCell();
    verdict.append(verdictTag(row.verdict, row.verdict_label));
    line.append(element("td", row.summary), element("td", row.confirm_short || "—"));
  });
  return table;
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
    sheetTable(location.rows),
    element(
      "p",
      `${site.basis === "representative" ? "町丁の代表点の値で、建物の位置の値ではありません。" : "ピンの位置の値です。"}色がないことは安全という意味ではありません。条件と出典は別紙に書いています。`,
      "sheet-pointer",
    ),
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
  App.locationState = state;
  if (App.sampleId) {
    App.startBuilding();
  } else {
    offerArchetypes();
  }
}

// 見本以外の住所では、近い形の見本を借りて説明する。
function offerArchetypes() {
  const body = document.getElementById("building-body");
  body.replaceChildren(element("p", "この建物に近い形を選んでください。見本の形を借りて説明します（架空の建物の図面と設備です）。", "hint"));
  [["a", "地下に電気室がある中〜大規模"], ["b", "地下がなく設備が1階の小〜中規模"], ["c", "地下設備のタワーマンション"]].forEach(([id, text]) => {
    const button = element("button", text);
    button.type = "button";
    button.addEventListener("click", () => {
      App.sampleId = id;
      App.startBuilding();
    });
    body.append(button);
  });
  document.getElementById("step-building").dataset.state = "current";
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
  lookUp({ address: currentLabel, longitude, latitude, pin: 1 });
}

const candidatesBox = document.getElementById("candidates");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  candidatesBox.hidden = true;
  addressError.hidden = true;
  try {
    const response = await fetch(`/api/search?${new URLSearchParams({ q: addressInput.value })}`);
    const body = await response.json();
    if (!response.ok) {
      showError(body.error);
      return;
    }
    renderCandidates(body.candidates);
  } catch (error) {
    showError("サーバーに接続できませんでした。起動しているか確かめてください。");
  }
});

function renderCandidates(candidates) {
  candidatesBox.replaceChildren(element("p", "候補から選んでください。", "hint"));
  candidates.forEach((candidate) => {
    const button = element("button", candidate.label, "candidate");
    button.type = "button";
    button.append(element("small", `（${candidate.source}）`));
    button.addEventListener("click", () => {
      App.sampleId = null;
      lookUp({ address: candidate.label, longitude: candidate.longitude, latitude: candidate.latitude });
    });
    candidatesBox.append(button);
  });
  if (candidates.some((candidate) => candidate.source === "OpenStreetMap")) {
    const credit = element("p", "", "hint");
    const link = element("a", "© OpenStreetMap contributors");
    link.href = "https://www.openstreetmap.org/copyright";
    link.target = "_blank";
    link.rel = "noopener";
    credit.append(link);
    candidatesBox.append(credit);
  }
  candidatesBox.hidden = false;
}

document.getElementById("print-button").addEventListener("click", () => window.print());

async function loadDemoPoints() {
  try {
    const response = await fetch("/api/demo-points");
    const points = await response.json();
    const buttons = document.getElementById("demo-buttons");
    points.forEach((point) => {
      const button = element("button", point.label);
      button.type = "button";
      button.title = point.kind;
      button.addEventListener("click", () => {
        addressInput.value = "";
        candidatesBox.hidden = true;
        App.sampleId = point.sample;
        lookUp({ demo: point.id });
      });
      buttons.append(button);
    });
    document.getElementById("demo-points").hidden = false;
  } catch (error) {
    // 見本のボタンが出なくても、検索は使える。
  }
}

// 別紙だけを渡されても読めるよう、免責の固定の文を同じものにする。
sheetBasis.append(document.querySelector(".disclaimer").cloneNode(true));

loadDemoPoints();
