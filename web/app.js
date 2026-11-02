"use strict";

const form = document.getElementById("address-form");
const addressInput = document.getElementById("address");
const addressError = document.getElementById("address-error");
const searchMessage = document.getElementById("search-message");
const candidatesBox = document.getElementById("candidates");
const locationBody = document.getElementById("location-body");
const sheetAddress = document.getElementById("sheet-address");
const sheetLocation = document.getElementById("sheet-location");
const sheetBasis = document.getElementById("sheet-basis");
const sheetBasisAddress = document.getElementById("sheet-basis-address");
const sheetBasisRows = document.getElementById("sheet-basis-rows");
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

// 画面どうしが共有する状態。判定はサーバーが返したものだけを読む。
const App = {
  sampleId: null,
  answers: null,
  locationState: null,
  building: null,
  confirmed: [],
  documentRead: false,
  directions: {},
  statements: [],
  hints: {},
  water: 3,
  measure: "plate",
  stage: "1",

  roomName(key) {
    return { elec: "電気室（受電の箱の部屋）", pump: "ポンプの部屋", panel_room: "おおもとのスイッチ盤の部屋", tank: "地下の貯留タンク", gen: "非常用発電機の部屋", park: "機械式駐車場の掘り込み", slope: "車路スロープ" }[key] || key;
  },

  requestBody() {
    return {
      sample_id: this.sampleId,
      answers: this.answers,
      label: this.locationState.site.label,
      confirmed: this.confirmed,
      document_read: this.documentRead,
      directions: this.directions,
      low_directions: this.locationState.location.reading.low_directions,
      statements: this.statements,
      location_rows: this.locationState.location.rows,
    };
  },

  async loadBuilding() {
    const response = await fetch("/api/building", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(this.requestBody()),
    });
    this.building = await response.json();
  },

  async startBuilding() {
    this.confirmed = [];
    this.documentRead = false;
    this.statements = [];
    this.water = 3;
    this.measure = "plate";
    if (!this.sampleId && !this.answers) {
      this.answers = { basement: "unknown", floors: this.hints.floors || null, built_year: this.hints.built_year || null };
    }
    await this.loadBuilding();
    ["plan-card", "model-card", "model-lower", "step-result", "step-building", "sim-card", "consult-card", "top-banner"].forEach((id) => {
      document.getElementById(id).hidden = false;
    });
    document.getElementById("stage2-empty").hidden = true;
    document.getElementById("stage4-empty").hidden = true;
    document.getElementById("chat-toggle").hidden = !document.getElementById("chat").hidden;
    document.getElementById("plan-stage").hidden = true;
    document.getElementById("plan-message").textContent = "";
    document.getElementById("plan-rooms").replaceChildren();
    document.getElementById("pin-card").hidden = true;
    document.getElementById("consult-body").replaceChildren();
    ExitPanel.reset();
    QuestionPanel.render();
    PlanPanel.offerSample();
    SimPanel.reset();
    ModelPanel.renderControls();
    this.loadModel();
    this.refresh();
  },

  // 答えを変えたときは、図面の確認を残して組み直す。
  async rebuild() {
    await this.loadBuilding();
    QuestionPanel.render();
    PlanPanel.offerSample();
    SimPanel.reset();
    ModelPanel.renderControls();
    this.loadModel();
    this.refresh();
  },

  loadModel() {
    if (!window.Model3D) return;
    window.Model3D.load({ ...this.building.sample, confirmedRooms: this.confirmed });
    window.Model3D.setDirections?.(this.directions);
    this.applyScenario();
  },

  disclaimerText() {
    const { fixed, sample } = this.building;
    return sample.has_chief_engineer && !sample.engineer_unsure ? fixed.disclaimer_1 : fixed.disclaimer_1_no_engineer;
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

  async setConfirmed(kind, value) {
    this.confirmed = value ? [...new Set([...this.confirmed, kind])] : this.confirmed.filter((item) => item !== kind);
    await this.loadBuilding();
    this.refresh();
    this.loadModel();
  },

  async setDirection(key, direction) {
    this.directions = { ...this.directions, [key]: direction };
    HazardMap.drawTaps(this.directions);
    window.Model3D?.setDirections?.(this.directions);
    showTapStatus();
    if (this.building) {
      await this.loadBuilding();
      this.refresh();
    }
  },

  async addStatement(text) {
    this.statements = [...this.statements, text];
    await this.loadBuilding();
    this.refresh();
  },

  refresh() {
    const building = this.building;
    document.getElementById("top-banner-lead").textContent = building.top_line.lead;
    document.getElementById("top-banner-notes").textContent = building.top_line.notes.join("");
    document.getElementById("top-banner-dir").textContent = building.direction_line;
    const body = document.getElementById("result-body");
    const grid = element("div", undefined, "result-grid");
    grid.append(...building.equipment.map(screenRow));
    body.replaceChildren(grid);
    if (building.statements.length) {
      body.append(element("p", `聞き取りとして入れた話：${building.statements.join("／")}（図面で確かめるまで未確認です）`, "hint"));
    }
    this.applyScenario();
    SimPanel.render();
    SheetPanel.render();
    ExitPanel.render();
  },

  chatContext() {
    if (!this.building) return { sample_id: this.sampleId };
    return {
      sample_id: this.sampleId,
      answers: this.answers,
      subsidy: this.building.sample.subsidy,
      name: this.building.sample.name,
      site: this.locationState.site.label,
      location: this.locationState.location.rows.map((row) => ({ label: row.label, verdict: row.verdict_label, summary: row.summary, confirm_by: row.confirm_by })),
      equipment: this.building.equipment.map((row) => ({ label: row.label, verdict: row.verdict_label, summary: row.summary, confirm_by: row.confirm_by })),
      places: this.building.sample.pins.map((pin) => ({ key: pin.key, title: pin.title, how_water: pin.how_water, check: pin.check, who: pin.who })),
      direction: this.building.direction_line,
      water: this.water,
      measure: this.measure,
    };
  },

  applyAction(action) {
    if (["focus", "water", "measure"].includes(action.type) && this.stage !== "all" && this.stage !== "2") this.showStage("2");
    if (action.type === "focus") this.focus(action.target);
    if (action.type === "water") this.setWater(action.level);
    if (action.type === "measure") this.setMeasure(action.key);
    if (action.type === "statement") this.addStatement(action.text);
  },

  showStage(stage) {
    this.stage = String(stage);
    document.querySelectorAll(".stage").forEach((section) => {
      section.classList.toggle("is-hidden", this.stage !== "all" && section.dataset.stage !== this.stage);
    });
    document.querySelectorAll("#stage-tabs button").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === this.stage);
    });
    document.getElementById("why-bar").classList.toggle("is-hidden", this.stage !== "1" && this.stage !== "all");
    HazardMap.refresh();
    window.dispatchEvent(new Event("resize"));
  },
};
window.App = App;

function renderLocation(state) {
  const { site, location } = state;
  locationBody.replaceChildren(
    verdictLegend(),
    element("p", location.basis_note, "basis-note"),
    element("div", undefined, "result-grid"),
    fixedNotes(),
  );
  locationBody.querySelector(".result-grid").append(...location.rows.map(screenRow));
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
  sheetBasisRows.replaceChildren(element("p", location.basis_note, "basis-note"), ...location.rows.map(basisRow));
  sheetBasis.hidden = false;
  HazardMap.show(state, mapElements, movePin);
  TerrainChart.render(document.getElementById("terrain"), location.reading, site);
  App.locationState = state;
  App.startBuilding();
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
  if (!App.locationState) {
    locationBody.replaceChildren(element("p", "場所を選ぶと、ここに五つの項目の判定が出ます。", "hint"));
  }
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
  lookUp({ address: App.locationState.site.label, longitude, latitude, pin: 1 });
}

async function pickPoint(longitude, latitude) {
  App.sampleId = null;
  App.answers = null;
  App.directions = {};
  showTapStatus();
  let label = "地図で選んだ場所";
  try {
    const response = await fetch(`/api/reverse?${new URLSearchParams({ longitude, latitude })}`);
    const body = await response.json();
    if (body.label) label = body.label;
  } catch (error) {
    // 町丁名が取れなくても、位置の値は読める。
  }
  lookUp({ address: label, longitude, latitude, pin: 1 });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  candidatesBox.hidden = true;
  searchMessage.hidden = true;
  addressError.hidden = true;
  try {
    const response = await fetch(`/api/search?${new URLSearchParams({ q: addressInput.value })}`);
    const body = await response.json();
    if (!response.ok) {
      showError(body.error);
      return;
    }
    App.hints = body.hints || {};
    if (body.message) {
      searchMessage.textContent = body.message;
      searchMessage.hidden = false;
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
      App.answers = null;
      App.directions = {};
      showTapStatus();
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

document.getElementById("geo-button").addEventListener("click", () => {
  if (!navigator.geolocation) {
    showError("このブラウザでは現在地を使えません。");
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (position) => pickPoint(position.coords.longitude, position.coords.latitude),
    () => showError("現在地を取得できませんでした。住所で探すか、地図を押して選んでください。"),
    { timeout: 10000 },
  );
});

function showTapStatus() {
  const { water, door } = App.directions;
  const parts = [];
  if (water) parts.push(`水が来そうな側：${water}`);
  if (door) parts.push(`扉の側：${door}`);
  document.getElementById("tap-status").textContent = parts.join("／");
}

function armTap(mode, message) {
  if (!App.locationState) {
    showError("先に場所を選んでください。");
    return;
  }
  HazardMap.setTapMode(mode);
  document.getElementById("tap-status").textContent = message;
}

document.getElementById("tap-water").addEventListener("click", () => armTap("water", "地図で水が来そうな側（低い側など）を押してください"));
document.getElementById("tap-door").addEventListener("click", () => armTap("door", "地図で電気室の扉がある側を押してください"));
document.getElementById("relief-toggle").addEventListener("change", (event) => HazardMap.setRelief(event.target.checked));

document.getElementById("stage-tabs").addEventListener("click", (event) => {
  const tab = event.target.closest("button")?.dataset.tab;
  if (tab) App.showStage(tab);
});
document.querySelectorAll("[data-go]").forEach((button) => {
  button.addEventListener("click", () => {
    App.showStage(button.dataset.go);
    window.scrollTo(0, 0);
  });
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
      button.title = point.kind;
      button.addEventListener("click", () => {
        addressInput.value = "";
        candidatesBox.hidden = true;
        searchMessage.hidden = true;
        App.sampleId = point.sample;
        App.answers = null;
        App.directions = {};
        showTapStatus();
        lookUp({ demo: point.id });
      });
      buttons.append(button);
    });
    document.getElementById("demo-points").hidden = false;
  } catch (error) {
    // 見本のボタンが出なくても、検索は使える。
  }
}

window.addEventListener("model3d-ready", () => {
  if (App.building) App.loadModel();
});

function renderClaudeStatus(status) {
  document.getElementById("claude-status").textContent = status.claude
    ? `Claude の API に接続する設定です（${status.key_source === "env" ? "環境変数のキー" : "保存したキー"}）。`
    : "API キーが未設定です。Claude を使う所は、説明カードやプログラムの定型文で動きます（画面にその旨を出します）。";
}

async function showClaudeStatus() {
  try {
    const response = await fetch("/api/status");
    renderClaudeStatus(await response.json());
  } catch (error) {
    // 表示できなくても動く。
  }
}

// API キーの保存欄。localhost で開いているときだけ出す。
(() => {
  const form = document.getElementById("key-form");
  const input = document.getElementById("key-input");
  const note = document.getElementById("key-note");
  if (!["localhost", "127.0.0.1"].includes(location.hostname)) return;
  form.hidden = false;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = input.value;
    input.value = "";
    if (!key.trim()) {
      note.textContent = "キーが入っていません。";
      return;
    }
    try {
      const response = await fetch("/api/key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      });
      const body = await response.json();
      if (!response.ok) {
        note.textContent = body.error;
        return;
      }
      renderClaudeStatus(body);
      note.textContent = body.key_source === "env"
        ? "保存しました。環境変数のキーがあるので、そちらを優先して使います。"
        : "保存しました。";
    } catch (error) {
      note.textContent = "保存できませんでした。サーバーが動いているか確かめてください。";
    }
  });
})();

// 建物の質問。「分からない」も答えとして受ける。
const QuestionPanel = (() => {
  const CHOICES = [["yes", "あり"], ["no", "なし"], ["unknown", "分からない"]];
  const FOOT_ART = {
    floor: '<svg viewBox="0 0 60 40" aria-hidden="true"><line x1="4" y1="34" x2="56" y2="34" stroke="#333" stroke-width="2"/><rect x="20" y="12" width="20" height="22" fill="#4f6d8f"/></svg>',
    raised: '<svg viewBox="0 0 60 40" aria-hidden="true"><line x1="4" y1="34" x2="56" y2="34" stroke="#333" stroke-width="2"/><line x1="46" y1="4" x2="46" y2="34" stroke="#333" stroke-width="2"/><rect x="26" y="6" width="20" height="16" fill="#4f6d8f"/></svg>',
    unknown: '<svg viewBox="0 0 60 40" aria-hidden="true"><line x1="4" y1="34" x2="56" y2="34" stroke="#333" stroke-width="2"/><text x="30" y="26" font-size="22" text-anchor="middle" fill="#5a5a60">?</text></svg>',
  };
  const STEP_ART = {
    yes: '<svg viewBox="0 0 60 40" aria-hidden="true"><path d="M4 34 H26 V24 H56" fill="none" stroke="#333" stroke-width="2"/><rect x="30" y="4" width="14" height="20" fill="none" stroke="#4f6d8f" stroke-width="2"/></svg>',
    no: '<svg viewBox="0 0 60 40" aria-hidden="true"><line x1="4" y1="34" x2="56" y2="34" stroke="#333" stroke-width="2"/><rect x="30" y="14" width="14" height="20" fill="none" stroke="#4f6d8f" stroke-width="2"/></svg>',
    unknown: FOOT_ART.unknown,
  };

  function radio(name, value, text, current, art) {
    const label = element("label", undefined, art ? "q-card" : "q-choice");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = `q-${name}`;
    input.value = value;
    input.checked = current === value;
    label.append(input);
    if (art) label.insertAdjacentHTML("beforeend", art);
    label.append(element("span", text));
    return label;
  }

  function group(title, name, choices, current, arts) {
    const box = element("fieldset", undefined, "q-group");
    box.append(element("legend", title));
    choices.forEach(([value, text]) => box.append(radio(name, value, text, current, arts && arts[value])));
    return box;
  }

  function numberField(title, name, value) {
    const label = element("label", undefined, "q-number");
    label.append(title);
    const input = document.createElement("input");
    input.type = "number";
    input.name = `q-${name}`;
    input.min = "1";
    input.value = value || "";
    label.append(input);
    return label;
  }

  function collect(root) {
    const pick = (name) => root.querySelector(`input[name="q-${name}"]:checked`)?.value || "unknown";
    const number = (name) => Number(root.querySelector(`input[name="q-${name}"]`).value) || null;
    return {
      built_year: number("built_year"),
      floors: number("floors"),
      basement: pick("basement"),
      rooms_floor: pick("rooms_floor"),
      slope: pick("slope"),
      vent: pick("vent"),
      cover: pick("cover"),
      panel_foot: pick("panel_foot"),
      door_step: pick("door_step"),
      tr: pick("tr"),
      hv: pick("hv"),
    };
  }

  function render() {
    const { sample } = App.building;
    const answers = sample.answers || {};
    const body = document.getElementById("building-body");
    const questions = element("form", undefined, "questions");

    const first = element("div", undefined, "q-section");
    first.append(element("h3", "建物のあらまし"), numberField("築年（西暦）", "built_year", answers.built_year), numberField("階数", "floors", answers.floors));
    first.append(group("地下はありますか", "basement", CHOICES, answers.basement));
    first.append(group("電気の部屋とポンプの部屋の階", "rooms_floor", [["basement", "地下階"], ["ground", "1階"], ["unknown", "分からない"]], answers.rooms_floor));
    first.append(element("p", "2020年6月の国のガイドラインより前の建物は、ケーブルを通す壁の穴の止水処理が要確認です。", "hint"));

    const second = element("div", undefined, "q-section");
    second.append(element("h3", "外から見える3つ"));
    second.append(group("地下へ降りるスロープや半地下の駐輪場", "slope", CHOICES, answers.slope));
    second.append(group("1階の足元の換気口", "vent", CHOICES, answers.vent));
    second.append(group("歩道ぎわの「東電」「高圧」の蓋（蓋は開けません）", "cover", CHOICES, answers.cover));

    const third = element("div", undefined, "q-section");
    third.append(element("h3", "覚えていれば（模式図から）"));
    third.append(group("盤の足元", "panel_foot", [["floor", "床置き"], ["raised", "架台・壁掛けの上"], ["unknown", "分からない"]], answers.panel_foot, FOOT_ART));
    third.append(group("電気室の扉", "door_step", [["yes", "段差あり"], ["no", "段差なし"], ["unknown", "分からない"]], answers.door_step, STEP_ART));

    const fourth = element("div", undefined, "q-section");
    fourth.append(element("h3", "電気の受け方"));
    fourth.append(group("東京電力の変圧器だけが入っている部屋（借室。東京電力の表示があり、東京電力が鍵を持つ）はありますか", "tr", CHOICES, answers.tr));
    fourth.append(group("マンション側で電気を受ける設備の部屋（キュービクルなど、主任技術者が月次点検する設備）はありますか", "hv", CHOICES, answers.hv));
    fourth.append(element("p", "答えは聞き取りとして扱い、図面や書類で確かめるまで「なし」とはしません。", "hint"));

    const submit = element("button", "この答えで作り直す", "primary");
    submit.type = "submit";
    const grid = element("div", undefined, "q-grid");
    grid.append(first, second, third, fourth);
    questions.append(
      element("p", "どの質問も、部屋や盤を見に行って確かめる必要はありません。電気の部屋、盤の部屋、ポンプの部屋、東京電力の変圧器の部屋には入らず、扉も開けません。外から見えるものも、雨や冠水のときは見に行かず、蓋は開けません。覚えていない所は「分からない」のままで構いません。", "fixed-note strong"),
      grid,
      submit,
    );
    questions.addEventListener("submit", async (event) => {
      event.preventDefault();
      const documented = App.building.sample.answers || {};
      App.answers = { ...collect(questions), hv_documented: documented.hv_documented, feed: documented.feed };
      await App.rebuild();
    });

    const report = document.createElement("textarea");
    report.id = "report-input";
    report.rows = 5;
    report.setAttribute("aria-label", "点検報告書の文");
    const load = element("button", "架空の点検報告書を読み込む");
    load.type = "button";
    load.addEventListener("click", async () => {
      report.value = await (await fetch(App.building.sample.report)).text();
    });
    const read = element("button", "書類を読む", "primary");
    read.type = "button";
    const found = element("div", undefined, "report-found");
    read.addEventListener("click", async () => {
      found.replaceChildren(element("p", "書類を読んでいます。", "hint"));
      const response = await fetch("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: report.value }) });
      const result = await response.json();
      const list = element("ul", undefined, "row-details");
      result.findings.forEach((item) => list.append(element("li", `「${item.word}」→ ${item.item}：${item.effect}`)));
      App.documentRead = result.basement_power;
      if (Object.keys(result.answers || {}).length) App.answers = { ...(App.answers || {}), ...result.answers };
      await App.loadBuilding();
      App.refresh();
      found.replaceChildren(element("p", result.message, "hint"), list);
    });
    const reportBox = element("div", undefined, "q-section q-report");
    reportBox.append(element("h3", "点検報告書など（必須ではありません）"), report, load, read, found);

    const title = sample.custom
      ? `${sample.name}（${sample.kind}）`
      : `${sample.name}　${sample.floors}階建て ${sample.units}戸（${sample.kind}。建物は架空）`;
    body.replaceChildren(element("p", title, "strong"), questions, reportBox);
  }

  return { render };
})();

// 出口 A・B・C の切り替えと、Claude で読みやすく整えるボタン。
const ExitPanel = (() => {
  let current = "a";
  const doc = document.getElementById("exit-doc");
  const text = document.getElementById("exit-text");
  const sheets = document.querySelector(".sheets");
  const note = document.getElementById("polish-note");
  let polished = {};

  let signature = "";

  function source() {
    const exits = App.building?.exits || {};
    const now = `${exits.board}${exits.procedure}`;
    if (now !== signature) {
      signature = now;
      polished = {};
    }
    if (!exits.board) return {};
    return {
      b: `${polished.board || exits.board}\n${exits.board_fixed}`,
      c: `${polished.procedure || exits.procedure}\n\n${exits.procedure_fixed}`,
    };
  }

  function render() {
    document.querySelectorAll("#exit-tabs [data-exit]").forEach((button) => {
      button.classList.toggle("active", button.dataset.exit === current);
    });
    const docs = source();
    const isSheet = current === "a";
    sheets.classList.toggle("is-hidden-screen", !isSheet);
    doc.hidden = isSheet;
    if (!isSheet) text.textContent = docs[current] || "①で場所を選ぶと、ここに出ます。";
  }

  document.getElementById("exit-tabs").addEventListener("click", (event) => {
    const exit = event.target.closest("button")?.dataset.exit;
    if (!exit) return;
    current = exit;
    render();
  });

  document.getElementById("polish-button").addEventListener("click", async () => {
    if (!App.building) {
      note.textContent = "①で場所を選ぶと使えます。";
      return;
    }
    note.textContent = "文を整えています。";
    const items = [
      { key: "board", text: App.building.exits.board },
      { key: "procedure", text: App.building.exits.procedure },
      { key: "top", text: App.building.top_line.notes.join("") },
      ...App.building.memos.flatMap((section, s) => section.items.map((item, i) => ({ key: `memo-${s}-${i}`, text: item.text }))),
    ];
    const response = await fetch("/api/polish", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }) });
    const result = await response.json();
    polished = Object.fromEntries(result.items.map((item) => [item.key, item.text]));
    SheetPanel.applyPolish(polished);
    render();
    note.textContent = result.source === "claude" ? `検査を通った文だけ差し替えました（検査は数字と単位、禁止の語、留保の語と主語）。当日と翌朝の文と免責は差し替えていません。${result.notice}` : result.notice;
  });

  return {
    render,
    reset() {
      polished = {};
      note.textContent = "";
    },
  };
})();

// 別紙だけを渡されても読めるよう、免責の固定の文を同じものにする。
sheetBasis.append(document.querySelector(".disclaimer").cloneNode(true));

HazardMap.init(mapElements.map, {
  picked: pickPoint,
  tap: (mode, direction) => App.setDirection(mode, direction),
});
App.showStage("1");
showClaudeStatus();
loadDemoPoints();
