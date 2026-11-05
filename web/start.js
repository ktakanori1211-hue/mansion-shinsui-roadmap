"use strict";

// かんたん版（2026-11-05 作り直し）。
// 4つの画面を順に進む：1 建物 → 2 止まるもの → 3 確かめる → 4 渡す。
// 1画面に、絵1枚・太字1行・ボタン1つ。くわしい説明は「くわしい版」（index.html）に置いたまま。
// 判定はサーバーの決まり（/api/building の equipment の verdict）だけを読み、この画面では新しい判定を作らない。
// 色は 赤＝確かめて止まるおそれ／橙＝未確認（危険という意味ではない）／緑＝問題なし。分からない＝危険とはしない。
// 画面3の答えは「管理会社が図面で確かめた答え」で、今の判定の語（pump・upper:pump・absent:pump など）のまま送る。

const S = {
  screen: 1,
  reached: 1,
  points: [],
  candidates: [],
  message: "",
  error: "",
  place: null,
  demoId: null,
  sampleId: null,
  rooms: "unknown",
  // 画面3で分かった、判定が読む答え（hv：主任技術者がいるか、tr：東京電力の部屋があるか）。
  extra: {},
  building: null,
  confirmed: [],
  floor: "",
  play: 0,
  timer: 0,
  read: null,
  busy: false,
};

const MAIN = ["water", "power", "tr"];
const LOOK = {
  risk: { mark: "！", word: "止まるおそれ" },
  unconfirmed: { mark: "？", word: "未確認" },
  clear: { mark: "✓", word: "問題なし" },
};
const DEFAULT_ROOMS = { a: "basement", b: "ground", c: "basement" };
const ROOM_CHOICES = [
  ["basement", "地下"],
  ["ground", "1階"],
  ["upper", "2階以上"],
  ["unknown", "分からない"],
];
// 暮らしの3つと、それを止める機械（今の判定の行）。水は電気の箱からポンプへ電気が来るので両方を見る。
const TILES = [
  { key: "water", label: "水・トイレ", short: "水", from: ["water", "power"], big: "水が出ない", small: () => "トイレも風呂も使えない" },
  { key: "ev", label: "エレベーター", short: "エレベーター", from: ["power"], big: "エレベーターが止まる", small: (n) => (n >= 2 ? `${n}階まで毎日階段` : "高い階は毎日階段") },
  { key: "homes", label: "家の電気", short: "電気", from: ["tr"], big: "家の電気が止まる", small: () => "冷蔵庫・冷房が使えない" },
];
const MACHINES = [
  { key: "water", label: "ポンプ" },
  { key: "power", label: "電気の箱" },
  { key: "tr", label: "東京電力" },
];
const SERVICE_OF_TILE = { water: "pump", ev: "ev", homes: "homes" };
// 管理会社に頼む確認を、電気を知らない人の言葉で言う（サーバーの top_line.steps の key ごと。中身は同じ確認）。
const PLAIN_ASK = {
  water: "水を送るポンプのスイッチの箱が、床から何cmの高さにあるか",
  power: "電気の機械がどの階にあり、点検の担当者が決まっているか",
  tr: "東京電力の機械の部屋が、建物の中にあるか・どの階か",
  entry: "電気の機械の部屋の壁の穴が、ふさがれているか",
  ev: "エレベーターの底に水が入ったときの手順",
  drain: "トイレの水を汲み上げるポンプがあるか・どの階か",
  backflow: "下水が逆に流れ込むのを止める弁があるか",
  lock: "停電のとき、玄関の扉がどう動くか",
  park: "機械式駐車場の深さと、水を抜くポンプ",
};
const CAPTIONS = {
  1: "大雨で、道路に水がたまる",
  2: "水が、機械の部屋に流れ込む",
  3: "機械が水につかり、止まる",
};
// 画面3の問い。kind は今の判定が読む部屋の語。low は「1階か地下」で、図面でその部屋を確かめた印になる。
const QUESTIONS = [
  { no: "①", row: "water", kind: () => "pump", title: "水を送るポンプの部屋は、図面で何階？", options: ["low", "upper", "absent"] },
  { no: "②", row: "power", kind: (b) => (b.sample.has_chief_engineer ? "elec" : "panel_room"), title: "電気を受ける部屋は、図面で何階？", options: ["low", "upper"] },
  { no: "③", row: "tr", kind: () => "tr", title: "東京電力の変圧器の部屋は、図面で何階？", options: ["low", "upper", "absent"] },
];
const OPTION_WORDS = { low: "1階か地下", upper: "2階以上", absent: "図面にない", none: "まだ" };

const screen = document.getElementById("screen");
const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

async function getJSON(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error("サーバーに接続できませんでした。起動しているか確かめてください。");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || "うまく読めませんでした。もう一度試してください。");
  return body;
}

function postJSON(url, body) {
  return getJSON(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// ---- 判定を読む ----

function row(key) {
  return (S.building?.equipment || []).find((item) => item.key === key) || null;
}

function verdict(key) {
  return row(key)?.verdict || "unconfirmed";
}

function worst(keys) {
  const list = keys.map(verdict);
  if (list.includes("risk")) return "risk";
  if (list.every((item) => item === "clear")) return "clear";
  return "unconfirmed";
}

function openCount() {
  return MAIN.filter((key) => verdict(key) === "unconfirmed").length;
}

function placeKey() {
  if (S.rooms !== "unknown") return S.rooms;
  return S.building?.sample?.archetype === "ground" ? "ground" : "basement";
}

function placeWord() {
  return { basement: "地下", ground: "1階", upper: "2階以上" }[S.rooms] || "";
}

function joinJa(words) {
  if (words.length <= 1) return words.join("");
  if (words.length === 2) return `${words[0]}と${words[1]}`;
  return words.join("・");
}

function titleLine() {
  if (MAIN.every((key) => verdict(key) === "clear")) return S.building.top_line.lead;
  if (S.rooms === "upper") return "機械が2階以上かを図面で確かめると、答えが出ます";
  const names = TILES.filter((tile) => worst(tile.from) !== "clear").map((tile) => tile.short);
  const where = placeWord();
  return `${where ? `${where}の` : ""}機械が水につかると、全部の家で${joinJa(names)}が止まります`;
}

// 戻るまでの目安。サーバーの五段の表の「ほかの建物の例」の文のまま。
function example() {
  const table = S.building?.scenarios?.["3:plate"]?.table || [];
  const found = table.find((item) => /ほかの建物の例/.test(item.label));
  const cell = found?.cells?.[3];
  return cell && cell !== "—" ? cell : "";
}

function placeLine() {
  const rows = S.place?.location?.rows || [];
  const risky = rows.filter((item) => item.verdict === "risk");
  if (risky.length) return { verdict: "risk", text: `この場所：${risky.map((item) => item.conclusion || item.label).join("・")}` };
  const open = rows.filter((item) => item.verdict === "unconfirmed").length;
  if (open) return { verdict: "unconfirmed", text: `この場所：立地の${rows.length}項目のうち${open}つが未確認` };
  return { verdict: "clear", text: "この場所：立地の項目は問題なし（建物の機械は別に確かめます）" };
}

function serviceState(level, tileKey) {
  const services = S.building?.scenarios?.[`${level}:plate`]?.services || [];
  return services.find((item) => item.key === SERVICE_OF_TILE[tileKey])?.state || "unknown";
}

// 最初の手の桁。くわしい版の「今すぐ」の段と同じ計算（app.js の tierSpan）。
function firstStepCost() {
  const ranges = (S.building?.measures || [])
    .filter((m) => m.tier === "今すぐ" && m.key !== "power")
    .map((m) => m.range)
    .filter((range) => range && !range.startsWith("—"));
  if (!ranges.length) return "";
  const low = ranges[0].split("〜")[0];
  const high = ranges[ranges.length - 1].split("〜")[1];
  return ranges.length === 1 ? ranges[0] : `${low}〜${high || ""}`;
}

function disclaimer() {
  const fixed = S.building?.fixed;
  const sample = S.building?.sample;
  if (!fixed || !sample) return null;
  return sample.has_chief_engineer && !sample.engineer_unsure ? fixed.disclaimer_1 : fixed.disclaimer_1_no_engineer;
}

// ---- 断面の絵 ----
// 説明用の模式。暮らしの3つ（上）と、それを止める機械（下）を縦の線で結ぶ。文字と図形は重ならない位置に固定。

function picture({ level = 0, pins = {} } = {}) {
  const place = placeKey();
  const H = place === "basement" ? 272 : 252;
  const groundY = place === "basement" ? 176 : 242;
  const room = { basement: [186, 264], ground: [166, 238], upper: [96, 160] }[place];
  const buildingBottom = place === "basement" ? 268 : groundY;
  const xs = [92, 196, 300];
  const machineY = room[1] - 40;
  const roomLabel = S.rooms === "unknown" ? "機械の部屋（階は未確認）" : `${placeWord()}の機械の部屋`;
  const parts = [];
  parts.push(`<rect x="0" y="0" width="360" height="${H}" fill="#f7f9fc"/>`);
  if (place === "basement") parts.push(`<rect x="0" y="${groundY}" width="360" height="${H - groundY}" fill="#efe6d4"/>`);
  parts.push(`<line x1="0" y1="${groundY}" x2="360" y2="${groundY}" stroke="#8a7a5c" stroke-width="3"/>`);
  parts.push(`<text x="3" y="${groundY - 17}" class="t-muted">道路</text>`);
  parts.push(`<rect x="38" y="10" width="316" height="${buildingBottom - 10}" fill="#fff" stroke="#44474f" stroke-width="2.5"/>`);
  parts.push(`<text x="46" y="28" class="t-muted">住まい（全部の家）</text>`);
  [98, 128, 158, 188, 218].forEach((y) => {
    if (y < groundY - 4 && !(y > room[0] - 6 && y < room[1] + 6)) parts.push(`<line x1="38" y1="${y}" x2="354" y2="${y}" stroke="#e1e4ea" stroke-width="1.5"/>`);
  });
  if (level >= 1) parts.push(`<rect class="water" x="0" y="${groundY - 12}" width="38" height="12"/>`);
  if (level >= 2) {
    const top = level >= 3 ? machineY - 6 : room[1] - 14;
    parts.push(`<rect class="water" x="44" y="${top}" width="304" height="${room[1] - top - 2}"/>`);
    parts.push(`<path d="M22 ${groundY - 6} C 34 ${groundY - 6}, 36 ${room[1] - 10}, 52 ${room[1] - 10}" fill="none" stroke="#1d5fa8" stroke-width="4" marker-end="url(#arrow)"/>`);
  }
  parts.push(`<rect x="44" y="${room[0]}" width="304" height="${room[1] - room[0]}" fill="none" stroke="#c98a2b" stroke-width="2" rx="4"/>`);
  parts.push(`<text x="52" y="${room[0] + 17}" class="t-room">${esc(roomLabel)}</text>`);
  TILES.forEach((tile, i) => {
    const x = xs[i];
    const machine = MACHINES[i];
    const mv = verdict(machine.key);
    parts.push(`<line x1="${x}" y1="84" x2="${x}" y2="${machineY}" class="link ${mv}"/>`);
    let state;
    let word;
    if (level) {
      const raw = serviceState(level, tile.key);
      state = raw === "stopped" ? "stopped" : raw === "unknown" ? "unconfirmed" : "running";
      word = { stopped: "止まる", unconfirmed: "？", running: "使える" }[state];
    } else {
      state = worst(tile.from);
      word = LOOK[state].word;
    }
    parts.push(`<g class="tile ${state}"><rect x="${x - 49}" y="38" width="98" height="46" rx="8"/><text x="${x}" y="58" class="t-tile">${esc(tile.label)}</text><text x="${x}" y="76" class="t-state">${esc(word)}</text></g>`);
    parts.push(`<g class="machine ${mv}"><rect x="${x - 49}" y="${machineY}" width="98" height="32" rx="6"/><text x="${x}" y="${machineY + 21}" class="t-machine">${esc(machine.label)} ${LOOK[mv].mark}</text></g>`);
    if (pins[machine.key]) parts.push(pin(x, machineY - 10, pins[machine.key]));
  });
  // 機械のほかに絵で示せる確認：壁の穴は水が入る機械の部屋の左の壁、エレベーターの手順はエレベーターの札。
  if (pins.entry) parts.push(pin(20, Math.round((room[0] + room[1]) / 2), pins.entry));
  if (pins.ev) parts.push(pin(xs[1], 32, pins.ev));
  const label = level ? `もし水がここまで来たら：${CAPTIONS[level]}` : titleLine();
  return `<svg class="art-svg" viewBox="0 0 360 ${H}" role="img" aria-label="${esc(label)}">
    <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#1d5fa8"/></marker></defs>
    ${parts.join("")}
  </svg>`;
}

function pin(cx, cy, number) {
  return `<g class="pin"><circle cx="${cx}" cy="${cy}" r="12"/><text x="${cx}" y="${cy + 5}">${number}</text></g>`;
}

function legend() {
  return `<ul class="legend">
    <li class="risk"><i></i>止まるおそれ（確かめた）</li>
    <li class="unconfirmed"><i></i>未確認（危険という意味ではありません）</li>
    <li class="clear"><i></i>問題なし</li>
  </ul>`;
}

// ---- 画面 ----

function screenOne() {
  const samples = S.points
    .map((point) => {
      const [name, place] = point.label.replace(/^見本/, "").split("／");
      const chosen = S.demoId === point.id ? " chosen" : "";
      const [letter, title] = [name.slice(0, 1), name.slice(1).replace("（架空）", "").trim()];
      return `<button type="button" class="sample${chosen}" data-demo="${esc(point.id)}"><b>見本${esc(letter)}</b><em>${esc(title)}</em><span>${esc(place || "")}</span></button>`;
    })
    .join("");
  const candidates = S.candidates
    .map((c, i) => `<button type="button" class="candidate" data-cand="${i}">${esc(c.label)}<small>${esc(c.source || "")}</small></button>`)
    .join("");
  const chips = ROOM_CHOICES.map(
    ([key, word]) => `<button type="button" class="chip${S.rooms === key ? " chosen" : ""}" data-rooms="${key}" aria-pressed="${S.rooms === key}">${roomIcon(key)}<span>${word}</span></button>`,
  ).join("");
  const picked = S.place
    ? `<div class="picked">
        <p class="place">場所：<b>${esc(S.place.site.label)}</b></p>
        <h2 class="question">電気とポンプの部屋は、どの階？</h2>
        <div class="chips">${chips}</div>
        <p class="hint">分からなくても進めます。3の画面で確かめます。</p>
        <button type="button" class="primary" data-act="see"${S.busy ? " disabled" : ""}>この建物で見る</button>
      </div>`
    : "";
  return `<section class="s1">
    <h1 class="title">大雨のとき、<br>あなたのマンションで<br>何が止まるか</h1>
    <form class="find" id="find">
      <input id="q" name="q" type="search" autocomplete="off" placeholder="住所かマンション名" aria-label="住所・マンション名・郵便番号">
      <button type="submit">探す</button>
    </form>
    ${S.error ? `<p class="error" role="alert">${esc(S.error)}</p>` : ""}
    ${S.message ? `<p class="hint">${esc(S.message)}</p>` : ""}
    ${candidates ? `<div class="candidates">${candidates}</div>` : ""}
    <p class="or">または、見本（架空の建物）で試す</p>
    <div class="samples">${samples}</div>
    ${picked}
  </section>`;
}

function roomIcon(key) {
  const y = { basement: 30, ground: 20, upper: 8, unknown: null }[key];
  const box = y === null ? `<text x="20" y="27" text-anchor="middle" font-size="16" font-weight="700" fill="currentColor">？</text>` : `<rect x="12" y="${y}" width="16" height="8" rx="2" fill="currentColor"/>`;
  return `<svg viewBox="0 0 40 40" aria-hidden="true"><rect x="6" y="4" width="28" height="22" fill="none" stroke="currentColor" stroke-width="2"/><line x1="0" y1="26" x2="40" y2="26" stroke="currentColor" stroke-width="2"/><rect x="6" y="26" width="28" height="12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="3 2"/>${box}</svg>`;
}

function screenTwo() {
  const b = S.building;
  const n = Number(S.floor);
  const lines = TILES.filter((tile) => worst(tile.from) !== "clear")
    .map((tile) => `<li class="${worst(tile.from)}"><b>${esc(tile.big)}</b><span>${esc(tile.small(n))}</span></li>`)
    .join("");
  const sample = example();
  const place = placeLine();
  const allClear = MAIN.every((key) => verdict(key) === "clear");
  const count = openCount();
  const playing = S.play > 0;
  return `<section class="s2">
    <p class="kicker">${esc(b.sample.custom ? S.place.site.label : `${b.sample.name}／${S.place.site.label}`)}</p>
    <h1 class="title">${esc(titleLine())}</h1>
    ${allClear ? "" : `<p class="lead${MAIN.some((key) => verdict(key) === "risk") ? " risky" : ""}">${esc(b.top_line.lead)}${sample ? `<br><small>${esc(sample)}</small>` : ""}</p>`}
    <div class="art">${picture({ level: S.play })}</div>
    <div class="play-row">
      <button type="button" class="play" data-act="play">${playing ? "❚❚ 止める" : "▶ 水が入る順に見る"}</button>
      <span class="caption">${playing ? `もし水がここまで来たら：<b>${S.play}. ${esc(CAPTIONS[S.play])}</b>` : "色は、今わかっていること"}</span>
    </div>
    ${playing ? "" : legend()}
    ${
      lines
        ? `<div class="life">
      <label class="floor">止まると、あなたの暮らしでは（住んでいる階：<input id="floor" type="number" inputmode="numeric" min="1" max="80" value="${esc(S.floor)}" placeholder="8">階）</label>
      <ul class="life-list">${lines}</ul>
    </div>`
        : ""
    }
    <p class="place-line ${place.verdict}"><i></i>${esc(place.text)}</p>
    <button type="button" class="primary" data-act="to3">${count ? `？を確かめる（未確認 ${count}）` : "確かめた答えを見直す"}</button>
  </section>`;
}

function chosenOption(kind) {
  if (S.confirmed.includes(`upper:${kind}`)) return "upper";
  if (S.confirmed.includes(`absent:${kind}`)) return "absent";
  if (S.confirmed.includes(kind)) return "low";
  return "none";
}

function screenThree() {
  const b = S.building;
  const count = openCount();
  const cards = QUESTIONS.map((q) => {
    const kind = q.kind(b);
    const item = row(q.row);
    const v = verdict(q.row);
    const unsure = q.row === "power" && b.sample.engineer_unsure;
    const chosen = chosenOption(kind);
    const options = unsure
      ? `<p class="hint">先に、点検報告書で電気主任技術者の名前を確かめます。</p><div class="options"><button type="button" class="option" data-hv="yes">名前がある</button><button type="button" class="option chosen" data-hv="none" aria-pressed="true">まだ</button></div>`
      : `<div class="options">${[...q.options, "none"]
          .map((o) => `<button type="button" class="option${chosen === o ? " chosen" : ""}" data-kind="${kind}" data-choice="${o}" aria-pressed="${chosen === o}">${OPTION_WORDS[o]}</button>`)
          .join("")}</div>`;
    const engineer = q.row === "power" && S.extra.hv === "yes" ? `<p class="hint">電気主任技術者：点検報告書に名前あり　<button type="button" class="option small" data-hv="none">取り消す</button></p>` : "";
    return `<div class="qcard ${v}">
      <p class="qtitle"><span class="no">${q.no}</span>${esc(q.title)}</p>
      ${engineer}${options}
      <p class="qresult ${v}"><b>${LOOK[v].mark} ${LOOK[v].word}</b>${item ? `　${esc(item.summary)}` : ""}</p>
    </div>`;
  }).join("");
  return `<section class="s3">
    <p class="kicker">管理会社に、竣工図で見てもらった答え</p>
    <h1 class="title">図面で確かめた答えを入れる</h1>
    <div class="count-row">
      <div class="count" id="count"><span>未確認</span><b>${count}</b><span>／3</span></div>
      <div class="art small">${picture()}</div>
    </div>
    ${cards}
    <div class="qcard read">
      <p class="qtitle">図面の写真から読む（Claude）</p>
      <div class="options">
        <label class="option file">写真・PDFを選ぶ<input type="file" id="plan-file" accept="image/*,application/pdf"></label>
        ${S.sampleId ? `<button type="button" class="option" data-act="read-sample">見本の図面で試す</button>` : ""}
      </div>
      ${readResult()}
    </div>
    <button type="button" class="primary" data-act="to4">管理会社に渡す紙へ</button>
  </section>`;
}

function floorChoice(floor) {
  const text = String(floor || "");
  if (/地下/.test(text) || /^1階/.test(text)) return "low";
  const m = text.match(/(\d+)階/);
  if (m && Number(m[1]) >= 2) return "upper";
  return null;
}

function readResult() {
  if (S.busy && !S.read) return `<p class="hint">読んでいます…</p>`;
  if (!S.read) return `<p class="hint">Claude が部屋と階を読み、①〜③の答えの候補を出します。入れるかは、あなたが決めます。</p>`;
  const kinds = { pump: "①", elec: "②", panel_room: "②", tr: "③" };
  const proposals = (S.read.rooms || [])
    .filter((room) => kinds[room.kind])
    .map((room) => {
      const choice = floorChoice(room.floor);
      const button = choice ? `<button type="button" class="option small" data-kind="${room.kind}" data-choice="${choice}">${kinds[room.kind]}に「${OPTION_WORDS[choice]}」を入れる</button>` : `<span class="hint">階が読めません</span>`;
      return `<li><b>${esc(room.name || room.word)}</b>：${esc(room.floor || "階は読めず")}　${button}</li>`;
    })
    .join("");
  return `<p class="hint">${esc(S.read.message || "")}</p>${proposals ? `<ul class="proposals">${proposals}</ul>` : ""}`;
}

function pinsOf(steps) {
  const pins = {};
  steps.forEach((step, i) => {
    if ([...MAIN, "entry", "ev"].includes(step.key)) pins[step.key] = i + 1;
  });
  return pins;
}

function screenFour() {
  const steps = S.building.top_line.steps || [];
  const cost = firstStepCost();
  const asks = steps
    .map((step, i) => `<li><span class="no">${i + 1}</span><div><b>${esc(PLAIN_ASK[step.key] || step.what)}</b><small>頼む先：${esc(step.who)}</small></div></li>`)
    .join("");
  return `<section class="s4">
    <h1 class="title">${steps.length ? `残りの確認${steps.length}つを、管理会社に頼む` : "大事な確認は、済んでいます"}</h1>
    <div class="art">${picture({ pins: pinsOf(steps) })}</div>
    ${asks ? `<ol class="asks">${asks}</ol>` : `<p class="hint">ほかの項目（入口・排水・駐車場など）は、くわしい版で見られます。</p>`}
    ${cost ? `<p class="cost">そのあとの最初の手は <b>${esc(cost)}</b>。理事会と管理費で決められることもあります。</p>` : ""}
    <button type="button" class="primary" data-act="print">依頼メモを印刷</button>
    <a class="secondary" href="${fullHref()}">くわしい版で、理事会用のA4表裏・費用・補助を見る</a>
  </section>`;
}

function fullHref() {
  return `/index.html${S.demoId ? `#demo=${encodeURIComponent(S.demoId)}` : ""}`;
}

function printMemo() {
  const steps = S.building.top_line.steps || [];
  const today = new Date();
  const date = `${today.getFullYear()}年${today.getMonth() + 1}月${today.getDate()}日`;
  const asks = steps
    .map((step, i) => `<li><b>${i + 1}. ${esc(PLAIN_ASK[step.key] || step.what)}</b><br>頼む先：${esc(step.who)}${step.memo_no ? `（くわしい版の依頼メモ ${esc(step.memo_no)}）` : ""}</li>`)
    .join("");
  document.getElementById("print-memo").innerHTML = `
    <h1>管理会社への確認のお願い</h1>
    <p>建物：${esc(S.building.sample.custom ? "（建物名）" : S.building.sample.name)}　場所：${esc(S.place.site.label)}　作成日：${date}</p>
    <div class="print-art">${picture({ pins: pinsOf(steps) })}</div>
    <p>図の番号の所を、図面（竣工図）と点検の記録で確かめてください。住民・理事・管理員は、電気やポンプの部屋に入りません。</p>
    <ol>${asks}</ol>
    <p>答えが分かったら、マンション浸水ロードマップの「3 確かめる」に入れると、絵の色が変わります。</p>
    <p class="print-fixed">${esc(disclaimer() || document.getElementById("fixed-disclaimer").textContent)}</p>`;
  window.print();
}

function render() {
  const views = { 1: screenOne, 2: screenTwo, 3: screenThree, 4: screenFour };
  screen.innerHTML = views[S.screen]();
  document.querySelectorAll("#steps [data-go]").forEach((button) => {
    const n = Number(button.dataset.go);
    button.disabled = n > S.reached;
    button.classList.toggle("current", n === S.screen);
    button.setAttribute("aria-current", n === S.screen ? "step" : "false");
  });
  document.getElementById("full-link").href = fullHref();
  const text = disclaimer();
  if (text) document.getElementById("fixed-disclaimer").textContent = text;
}

function go(n) {
  stopPlay(false);
  S.screen = n;
  S.reached = Math.max(S.reached, n);
  render();
  window.scrollTo({ top: 0 });
}

// ---- 動き ----

async function loadPoints() {
  try {
    S.points = await getJSON("/api/demo-points");
  } catch (error) {
    S.points = [];
  }
  render();
}

async function choosePlace(params, sampleId, demoId) {
  S.busy = true;
  S.error = "";
  render();
  try {
    S.place = await getJSON(`/api/location?${new URLSearchParams(params)}`);
    S.sampleId = sampleId;
    S.demoId = demoId;
    S.rooms = DEFAULT_ROOMS[sampleId] || "unknown";
    S.candidates = [];
    S.message = "";
    S.building = null;
    S.confirmed = [];
    S.extra = {};
    S.read = null;
    S.reached = 1;
  } catch (error) {
    S.error = error.message;
  } finally {
    S.busy = false;
    render();
  }
}

async function loadBuilding() {
  const location = S.place.location;
  const reading = location.reading || {};
  S.building = await postJSON("/api/building", {
    sample_id: S.sampleId,
    answers: { rooms_floor: S.rooms, basement: S.rooms === "basement" ? "yes" : S.rooms === "unknown" ? "unknown" : "no", ...S.extra },
    label: S.place.site.label,
    confirmed: S.confirmed,
    document_read: false,
    directions: {},
    low_directions: reading.low_directions || [],
    high_directions: reading.high_directions || [],
    basin: Boolean(reading.basin),
    statements: [],
    location_rows: location.rows,
  });
}

async function seeBuilding() {
  S.busy = true;
  render();
  try {
    await loadBuilding();
    S.busy = false;
    go(2);
  } catch (error) {
    S.busy = false;
    S.error = error.message;
    render();
  }
}

async function setRoom(kind, choice) {
  const before = openCount();
  S.confirmed = S.confirmed.filter((item) => ![kind, `upper:${kind}`, `absent:${kind}`].includes(item));
  if (choice === "low") S.confirmed.push(kind);
  if (choice === "upper") S.confirmed.push(`upper:${kind}`);
  if (choice === "absent") S.confirmed.push(`absent:${kind}`);
  // 東京電力の部屋は、図面で階が分かれば「ある」、図面になければ「ない」と答えたことにもなる。
  if (kind === "tr") {
    if (choice === "none") delete S.extra.tr;
    else S.extra.tr = choice === "absent" ? "no" : "yes";
  }
  await loadBuilding();
  render();
  if (openCount() !== before) document.getElementById("count")?.classList.add("bump");
}

async function setEngineer(answer) {
  if (answer === "yes") S.extra.hv = "yes";
  else delete S.extra.hv;
  await loadBuilding();
  render();
}

async function readPlan(file) {
  S.busy = true;
  S.read = null;
  render();
  try {
    const body = { sample_id: S.sampleId };
    if (file) {
      body.data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = () => reject(new Error("ファイルを読めませんでした。"));
        reader.readAsDataURL(file);
      });
      body.media_type = file.type;
    }
    S.read = await postJSON("/api/plan", body);
  } catch (error) {
    S.read = { message: error.message, rooms: [] };
  } finally {
    S.busy = false;
    render();
  }
}

function stopPlay(redraw = true) {
  clearInterval(S.timer);
  S.timer = 0;
  S.play = 0;
  if (redraw) render();
}

function startPlay() {
  stopPlay(false);
  S.play = 1;
  render();
  S.timer = setInterval(() => {
    if (S.play >= 3) {
      clearInterval(S.timer);
      S.timer = setTimeout(() => stopPlay(), 2600);
      return;
    }
    S.play += 1;
    render();
  }, 1800);
}

screen.addEventListener("submit", async (event) => {
  if (event.target.id !== "find") return;
  event.preventDefault();
  const q = document.getElementById("q").value.trim();
  S.error = "";
  S.message = "";
  try {
    const body = await getJSON(`/api/search?${new URLSearchParams({ q })}`);
    S.candidates = body.candidates || [];
    S.message = body.message || (S.candidates.length ? "" : "場所が見つかりませんでした。");
  } catch (error) {
    S.candidates = [];
    S.error = error.message;
  }
  render();
});

screen.addEventListener("click", (event) => {
  const target = event.target.closest("button");
  if (!target || target.disabled) return;
  if (target.dataset.demo) {
    const point = S.points.find((p) => p.id === target.dataset.demo);
    if (point) choosePlace({ demo: point.id }, point.sample, point.id);
  } else if (target.dataset.cand) {
    const c = S.candidates[Number(target.dataset.cand)];
    if (c) choosePlace({ address: c.label, longitude: c.longitude, latitude: c.latitude }, null, null);
  } else if (target.dataset.rooms) {
    S.rooms = target.dataset.rooms;
    render();
  } else if (target.dataset.hv) {
    setEngineer(target.dataset.hv);
  } else if (target.dataset.kind) {
    setRoom(target.dataset.kind, target.dataset.choice);
  } else {
    const act = target.dataset.act;
    if (act === "see") seeBuilding();
    if (act === "play") (S.play ? stopPlay() : startPlay());
    if (act === "to3") go(3);
    if (act === "to4") go(4);
    if (act === "read-sample") readPlan(null);
    if (act === "print") printMemo();
  }
});

screen.addEventListener("change", (event) => {
  if (event.target.id === "floor") {
    S.floor = event.target.value;
    render();
  }
  if (event.target.id === "plan-file" && event.target.files[0]) readPlan(event.target.files[0]);
});

document.getElementById("steps").addEventListener("click", (event) => {
  const button = event.target.closest("[data-go]");
  if (button && !button.disabled) go(Number(button.dataset.go));
});

render();
loadPoints();
