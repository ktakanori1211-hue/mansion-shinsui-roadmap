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
  landforms: document.getElementById("landform-tags"),
};

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

// 専門用語に、指を置くと読める言葉の意味を付ける（#4。2026-11-04）。文は変えず、語に点線の下線と title を足すだけ。
// 数字は入れない。安全に関わる語は「入らない・触らない」の側で書く。
const TERMS = {
  // 電気保安の専門家のレビュー（2026-11-04）を受けた言い方。安全に関わる語は「入らない・触らない」でそろえる。
  "借室": "東京電力PGの変圧器などが入る部屋。立入は禁止です。浸水時も近づかず、東京電力PGへ連絡します",
  "キュービクル": "受電設備を金属の箱に収めたもの。高い電圧の電気を、建物で使える電気に変えます。開けず、触りません",
  "受電の箱": "受電設備を収めた箱。建物によっては箱ではなく専用の部屋（受変電室）のこともあります",
  "受電設備": "電力会社から電気を受け、建物で使える形にして配る設備。箱型（キュービクル）や専用の部屋の型があります",
  "架台": "盤や機器を床からかさ上げして載せる台",
  "高圧": "電柱の電線や地中のケーブルで受ける、家庭のコンセントよりずっと高い電圧の電気。感電の危険が大きく、近づかず触りません",
  "制御盤": "ポンプを動かすスイッチや部品が入った箱。浸かるとポンプが止まるおそれがあります。浸かった盤は触らず、電気の専門家を呼びます",
  "スイッチ盤": "ポンプや設備に電気を送り、動かすスイッチや部品が入った箱。浸かったら触りません",
  "電気主任技術者": "受電設備の保安を受け持つ国家資格の人。外部の保安会社に委託していることも多い。点検をし、浸水後は電気を戻してよいか確認します",
  "主任技術者": "電気主任技術者のこと。浸水後に電気を戻してよいか、設備を確認します",
  "竣工図": "建物ができたときの図面。その後の改修は載っていないことがあります。管理組合か管理会社が保管していることが多い",
  "逆止弁": "下水が逆向きに建物へ流れ込むのを防ぐ弁。ごみ噛みや劣化で効かないことがあります",
  "合流式": "雨水と汚水を同じ下水管で流す方式。大雨で管がいっぱいになると、下水が逆流したりあふれたりするおそれがあります",
  "東京電力PG": "東京電力パワーグリッド。電柱・電線・変圧器など送配電設備を受け持つ会社。停電や復旧の連絡先です",
  "ピット": "床より下に掘り下げた部分（ポンプの水槽やケーブルの通り道など）。水がたまると危険なので入りません",
  "汲み上げポンプ": "地下の汚水や雨水を、下水管の高さまで汲み上げるポンプ。非常用電源がなければ停電で止まります",
};
const TERM_PATTERN = new RegExp(Object.keys(TERMS).sort((a, b) => b.length - a.length).join("|"), "g");
function withTerms(text, tag = "span", className) {
  const node = element(tag, undefined, className);
  const value = String(text ?? "");
  let last = 0;
  value.replace(TERM_PATTERN, (word, at) => {
    if (at > last) node.append(value.slice(last, at));
    const term = element("abbr", word, "term");
    term.title = TERMS[word];
    term.tabIndex = 0;
    node.append(term);
    last = at + word.length;
    return word;
  });
  if (last < value.length) node.append(value.slice(last));
  return node;
}

function verdictTag(verdict, label) {
  return element("span", label, `tag tag-${verdict}`);
}

function detailItems(row, lead) {
  const list = element("ul", undefined, "row-details");
  if (lead) list.append(element("li", lead));
  [...(row.records || []), ...row.details].forEach((line) => list.append(element("li", line)));
  if (row.confirm_by) {
    const item = element("li", undefined, "row-confirm");
    item.append(element("strong", "誰が確かめるか："), row.confirm_by);
    list.append(item);
  }
  return list;
}

function fold(title, ...nodes) {
  const more = element("details", undefined, "fold");
  more.append(element("summary", title), ...nodes);
  return more;
}

// 立地のカード。一段目は大きな値、色つきの札、太字の一行だけ。判定は札のとおりで、色は地図の色の強調。
function locationCard(row) {
  const accent = row.accent;
  const classes = ["loc-card", `loc-${row.verdict}`];
  if (accent) classes.push(`accent-${accent.kind}`, `accent-${accent.level}`);
  const card = element("article", undefined, classes.join(" "));
  const head = element("div", undefined, "loc-head");
  head.append(element("span", row.label, "loc-label"), verdictTag(row.verdict, row.verdict_label));
  const face = element("div", undefined, "loc-face");
  face.append(element("span", row.value, "loc-value"));
  (accent?.badges || []).forEach((badge) => face.append(element("span", badge, "accent-badge")));
  const foot = element("div", undefined, "loc-foot");
  foot.append(withTerms(row.conclusion, "p", "loc-line"), fold("くわしく", detailItems(row, row.headline)));
  card.append(head, face, foot);
  return card;
}

// 何が止まるかのカード。一段目は札と短い一行で、理由と確かめる人は開いて読む。
// 住民の暮らしで何に関わるか（カードの太字の一行）。判定は言わず、札が判定を表す。
// 出典：ノートの「住民から見た被害」（水・トイレ・風呂・エレベーター・車・暑さ）。新しい数字は足さない。
const LIFE = {
  water: "全戸の水（蛇口・トイレ・風呂）",
  tr: "各戸の電気（照明・冷蔵庫・冷房）",
  ev: "エレベーター（止まると高い階は階段）",
  drain: "トイレと排水を流せるか",
  backflow: "低い階のトイレ・排水口からの逆流",
  lock: "停電のときの玄関の扉と呼び出し",
  park: "駐車場の車",
  power: "共用部の電気（廊下の照明・ポンプ）",
  entry: "電気室へ水が入る道（壁の穴）",
  outside: "道路の水が地下へ入る入口",
  damp: "地下の電気の部屋の湿気",
};
// 暮らしに近いものから並べる。水の入り道は最後にまとめる。
const LIFE_ORDER = ["water", "tr", "ev", "drain", "backflow", "lock", "park", "power", "entry", "outside", "damp"];
function lifeOrder(rows) {
  const rank = (row) => (LIFE_ORDER.includes(row.key) ? LIFE_ORDER.indexOf(row.key) : LIFE_ORDER.length);
  return [...rows].sort((a, b) => rank(a) - rank(b));
}

// 何が止まるかのカード。札と暮らしの一行を太字に、分かったことと、誰が確かめるか（依頼メモの番号）を下に添える。
function screenRow(row, keyRows = []) {
  // ②の頭の「次の3つ」に入っている行は、未確認の中でも答えに効くものとして枠と札で目立たせる（全部が同じ橙に見えないように）。
  const key = keyRows.includes(row.key);
  const article = element("article", undefined, `row row-${row.verdict}${key ? " row-key" : ""}`);
  const head = element("div", undefined, "row-head");
  head.append(verdictTag(row.verdict, row.verdict_label));
  if (key) head.append(element("span", "答えに効く・先に確かめる", "row-key-badge"));
  // サーバーが付けた札（規模の重点など、F-022）。文はサーバーのまま出す。
  (row.badges || []).forEach((badge) => head.append(element("span", badge, "row-badge")));
  const life = withTerms(LIFE[row.key] || row.label, "p", "row-life");
  life.title = row.label;
  article.append(head, life);
  // 未確認の行は、分かったことの代わりに「誰が確かめるか」を表に出す（分かったことは開いて読む）。
  // 確定した行（リスクあり・問題なし）は、分かったことを表に出す。
  const who = row.confirm_short && row.verdict === "unconfirmed";
  if (who) article.append(withTerms(`確かめる：${row.confirm_short}${row.memo_no ? `（依頼メモ${row.memo_no}）` : ""}`, "p", "row-who"));
  else article.append(withTerms(row.summary || row.headline, "p", "row-headline"));
  const lead = who ? row.summary || row.headline : row.summary ? row.headline : "";
  // 8枚のカードに同じ長い文が並ばないよう、畳みの名前は短く「くわしく」にする（#25）。
  article.append(fold("くわしく", detailItems({ ...row, details: [`見たもの：${row.label}`, ...row.details] }, lead)));
  return article;
}

// ③の面の「いくらで、誰が決めるか」。段ごとに、決める場とお金の出どころを大きく、手と桁は開いて読む。
// 値はサーバーの手の表（A4 のおもての表と同じ）のままで、新しい数字は作らない。
const TIERS = ["今すぐ", "工事が要る", "更新と一緒"];
function tierSpan(items) {
  const ranges = items.map((m) => m.range).filter((range) => range && !range.startsWith("—"));
  if (!ranges.length) return "契約・見積りで確かめる";
  const low = ranges[0].split("〜")[0];
  const high = ranges[ranges.length - 1].split("〜")[1];
  return ranges.length === 1 ? ranges[0] : `${low}〜${high || ""}`;
}
function renderCostTiers(building) {
  const measures = SimPanel.byTier(building.measures.filter((m) => m.key !== "power"));
  const lead = document.getElementById("cost-tiers-lead");
  lead.replaceChildren(element("b", "最初の段は、建物の規約と予算によっては理事会と管理費で決められる手から。修繕積立金を使う工事は、その後の段です。"));
  const grid = document.getElementById("cost-tier-grid");
  grid.replaceChildren(
    ...TIERS.map((tier) => {
      const items = measures.filter((m) => m.tier === tier);
      if (!items.length) return null;
      const card = element("article", undefined, `cost-tier tier-${TIERS.indexOf(tier) + 1}`);
      // 決める場とお金の出どころは、桁のある手（申し入れや契約次第の手ではない）から取る。
      const priced = items.filter((m) => m.range && !m.range.startsWith("—"));
      const basis = priced.length ? priced : items;
      // 「理事会で決められる場合がある（建物の規約と予算による）」は、タイルでは短く言い直す（＊の注記を畳みに探しに行かせない）。
      const decisions = [...new Set(basis.map((m) => m.decision.replace("理事会で決められる場合がある（建物の規約と予算による）", "理事会で決められることも（規約・予算しだい）")))];
      const accounts = [...new Set(basis.map((m) => m.account).filter((account) => account && account !== "—"))];
      const list = element("ul", undefined, "row-details");
      items.forEach((m) => list.append(element("li", `${m.label}：${m.range}`)));
      card.append(
        element("p", tier, "cost-tier-name"),
        element("p", tierSpan(items), "cost-tier-big"),
        element("p", `決める場：${decisions[0]}${decisions.length > 1 ? " ほか" : ""}`, "cost-tier-line"),
        element("p", `お金：${accounts[0] || "契約による"}`, "cost-tier-line"),
        fold(`${items.length}つの手と桁を開く`, list, element("p", "理事会で決められるか、管理費か修繕積立金かは、建物の規約と予算によります。管理会社に規約・予算書・総会の議事録で確かめてもらいます。桁は目安で、見積りではありません。", "hint")),
      );
      return card;
    }).filter(Boolean),
  );
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

// 「何が分かれば答えが出るか・誰に頼むか」（サーバーの top_line.steps）。②の頭と A4 のおもての頭で同じものを出す。
function answerSteps(building, className) {
  const steps = building.top_line.steps || [];
  const list = element("ol", undefined, className || "answer-steps");
  steps.forEach((step) => {
    const item = element("li");
    item.append(withTerms(step.what, "b"), withTerms(`頼む先：${step.who}${step.memo_no ? `（依頼メモ${step.memo_no}）` : ""}`, "span", "answer-who"));
    list.append(item);
  });
  return list;
}

// A4 と共有に出す住所は町丁まで（番地はピンの位置から来ることがあり、建物の住所とは限らないため）。
function townLabel(label) {
  return String(label || "")
    .replace(/[0-9０-９一二三四五六七八九十〇百千]+番(?!町)(地)?.*$/, "")
    .replace(/[0-9０-９一二三四五六七八九十〇百千]+号.*$/, "")
    .replace(/(丁目)[0-9０-９\-－−ー].*$/, "$1")
    .replace(/[0-9０-９]+[\-－−ー][0-9０-９].*$/, "")
    .trim();
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
  // 見本でない建物は、図面を入れるか近い形を選ぶまで図面と3Dを出さない。
  shapeChosen: false,

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
      high_directions: this.locationState.location.reading.high_directions,
      basin: this.locationState.location.reading.basin,
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
    this.shapeChosen = Boolean(this.sampleId);
    ["stage3-cost", "sim-card", "consult-card", "cost-tiers"].forEach((id) => {
      document.getElementById(id).hidden = false;
    });
    this.showShape();
    document.getElementById("stage2-empty").hidden = true;
    document.getElementById("chat-toggle").hidden = !document.getElementById("chat").hidden;
    document.getElementById("plan-stage").hidden = true;
    document.getElementById("plan-message").textContent = "";
    document.getElementById("plan-rooms").replaceChildren();
    document.getElementById("pin-card").hidden = true;
    document.getElementById("consult-body").replaceChildren();
    ExitPanel.reset();
    QuestionPanel.reset();
    QuestionPanel.render();
    PlanPanel.reset();
    PlanPanel.offerSample();
    SimPanel.reset();
    ModelPanel.renderControls();
    this.loadModel();
    this.refresh();
  },

  showShape() {
    ["plan-card", "model-card", "model-lower", "step-result", "step-building", "top-banner"].forEach((id) => {
      document.getElementById(id).hidden = !this.shapeChosen;
    });
    document.getElementById("type-chooser").hidden = this.shapeChosen;
    this.fitStage2();
    window.dispatchEvent(new Event("resize"));
    window.dispatchEvent(new Event("building-shown"));
  },

  async chooseShape(type) {
    this.answers = { ...(this.answers || {}), type };
    this.shapeChosen = true;
    await this.rebuild();
    this.showShape();
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

  // 設備図で確かめた結果（F-017・F-021）。一つの種類に absent と upper が同時に入らないよう、外す key と入れる key を一度に替える。
  async setConfirmedKeys(remove, add) {
    const dropped = this.confirmed.filter((item) => !remove.includes(item));
    this.confirmed = [...new Set([...dropped, ...add])];
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
    document.getElementById("top-banner-steps").replaceWith(Object.assign(answerSteps(building, "answer-steps top-banner-steps"), { id: "top-banner-steps" }));
    document.getElementById("top-banner-notes").textContent = building.top_line.notes.join("");
    document.getElementById("top-banner-dir").textContent = building.direction_line ? `${building.direction_line}（向きは答えと地図の目安で、測ったものではありません）` : "";
    PlanPanel.renderDirection();
    PlanPanel.renderAbsent();
    document.getElementById("legal-safety").textContent = this.disclaimerText();
    const body = document.getElementById("result-body");
    const grid = element("div", undefined, "result-grid");
    const keyRows = (building.top_line.steps || []).map((step) => step.key);
    const ordered = lifeOrder(building.equipment);
    // 答えに効く行を先に、残りは暮らしに近い順のまま。
    grid.append(...[...ordered.filter((row) => keyRows.includes(row.key)), ...ordered.filter((row) => !keyRows.includes(row.key))].map((row) => screenRow(row, keyRows)));
    // 外の街より建物の復旧が長くなりうる差（ノートの「取り残される」）。数字は足さない。
    const lead = element("p", undefined, "result-lead");
    lead.append(element("b", "外の道路が乾いても、館内の水と電気は戻らないことがあります。"));
    body.replaceChildren(lead, grid);
    if (building.statements.length) {
      body.append(element("p", `聞き取りとして入れた話：${building.statements.join("／")}（図面で確かめるまで未確認です）`, "hint"));
    }
    this.applyScenario();
    window.Model3D?.updateTags?.();
    SimPanel.render();
    SheetPanel.render();
    renderCostTiers(building);
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
      location: this.locationState.location.rows.map((row) => ({ label: row.label, verdict: row.verdict_label, summary: row.summary, confirm_short: row.confirm_short })),
      equipment: this.building.equipment.map((row) => ({ label: row.label, verdict: row.verdict_label, summary: row.summary, confirm_by: row.confirm_by })),
      places: this.building.sample.pins.map((pin) => ({ key: pin.key, title: pin.title, how_water: pin.how_water, who: pin.who })),
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
    document.getElementById("why-bar").classList.toggle("is-hidden", this.stage !== "1" || !this.locationState);
    document.getElementById("hero").classList.toggle("is-hidden", Boolean(this.locationState) || this.stage === "materials");
    if (this.stage === "materials") Materials.load();
    HazardMap.refresh();
    this.fitStage2();
    window.dispatchEvent(new Event("resize"));
  },

  // 第2段階の平面図と模型を、スクロールなしで押しながら見られる高さにそろえる。
  fitStage2() {
    if (this.stage !== "2") return;
    const top = document.querySelector(".stage2-grid").getBoundingClientRect().top + window.scrollY;
    // 免責の帯は貼り付けずページの下に出すので、高さから引かない。
    // 図面と3Dを読める大きさで見せるため、画面が低くても 640px は取る（少しスクロールしてよい）。
    document.documentElement.style.setProperty("--stage2-room", `${Math.max(640, window.innerHeight - top - 10)}px`);
  },
};
window.App = App;

// 土地の弱さの札。文より先に、どこに色が付いているかを見せる。判定の札は変えない。
const LAND_NAMES = [["flood", "洪水"], ["surge", "高潮"], ["inland", "内水"], ["ground", "土地"], ["record", "記録"]];

function landChips(rows) {
  return LAND_NAMES.map(([key, name]) => {
    const row = rows.find((item) => item.key === key);
    return row && { row, text: /記録|標高/.test(row.value) ? row.value : `${name} ${row.value}` };
  }).filter(Boolean);
}

function renderLocation(state) {
  const { site, location } = state;
  locationBody.replaceChildren(...location.rows.map(locationCard), fold("札の見方", verdictLegend()));
  document.getElementById("legal-basis").textContent = location.basis_note;
  document.getElementById("legal-basis-box").hidden = false;
  sheetAddress.textContent = `住所：${townLabel(site.label)}`;
  sheetLocation.replaceChildren(
    sheetTable(location.rows),
    element(
      "p",
      `${site.basis === "representative" ? "町丁の代表点の値で、建物の位置の値ではありません。" : "ピンの位置の値です。"}色がないことは安全という意味ではありません。条件と出典は別紙に書いています。`,
      "sheet-pointer",
    ),
  );
  sheetBasisAddress.textContent = `住所：${townLabel(site.label)}`;
  sheetBasisRows.replaceChildren(element("p", location.basis_note, "basis-note"), ...location.rows.map(basisRow));
  sheetBasis.hidden = false;
  HazardMap.show(state, mapElements, movePin);
  // ピンの点にどれかの地図の色があるときは「色がない所も」と言い、画面と食い違わないようにする（#16）。
  const pinColored = location.reading.hazards.some((hazard) => hazard.status === "color");
  document.querySelector(".map-fixed").textContent = pinColored
    ? "色がない所も、安全という意味ではありません。斜線はデータが取れていない所です。"
    : "地図に色がないことは、安全という意味ではありません。斜線はデータが取れていない所です。";
  TerrainChart.render(document.getElementById("terrain"), location.reading, site);
  App.locationState = state;
  Scenes.render(state);
  App.showStage(App.stage);
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
      candidatesBox.hidden = true;
      searchMessage.hidden = true;
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

// ③の「いくらで、誰が決めるか」から、畳みの中の補助と相談へ直接行く（#33。2026-11-04）。
document.querySelectorAll("[data-open-cost]").forEach((button) => {
  button.addEventListener("click", () => {
    const fold = document.getElementById("stage3-cost");
    fold.open = true;
    document.getElementById(button.dataset.openCost)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

async function loadDemoPoints() {
  try {
    const response = await fetch("/api/demo-points");
    const points = await response.json();
    const buttons = document.getElementById("demo-buttons");
    points.forEach((point) => {
      const [name, place] = point.label.replace(/^見本/, "").split("／");
      const button = element("button", undefined, "demo-button");
      button.append(element("b", `見本${name.slice(0, 1)}`), element("span", place));
      button.type = "button";
      button.title = `${point.label}（${point.kind}）`;
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

// 近い形の選択肢。図は見本の平面図を小さく見せる。
const SHAPES = [
  ["a", "板状で、地下に機器", "中〜大規模。地下に電気室やポンプ室がある"],
  ["b", "小規模で、1階に機器", "地下がなく、電気やポンプの部屋が1階にある"],
  ["c", "タワーで、地下に機器", "20階建て以上。地下に受変電室や発電機がある"],
];

function renderShapeOptions() {
  const box = document.getElementById("type-options");
  box.replaceChildren(
    ...SHAPES.map(([type, name, note]) => {
      const button = element("button", undefined, "type-option");
      button.type = "button";
      const image = document.createElement("img");
      image.src = `samples/plan_${type}.png`;
      image.alt = "";
      button.append(image, element("strong", name), element("span", note));
      button.addEventListener("click", () => App.chooseShape(type));
      return button;
    }),
  );
}
renderShapeOptions();

document.getElementById("type-file").addEventListener("change", async (event) => {
  const chosen = event.target.files[0];
  if (!chosen) return;
  if (!window.confirm("この図面は回答を作るために Anthropic の API へ送ります（API キーを設定しているときだけ）。続けますか？")) return;
  App.shapeChosen = true;
  App.showShape();
  PlanPanel.load(await chosen.arrayBuffer(), chosen.type, null);
});

window.addEventListener("model3d-ready", () => {
  if (App.building) App.loadModel();
});

// チャットの送り先を、送る前に出す（F-038）。表示を替えるだけで API は呼ばない。
const CHAT_ROUTE_TEXT = {
  claude: "送った質問と、この画面の住所・答え・判定は Anthropic の API を通ります。図面と書類の中身は送りません。",
  none: "AI を通さず、説明カードで答えます",
};

function renderChatRoute(status) {
  const route = document.getElementById("chat-route");
  if (!route) return;
  route.textContent = status.claude ? CHAT_ROUTE_TEXT.claude : CHAT_ROUTE_TEXT.none;
  route.classList.toggle("chat-route-api", Boolean(status.claude));
}

function renderClaudeStatus(status) {
  renderChatRoute(status);
  const statusText = document.getElementById("claude-status");
  const toggle = document.getElementById("key-toggle");
  const keyForm = document.getElementById("key-form");
  const local = ["localhost", "127.0.0.1"].includes(location.hostname);
  if (status.claude) {
    statusText.textContent = "";
    toggle.textContent = status.key_source === "env" ? "🟢 Claude API 接続済み（環境変数）" : "🟢 Claude API 接続済み（キーを変更）";
    toggle.hidden = false;
    toggle.disabled = !local || status.key_source === "env";
    keyForm.hidden = true;
  } else {
    statusText.textContent = "⚪ APIキーなし（説明カードで動きます）";
    toggle.textContent = "APIキーを設定";
    toggle.hidden = !local;
    toggle.disabled = false;
    keyForm.hidden = true;
  }
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
  document.getElementById("key-toggle").addEventListener("click", () => {
    form.hidden = !form.hidden;
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = input.value;
    input.value = "";
    if (!key.trim()) {
      note.textContent = "キーが入っていません。";
      note.classList.add("show");
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
        note.classList.add("show");
        return;
      }
      note.classList.add("show");
      renderClaudeStatus(body);
      form.hidden = false;
      note.textContent = body.key_source === "env"
        ? "保存しました。環境変数のキーがあるので、そちらを優先して使います。"
        : "保存しました。";
    } catch (error) {
      note.textContent = "保存できませんでした。サーバーが動いているか確かめてください。";
      note.classList.add("show");
    }
  });
})();

// 点検報告書・修繕履歴の PDF から文字を取り出す（F-042）。この画面の中で PDF.js を使うだけで、どこへも送らない。
// 書類の規則は行の頭（「指摘」）や全角の「：」で読むので、行を作り直し、全体には NFKC をかけない。
// 「⾞」のような康熙部首だけ、普通の字にそろえる。文字のない画像の PDF は読まない（API がある時だけの部分は作らない）。
async function reportPdfText(buffer) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";
  const pdf = await pdfjsLib.getDocument({ data: buffer.slice(0) }).promise;
  const pages = [];
  for (let number = 1; number <= pdf.numPages; number += 1) {
    const page = await pdf.getPage(number);
    const content = await page.getTextContent();
    const rows = [];
    content.items
      .filter((item) => item.str)
      .forEach((item) => {
        const x = item.transform[4];
        const y = item.transform[5];
        const size = Math.abs(item.transform[3]) || 10;
        let row = rows.find((line) => Math.abs(line.y - y) < size * 0.5);
        if (!row) {
          row = { y, parts: [] };
          rows.push(row);
        }
        row.parts.push({ x, str: item.str });
      });
    // PDF の座標は上へ向かって大きくなるので、上の行から並べる。
    rows.sort((a, b) => b.y - a.y);
    const text = rows
      .map((row) => row.parts.sort((a, b) => a.x - b.x).map((part) => part.str).join("").trim())
      .filter(Boolean)
      .join("\n");
    if (text) pages.push(text);
  }
  return pages.join("\n").replace(/[\u2E80-\u2EFF\u2F00-\u2FDF]/g, (char) => char.normalize("NFKC"));
}
window.reportPdfText = reportPdfText;

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
    box.append(withTerms(title, "legend"));
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

  // 足した質問（F-012・F-013・F-022）。選ばれていなければ答えに入れず、サーバーの既定のまま（見本Cの貯留タンクと発電機など）にする。
  const SCALE_CHOICES = [["small", "小さめ"], ["mid", "中くらい"], ["large", "大きめ"], ["unknown", "分からない"]];
  const ENTRANCE_CHOICES = [["yes", "段差あり"], ["no", "段差なし"], ["unknown", "分からない"]];
  // 高さの欄（F-024）。名前はサーバーの HEIGHT_FIELDS と同じ。入れた値をそのまま出すだけで、計算しない。
  const HEIGHT_FIELDS = [
    ["panel_bottom", "給水ポンプの制御盤の下の端（床から）"],
    ["pump_floor", "ポンプの部屋の床（外の地面との差）"],
    ["elec_floor", "電気の部屋の床（外の地面との差）"],
  ];
  const HEIGHT_SOURCES = [["drawing", "竣工図"], ["measured", "実測"], ["hearing", "聞き取り"]];

  // 0cm や外の地面より低い床（負の値）も入れられるよう、下限を付けない。
  function heightField(key, label, item) {
    const box = element("div", undefined, "q-height");
    const field = element("label", undefined, "q-number");
    field.append(label);
    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.name = `q-height-${key}`;
    input.value = item && typeof item.cm === "number" ? String(item.cm) : "";
    const unit = element("span", undefined, "q-height-input");
    unit.append(input, " cm");
    field.append(unit);
    const source = document.createElement("select");
    source.name = `q-height-source-${key}`;
    source.setAttribute("aria-label", `${label}の出どころ`);
    source.append(new Option("出どころを選ぶ", ""), ...HEIGHT_SOURCES.map(([value, text]) => new Option(text, value)));
    const given = item && item.source;
    if (given && !HEIGHT_SOURCES.some(([value]) => value === given)) source.append(new Option(given, given));
    source.value = given || "";
    box.append(field, source);
    return box;
  }

  // 空欄は飛ばす。全部空欄でも {} を送り、前に入れた値を消せるようにする。
  function collectHeights(root) {
    const heights = {};
    HEIGHT_FIELDS.forEach(([key]) => {
      const raw = root.querySelector(`input[name="q-height-${key}"]`)?.value.trim() || "";
      if (raw === "") return;
      const cm = Number(raw);
      if (!Number.isFinite(cm)) return;
      const source = root.querySelector(`select[name="q-height-source-${key}"]`)?.value;
      heights[key] = source ? { cm, source } : { cm };
    });
    return heights;
  }

  function collect(root) {
    const pick = (name) => root.querySelector(`input[name="q-${name}"]:checked`)?.value || "unknown";
    const optional = (name) => root.querySelector(`input[name="q-${name}"]:checked`)?.value;
    const number = (name) => Number(root.querySelector(`input[name="q-${name}"]`).value) || null;
    return {
      entrance_step: optional("entrance_step"),
      tank: optional("tank"),
      generator: optional("generator"),
      scale: optional("scale"),
      heights: collectHeights(root),
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

  // 書類で読んだ語と質問の結びつき（F-043）。サーバーは語と答えの key を結ばないので、画面の側の表で結ぶ。
  // API がある時だけの「対応表にない語のゆれを読む」部分は作らない。
  // match は答えの値ごとの語。地中と読んだ答えに「架空」の語を結ばないよう、値で分ける。
  const DOC_QUESTIONS = {
    tr: { name: "東京電力の変圧器だけが入っている部屋", match: { any: /東京電力の変圧器/ } },
    hv: { name: "マンション側で電気を受ける設備の部屋", match: { no: /受電設備なし|選任していない/, yes: /マンション側の受電設備/ } },
    rooms_floor: { name: "電気の部屋とポンプの部屋の階", match: { any: /受電設備：地下|受電の箱は地下|電気室・主開閉器盤の階/ } },
    panel_foot: { name: "盤の足元", match: { floor: /床置き|直置き/, raised: /壁掛け|架台/ } },
    feed: { name: "電気の引込み（地中か空中か）", match: { underground: /地中/, overhead: /架空|空中/ } },
    // ノートの機能で足した、書類で入る答え（F-013・F-014・F-017・F-019・F-021）。
    tank: { name: "雨水を地下にためる槽（貯留槽）", match: { any: /貯留槽/ } },
    generator: { name: "非常用発電機", match: { any: /非常用発電機/ } },
    tank_valve: { name: "貯留槽の導入管の止水バルブ", match: { any: /止水バルブ/ } },
    damp: { name: "点検報告書の湿気・漏水の指摘", match: { yes: /湿気|漏水/, no: /指摘事項/ } },
    sealed: { name: "止水施工済み（止水処理済み）の記載", match: { any: /止水施工済|止水処理済/ } },
    homes_feed: { name: "各戸の電気の受け方（高圧一括受電）", match: { any: /高圧一括受電/ } },
  };
  // 書類の答えの key のうち、別の質問の key に含めるもの。
  const DOC_KEY_OF = { hv_documented: "hv", homes_feed_documented: "homes_feed" };
  const questionOf = (key) => DOC_KEY_OF[key] || key;

  function docMatches(key, value, text) {
    const match = DOC_QUESTIONS[key].match;
    const pattern = match[value] || match.any;
    return Boolean(pattern && pattern.test(text));
  }
  let draft = "";
  let doc = null;
  // 下の段（管理会社や技術者が確かめる項目）を開いたかを、作り直したあとも保つ。
  let expertOpen = false;

  // 答えの key（hv_documented は hv に含める）ごとに、どの語から読んだかを結ぶ。
  function linkFindings(result) {
    // 「分からない」と読んだものは、書類で埋まったことにしない。
    const keys = Object.entries(result.answers || {})
      .filter(([, value]) => value !== "unknown")
      .map(([key]) => questionOf(key))
      .filter((key) => DOC_QUESTIONS[key]);
    const answers = result.answers || {};
    const findings = result.findings.map((item) => ({ ...item, keys: [...new Set(keys)].filter((key) => docMatches(key, answers[key], `${item.word}${item.item}`)) }));
    [...new Set(keys)].forEach((key) => {
      if (!findings.some((item) => item.keys.includes(key))) {
        findings.push({ word: "書類の記載", item: DOC_QUESTIONS[key].name, effect: "質問の答えに入れました", keys: [key] });
      }
    });
    return findings;
  }

  function rejectedKeys() {
    const rejected = new Set();
    doc.links.forEach((item, index) => {
      if (doc.off.has(index)) item.keys.forEach((key) => rejected.add(key));
    });
    return rejected;
  }

  // 書類で埋まっている質問の key と、その語。
  function filledByDoc() {
    if (!doc) return {};
    const rejected = rejectedKeys();
    const filled = {};
    doc.links.forEach((item) => {
      item.keys.forEach((key) => {
        if (rejected.has(key)) return;
        filled[key] = [...(filled[key] || []), item.word];
      });
    });
    return filled;
  }

  // 外した key を答えから除き（読む前の答えへ戻し）、作り直す。/api/report はもう一度呼ばない。
  async function applyDoc() {
    const rejected = rejectedKeys();
    const answers = { ...(App.answers || {}) };
    Object.entries(doc.result.answers || {}).forEach(([key, value]) => {
      const question = questionOf(key);
      if (!rejected.has(question)) {
        answers[key] = value;
      } else if (doc.before && key in doc.before) {
        answers[key] = doc.before[key];
      } else {
        delete answers[key];
      }
    });
    App.answers = answers;
    App.documentRead = Boolean(doc.result.basement_power) && !rejected.has("rooms_floor");
    await App.loadBuilding();
    App.refresh();
    render();
  }

  function renderFound(found) {
    const list = element("ul", undefined, "row-details report-links");
    doc.links.forEach((item, index) => {
      const off = doc.off.has(index);
      const line = element("li", undefined, off ? "doc-off" : "");
      line.append(element("span", `「${item.word}」→ ${item.item}：${item.effect}`));
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.checked = off;
      toggle.addEventListener("change", async () => {
        if (toggle.checked) doc.off.add(index);
        else doc.off.delete(index);
        await applyDoc();
      });
      const wrap = element("label", undefined, "doc-wrong");
      wrap.append(toggle, "この結びつきは違う");
      line.append(" ", wrap);
      if (!item.keys.length) line.append(element("small", "（質問の答えには入れていない語です）", "doc-nokey"));
      list.append(line);
    });
    found.replaceChildren(element("p", doc.result.message, "hint"), list);
  }

  // 書類で埋まった質問は灰色にして下へ寄せ、書類で埋まらない質問を上に並べる。外せば元に戻る。
  function markDocQuestions(grid, root = grid) {
    const filled = filledByDoc();
    const keys = Object.keys(filled);
    if (!keys.length) return;
    const section = element("div", undefined, "q-section q-doc-section");
    section.append(element("h3", "書類で読んだ項目"));
    keys.forEach((key) => {
      const words = `書類で読みました（${filled[key].map((word) => `「${word}」`).join("")}の語）`;
      const undo = element("button", "この読みを外す", "doc-undo");
      undo.type = "button";
      undo.addEventListener("click", async () => {
        doc.links.forEach((item, index) => {
          if (item.keys.includes(key)) doc.off.add(index);
        });
        await applyDoc();
      });
      const box = root.querySelector(`input[name="q-${key}"]`)?.closest("fieldset");
      if (box) {
        box.classList.add("q-from-doc");
        box.querySelectorAll("input").forEach((input) => {
          input.disabled = true;
        });
        box.append(element("p", words, "q-doc-note"), undo);
        section.append(box);
      } else {
        const line = element("div", undefined, "q-group q-from-doc");
        line.append(element("p", `${DOC_QUESTIONS[key].name}：${words}`, "q-doc-note"), undo);
        section.append(line);
      }
    });
    grid.append(section);
  }

  function render() {
    const { sample } = App.building;
    const answers = sample.answers || {};
    const body = document.getElementById("building-body");
    const questions = element("form", undefined, "questions");

    // 2段に分ける（2026-11-04）。上の段は住民や理事長が外から見て答えられる項目だけ。
    // 下の段（借室・受電設備・盤の高さなど）は、管理会社や技術者が図面・現地で確かめる項目として畳んでおく。
    const outside = element("div", undefined, "q-section");
    outside.append(element("h3", "建物のあらまし"), numberField("階数", "floors", answers.floors), numberField("築年（西暦）", "built_year", answers.built_year));
    outside.append(group("地下の階はありますか", "basement", CHOICES, answers.basement));

    const second = element("div", undefined, "q-section");
    second.append(element("h3", "外から見える3つ"));
    second.append(group("地下へ降りるスロープや半地下の駐輪場", "slope", CHOICES, answers.slope));
    second.append(group("歩道ぎわの「東電」「高圧」の蓋（蓋は開けません）", "cover", CHOICES, answers.cover));
    second.append(group("1階の出入口に、道路からの段差がありますか", "entrance_step", ENTRANCE_CHOICES, answers.entrance_step));

    // 規模（小さめ・中くらい・大きめ）は区切りが仮の目安で、住民によって答えが変わるので、下の段で管理会社が総戸数から答える。
    // 足元の換気口（給気ガラリなど）は住民には見分けにくく、浸水の入口にもなるので、下の段で確かめる。
    const vents = element("div", undefined, "q-section");
    vents.append(element("h3", "規模と換気口（管理会社が総戸数と現地で答える）"));
    vents.append(group("建物の規模（総戸数のおおよそ）", "scale", SCALE_CHOICES, answers.scale));
    vents.append(group("1階の足元の換気口（給気ガラリなど。水が入る口になります）", "vent", CHOICES, answers.vent));

    const first = element("div", undefined, "q-section");
    first.append(element("h3", "部屋の階"));
    first.append(group("電気の部屋とポンプの部屋の階", "rooms_floor", [["basement", "地下階"], ["ground", "1階"], ["upper", "2階以上"], ["unknown", "分からない"]], answers.rooms_floor));
    first.append(element("p", "2020年6月の国のガイドラインより前の建物は、ケーブルを通す壁の穴の止水処理が要確認です。", "hint"));

    const third = element("div", undefined, "q-section");
    third.append(element("h3", "盤と扉（模式図から）"));
    third.append(group("盤の足元", "panel_foot", [["floor", "床置き"], ["raised", "架台・壁掛けの上"], ["unknown", "分からない"]], answers.panel_foot, FOOT_ART));
    third.append(group("電気室の扉", "door_step", [["yes", "段差あり"], ["no", "段差なし"], ["unknown", "分からない"]], answers.door_step, STEP_ART));

    // 足した質問（F-012・F-013）。見本Cの貯留タンクと発電機は、答えがなければサーバーの既定（あり）のまま見せる。
    const tower = sample.id === "c" && !sample.custom;
    const extra = element("div", undefined, "q-section");
    extra.append(element("h3", "槽・発電機"));
    extra.append(group("雨水を地下にためる槽（貯留槽）はありますか", "tank", CHOICES, answers.tank ?? (tower ? "yes" : undefined)));
    extra.append(group("非常用発電機はありますか", "generator", CHOICES, answers.generator ?? (tower ? "yes" : undefined)));

    const heightBox = element("div", undefined, "q-section");
    heightBox.append(element("h3", "高さ（分かれば・cm）"));
    HEIGHT_FIELDS.forEach(([key, label]) => heightBox.append(heightField(key, label, (answers.heights || {})[key])));
    heightBox.append(element("p", "入れた値をそのまま表と3Dに出すだけで、浸かるかどうかは計算しません。空欄のままで構いません。", "hint"));
    const given = App.building.heights || [];
    if (given.length) heightBox.append(element("p", given.map((item) => `${item.label}：${item.text}`).join("／"), "q-height-given"));

    const fourth = element("div", undefined, "q-section");
    fourth.append(element("h3", "電気の受け方"));
    fourth.append(group("東京電力の変圧器だけが入っている部屋（借室。東京電力の表示があり、東京電力が鍵を持つ）はありますか", "tr", CHOICES, answers.tr));
    fourth.append(group("マンション側で電気を受ける設備の部屋（キュービクルなど、主任技術者が月次点検する設備）はありますか", "hv", CHOICES, answers.hv));
    fourth.append(element("p", "答えは聞き取りとして扱い、図面や書類で確かめるまで「なし」とはしません。", "hint"));

    const submit = element("button", "この答えで作り直す", "primary");
    submit.type = "submit";
    const grid = element("div", undefined, "q-grid q-grid-residents");
    grid.append(outside, second);
    const expertGrid = element("div", undefined, "q-grid");
    expertGrid.append(first, vents, third, fourth, extra, heightBox);
    const expert = element("details", undefined, "q-expert");
    expert.open = expertOpen;
    expert.addEventListener("toggle", () => {
      expertOpen = expert.open;
    });
    expert.append(element("summary", "ここから下は、管理会社や技術者が図面・現地で確かめる項目です（分からないままでOK）"), expertGrid);
    questions.append(
      element("p", "住民・理事長が外から見て答えられる項目です。分かる所だけで構いません。", "q-lead"),
      grid,
      expert,
      element("p", "どの質問も、部屋や盤を見に行って確かめる必要はありません。電気の部屋、盤の部屋、ポンプの部屋、東京電力の変圧器の部屋には入らず、扉も開けません。外から見えるものも、雨や冠水のときは見に行かず、蓋は開けません。覚えていない所は「分からない」のままで構いません。", "fixed-note strong"),
      submit,
    );
    questions.addEventListener("submit", async (event) => {
      event.preventDefault();
      // 書類で入った答え（hv_documented、feed、damp、sealed、tank_valve、homes_feed など）と、選んだ近い形（type）を残す。
      // 欄のある答えは欄の値で上書きし、選ばれていない欄（undefined）は上書きしない。
      const documented = App.building.sample.answers || {};
      const fresh = Object.fromEntries(Object.entries(collect(questions)).filter(([, value]) => value !== undefined));
      App.answers = { ...documented, ...fresh };
      await App.rebuild();
    });

    const report = document.createElement("textarea");
    report.id = "report-input";
    report.rows = 5;
    report.setAttribute("aria-label", "点検報告書の文");
    report.value = draft;
    report.addEventListener("input", () => {
      draft = report.value;
    });
    const load = element("button", "架空の点検報告書を読み込む");
    load.type = "button";
    load.addEventListener("click", async () => {
      report.value = await (await fetch(App.building.sample.report)).text();
      draft = report.value;
    });
    const read = element("button", "書類を読む", "primary");
    read.type = "button";
    const found = element("div", undefined, "report-found");
    read.addEventListener("click", async () => {
      found.replaceChildren(element("p", "書類を読んでいます。", "hint"));
      const response = await fetch("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: report.value }) });
      const result = await response.json();
      // 読む前の答えを残し、結びつきを外したときはそこへ戻す。二度目に読んだときも、最初に読む前の答えへ戻す。
      const before = doc ? doc.before : App.answers ? { ...App.answers } : null;
      doc = { text: report.value, result, before, off: new Set(), links: linkFindings(result) };
      await applyDoc();
    });
    if (doc) renderFound(found);
    // PDF の受け口（F-042）。取り出した文字は貼り付け欄に入れるだけで、読むのは「書類を読む」を押したとき。
    const pdfInput = document.createElement("input");
    pdfInput.type = "file";
    pdfInput.accept = "application/pdf";
    pdfInput.id = "report-file";
    const pdfLabel = element("label", "PDF から文字を入れる（点検報告書・修繕履歴）", "plan-file-label report-file-label");
    pdfLabel.htmlFor = "report-file";
    const pdfNote = element("p", "", "hint report-file-note");
    pdfInput.addEventListener("change", async () => {
      const chosen = pdfInput.files[0];
      pdfInput.value = "";
      if (!chosen) return;
      pdfNote.textContent = "PDF から文字を取り出しています（この画面の中で取り出し、まだどこへも送りません）。";
      try {
        const text = await reportPdfText(await chosen.arrayBuffer());
        if (!text.trim()) {
          pdfNote.textContent = "文字を取り出せませんでした。文字のある PDF を入れるか、文を貼り付けてください。";
          return;
        }
        report.value = text;
        draft = text;
        pdfNote.textContent = `「${chosen.name}」の文字を貼り付け欄に入れました。合っているか見てから「書類を読む」を押してください。`;
      } catch (error) {
        pdfNote.textContent = `PDF を読めませんでした：${error.message}`;
      }
    });
    // 点検報告書の欄は、管理会社から受け取ったときに使うので畳んでおく（読んだ結果があれば開いたまま）。
    const reportBox = element("details", undefined, "q-section q-report");
    reportBox.open = Boolean(doc) || Boolean(draft);
    reportBox.append(element("summary", "点検報告書や修繕履歴を受け取ったら、ここに入れる（必須ではありません）"), report, load, read, pdfLabel, pdfInput, pdfNote, found);
    // 書類で読んだ項目（借室・受電設備など）は、住民の段ではなく下の段に寄せる。
    markDocQuestions(expertGrid, questions);

    const title = sample.custom
      ? `${sample.name}（${sample.kind}）`
      : `${sample.name}　${sample.floors}階建て ${sample.units}戸（${sample.kind}。建物は架空）`;
    body.replaceChildren(element("p", title, "strong"), questions, reportBox);
  }

  return {
    render,
    reset() {
      draft = "";
      doc = null;
    },
  };
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
    document.getElementById("sheet-tabs").classList.toggle("is-hidden-screen", !isSheet);
    document.getElementById("sheet-tab-note").classList.toggle("is-hidden-screen", !isSheet);
    doc.hidden = isSheet;
    if (!isSheet) text.textContent = docs[current] || "①で場所を選ぶと、ここに出ます。";
  }

  // 渡す相手ごとの紙のタブ（2026-11-04）。選んだ紙だけを画面に大きく出し、印刷もその紙だけにする。
  const SHEET_NOTES = {
    board: ["理事会へ（表裏1枚）", "理事会に配る表裏1枚です。両面に印刷し、防災のファイルに綴じます。"],
    memo: ["管理会社へ（依頼メモ）", "管理会社に渡し、未確認の項目を確かめてもらう紙です。答えが返ったら、②の質問に入れ直します。"],
    engineer: ["電気主任技術者へ（確認表）", "管理会社を通じて電気主任技術者に渡す紙です。住民向けの面には出さない項目です。"],
    extra: ["別紙", "表裏1枚のくわしい版と、値の条件と出典です。理事会で聞かれたときに添えます。"],
    all: ["全部", "すべての紙を続けて並べます。印刷すると全部の紙が出ます。"],
  };
  let shown = "board";
  function showSheets(key) {
    shown = key;
    sheets.dataset.show = key;
    document.querySelectorAll("#sheet-tabs [data-sheets]").forEach((button) => {
      const on = button.dataset.sheets === key;
      button.classList.toggle("active", on);
      button.setAttribute("aria-selected", String(on));
    });
    document.getElementById("sheet-tab-note").textContent = SHEET_NOTES[key][1];
    document.getElementById("print-button").textContent = key === "all" ? "全部の紙を印刷（PDFに保存もできます）" : `「${SHEET_NOTES[key][0]}」を印刷（PDFに保存もできます）`;
  }
  document.getElementById("sheet-tabs").addEventListener("click", (event) => {
    const key = event.target.closest("button")?.dataset.sheets;
    if (key) showSheets(key);
  });
  showSheets(shown);

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
const refit = () => App.fitStage2();
window.addEventListener("resize", refit);
const refitObserver = new ResizeObserver(refit);
refitObserver.observe(document.getElementById("top-banner"));
refitObserver.observe(document.getElementById("legal-footer"));
App.showStage("1");
showClaudeStatus();
loadDemoPoints();
