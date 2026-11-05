"use strict";

// マンション浸水ロードマップ（2026-11-05 一本化）。
// 4つの画面を順に進む：1 場所 → 2 止まるもの → 3 確かめる → 4 渡す。
// 絵は構内平面図だけ。部屋の位置は /api/building の sample.views から描き、部屋の色はサーバーの判定（equipment の verdict）のまま塗る。
// この画面では新しい判定を作らない。色は 赤＝確かめて止まるおそれ／橙＝未確認（危険という意味ではない）／緑＝問題なし。
// 青い矢印は水の入り道（入りうる所）で、判定ではない。
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
  // 画面3で分かった、判定が読む答え（hv：主任技術者がいるか、tr：東京電力の部屋があるか）。
  extra: {},
  // 画面3の答え。部屋の種類ごとに basement / ground / upper / absent。
  choices: {},
  building: null,
  floor: "",
  play: 0,
  timer: 0,
  read: null,
  busy: false,
  tab: "memo",
  flash: [],
  claude: null,
  // チャットで聞き取った事実（サーバーの statements）。依頼メモの材料になる。
  statements: [],
  map: null,
};

const MAIN = ["water", "power", "tr"];
const LOOK = {
  risk: { mark: "！", word: "止まるおそれ" },
  unconfirmed: { mark: "？", word: "未確認" },
  clear: { mark: "✓", word: "問題なし" },
};
// 暮らしの3つと、それを止める機械（今の判定の行）。水は電気の部屋からポンプへ電気が来るので両方を見る。
const TILES = [
  { key: "water", label: "水・トイレ", short: "水", from: ["water", "power"], small: () => "風呂もトイレも使えない" },
  { key: "ev", label: "エレベーター", short: "エレベーター", from: ["power"], small: (n) => (n >= 2 ? `${n}階まで毎日階段` : "高い階は毎日階段") },
  { key: "homes", label: "家の電気", short: "電気", from: ["tr"], small: () => "冷蔵庫も冷房も止まる" },
];
const SERVICE_OF_TILE = { water: "pump", ev: "ev", homes: "homes" };
// 平面図の部屋と、判定の行（サーバーの _UPPER_ROWS・_ABSENT_ROWS と同じ対応）。ほかの部屋は色を塗らない。
const KIND_ROWS = { pump: "water", elec: "power", panel_room: "power", tr: "tr", gen: "gen", tank: "tank", park: "park", ev: "ev" };
const ROOM_SHORT = { elec: "電気室", tr: "借室", panel_room: "分電盤室", pump: "ポンプ室", gen: "発電機室", tank: "雨水槽", park: "駐車場ピット", ev: "EV" };
// 水が来たときに止まるもの（サーバーの scenarios の services）と、その部屋。
const STOPS_OF_ROOM = { pump: ["pump"], elec: ["ev", "light"], panel_room: ["ev", "light"], tr: ["homes"] };
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
// 再生の注意書き（前の断面図の再生と同じ文）。時刻や速さは出さない。
const PLAY_NOTE = "実際の浸水速度の予測ではなく、水が順番に入る仕組みの模式です。";
const CAPTIONS = {
  1: "大雨で、道路に水がたまる",
  2: "水が、入り道から建物に入る",
  3: "機械の部屋が水につかり、止まる想定",
};
// 画面3の問い。kind は今の判定が読む部屋の語。「地下」「1階」は、図面でその部屋を確かめた印になる。
const QUESTIONS = [
  { no: "①", row: "water", kind: () => "pump", title: "水を送るポンプの部屋は、図面で何階？", options: ["basement", "ground", "upper", "absent"] },
  { no: "②", row: "power", kind: (b) => (b.sample.has_chief_engineer ? "elec" : "panel_room"), title: "電気を受ける部屋は、図面で何階？", options: ["basement", "ground", "upper"] },
  { no: "③", row: "tr", kind: () => "tr", title: "東京電力の変圧器の部屋は、図面で何階？", options: ["basement", "ground", "upper", "absent"] },
];
const OPTION_WORDS = { basement: "地下", ground: "1階", upper: "2階以上", absent: "図面にない", none: "まだ" };
// 立地の行の短い名前。
const PLACE_SHORT = { flood: "川の洪水", inland: "下水・水路", surge: "高潮", ground: "土地の高さ", record: "浸水の記録" };
// 対策の短い名前（サーバーの measures の key ごと。くわしい文は折りたたみに入れる）。
const MEASURE_SHORT = {
  hole: "壁の穴をふさぐ",
  plate: "置くだけの止水板と土のう",
  procedure: "大雨の前の手順を決める",
  tepco: "借室の対策を東京電力に照会",
  pump_check: "排水ポンプの点検",
  panel: "ポンプの盤を高く付け替える",
  pillar: "支柱式の止水板",
  door: "電気室の扉を防水扉に",
  vent: "足元の換気口を高く",
  power: "電源車の受け口を1階に",
  backflow: "逆止弁を付ける",
  door_rebuild: "枠ごと防水扉に",
  move: "受電の箱を屋上へ移す",
  main_panel: "共用の主な盤を高く付け替える",
  gen_move: "非常用発電機を上の階へ",
};
const TIERS = ["今すぐ", "工事が要る", "更新と一緒"];
// 補助の印。前の試算の画面と同じ言い方（言い切らない）。東京都と千葉市のほかは、制度を調べていないので出さない。
const AID_WORDS = { yes: "補助の対象になりうる", with_plate: "止水板などと併せるときに限る", no: "対象外になりうる", unknown: "補助は未確認" };
const AID_REGIONS = ["tokyo", "chiba"];
const TABS = [
  ["memo", "依頼メモ", "依頼メモを印刷"],
  ["a4", "理事会A4", "A4表裏を印刷"],
  ["cost", "費用・補助", "費用と補助を印刷"],
];
const BORROWED = "図は見本の形を借りた説明用です。あなたの建物の図面ではありません。";
// 紙の裏に出す固定の文（前の A4 の裏と同じ。言い換えない）。
const SHEET_FIXED = [
  "浸水実績は自治体の公表データを独自に集計・加工したもので、自治体の公式証明ではない",
  "本シートは予報ではなく、現時点の静的な整理である",
  "費用は桁の目安で、保安法人・工事業者の見積りに置き換えること",
];
const COST_FIXED = SHEET_FIXED[2];
const SCOPE_LINES = [
  "対象：東京電力パワーグリッドの区域の、高圧で電気を受けるマンション。低圧・テナントの入る建物・ほかの区域にも同じ形で広げられます。戸建ては対象外です。今の見本には借室のみの建物も含みます。",
  "東京電力パワーグリッドの区域の外では、借室の照会先はその地域の電力会社（一般送配電事業者）になるので、この道具の文はそのままでは当てはまりません。区域に入る都道府県の一覧は、まだ確かめていません。",
];

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

function roomsFloor() {
  return S.building?.sample?.answers?.rooms_floor || "unknown";
}

// 紙と画面に出す住所は町丁まで。番地・号・建物の番号は出さない（前の A4 と同じ丸め方）。
function townLabel(label) {
  return String(label || "")
    .replace(/[0-9０-９一二三四五六七八九十〇百千]+番(?!町)(地)?.*$/, "")
    .replace(/[0-9０-９一二三四五六七八九十〇百千]+号.*$/, "")
    .replace(/(丁目)[0-9０-９\-－−ー].*$/, "$1")
    .replace(/[0-9０-９]+[\-－−ー][0-9０-９].*$/, "")
    .trim();
}

function where() {
  const b = S.building;
  return `${b.sample.custom ? "（建物名）" : b.sample.name}／${townLabel(S.place.site.label)}`;
}

function joinJa(words) {
  if (words.length <= 1) return words.join("");
  if (words.length === 2) return `${words[0]}と${words[1]}`;
  return words.join("・");
}

function titleLine() {
  if (MAIN.every((key) => verdict(key) === "clear")) return S.building.top_line.lead;
  if (roomsFloor() === "upper") return "機械が2階以上かを図面で確かめると、答えが出ます";
  const names = TILES.filter((tile) => worst(tile.from) !== "clear").map((tile) => tile.short);
  const where = { basement: "地下", ground: "1階" }[roomsFloor()] || "";
  return `${where ? `${where}の` : ""}機械が水につかると、全部の家で${joinJa(names)}が止まります`;
}

// 戻るまでの目安。サーバーの五段の表の「ほかの建物の例」の文のまま。
function example() {
  const table = S.building?.scenarios?.["3:plate"]?.table || [];
  const found = table.find((item) => /ほかの建物の例/.test(item.label));
  const cell = found?.cells?.[3];
  return cell && cell !== "—" ? cell : "";
}

function serviceState(level, key) {
  const services = S.building?.scenarios?.[`${level}:plate`]?.services || [];
  return services.find((item) => item.key === key)?.state || "unknown";
}

// サーバーの対策を全部出す。短い名前がない手は、元の名前の（ ）の前までを使う。
function measures() {
  return S.building?.measures || [];
}

function measureName(m) {
  return MEASURE_SHORT[m.key] || m.label.replace(/（.*$/, "");
}

// 最初の手の桁。「今すぐ」の段の費用の幅を、安い順のまま端から端までつなぐ。
function firstStepCost() {
  const ranges = measures()
    .filter((m) => m.tier === "今すぐ" && m.key !== "power")
    .map((m) => m.range)
    .filter((range) => range && !range.startsWith("—"));
  if (!ranges.length) return "";
  const low = ranges[0].split("〜")[0];
  const high = ranges[ranges.length - 1].split("〜")[1];
  return ranges.length === 1 ? ranges[0] : `${low}〜${high || ""}`;
}

function subsidy() {
  const region = S.building?.sample?.subsidy || "none";
  return { region, ...(S.building?.subsidies?.[region] || S.building?.subsidies?.none || {}) };
}

function disclaimer() {
  const fixed = S.building?.fixed;
  const sample = S.building?.sample;
  if (!fixed || !sample) return null;
  return sample.has_chief_engineer && !sample.engineer_unsure ? fixed.disclaimer_1 : fixed.disclaimer_1_no_engineer;
}

function steps() {
  return S.building?.top_line?.steps || [];
}

// ---- 構内平面図 ----
// 機械のある階の平面図を大きく描く。1階のスロープ・道路・引込みの管・雨水ますは、同じ外形の上に重ねて入り道として描く。
// 部屋の色はサーバーの判定のまま。番号のピンは、まだ確かめていない確認（top_line.steps）だけに立てる。

const VW = 700;
const PAD = 18;

function machineView(sample) {
  return sample.views.find((view) => view.rooms.some((room) => ["pump", "elec", "tr", "panel_room"].includes(room.key))) || sample.views[0];
}

function planShape(sample) {
  const view = machineView(sample);
  const all = sample.views.flatMap((v) => v.rooms);
  const W = Math.max(...all.map((room) => room.mm[2]));
  const H = Math.max(...all.map((room) => room.mm[3]));
  const marks = sample.views.flatMap((v) => (v.marks || []).map((mark) => ({ ...mark, own: v === view })));
  const slope = sample.views.filter((v) => v !== view).flatMap((v) => v.rooms).find((room) => room.key === "slope");
  const basin = marks.find((mark) => mark.kind === "basin");
  const road = marks.find((mark) => mark.kind === "road");
  const top = slope || basin ? 66 : 46;
  const inner = VW - PAD * 2;
  const planH = (inner * H) / W;
  const bottom = road ? 84 : 22;
  return { view, W, H, marks, slope, basin, road, top, inner, planH, VH: Math.round(top + planH + bottom) };
}

function fitText(text, width, size, min = 15) {
  const chars = [...text].length || 1;
  const fit = Math.min(size, (width - 10) / chars);
  return fit >= min ? fit : 0;
}

function roomAt(view, fx, fy) {
  return view.rooms.find((room) => fx >= room.x && fx <= room.x + room.w && fy >= room.y && fy <= room.y + room.h) || null;
}

// 番号のピンの位置。部屋の右上、または壁の穴・坂の下の扉の上。
function pinAnchors(shape, X, Y) {
  const anchors = {};
  const byKey = (keys) => shape.view.rooms.find((room) => keys.includes(room.key));
  const corner = (room) => {
    if (!room) return null;
    const w = room.w * shape.inner;
    // 部屋の名前に重ならないよう、壁の角に立てる。小さい部屋（EV など）は部屋の真ん中に立て、隣の部屋の角のピンと離す。
    return w < 90 ? [X(room.x + room.w / 2), Y(room.y + room.h / 2)] : [X(room.x + room.w) - 6, Y(room.y) + 6];
  };
  anchors.water = corner(byKey(["pump"]));
  anchors.power = corner(byKey(["elec", "panel_room"]));
  anchors.tr = corner(byKey(["tr"]));
  anchors.ev = corner(byKey(["ev"]));
  anchors.park = corner(byKey(["park"]));
  const hole = shape.marks.find((mark) => mark.kind === "conduit_hole" || mark.kind === "door_low");
  if (hole) anchors.entry = [X(hole.x), Y(1)];
  return anchors;
}

function plan({ level = 0, pins = {}, small = false } = {}) {
  const sample = S.building.sample;
  const shape = planShape(sample);
  const { view, top, inner, planH, VH } = shape;
  const X = (fx) => PAD + fx * inner;
  const Y = (fy) => top + fy * planH;
  const parts = [];
  const wet = new Set();
  parts.push(`<rect x="0" y="0" width="${VW}" height="${VH}" class="p-ground"/>`);
  parts.push(`<text x="${PAD}" y="30" class="p-floor">${esc(view.name.replace("平面図", ""))}の平面図</text>`);

  // 道路（1階の平面図の下の辺の外）。
  const roadY = Y(1) + 18;
  if (shape.road) {
    parts.push(`<rect x="0" y="${roadY}" width="${VW}" height="46" class="p-road${level >= 1 ? " p-flooded" : ""}"/>`);
    const word = shape.road.slope ? "坂の下の通路" : "前の道路";
    parts.push(`<text x="${VW - PAD}" y="${roadY + 30}" class="p-road-label" text-anchor="end">${word}</text>`);
  }

  // 入り道がつながる部屋（水が入る順の2段め）。
  const entries = [];
  if (shape.slope) {
    const cx = shape.slope.x + shape.slope.w / 2;
    const target = roomAt(view, cx, shape.slope.y + 0.02);
    if (target) wet.add(target.key);
    entries.push({ x1: X(cx), y1: 14, x2: X(cx), y2: Y(target ? target.y : 0) + 26, label: "スロープから", lx: X(cx) - 12, ly: 34, anchor: "end" });
  }
  if (shape.basin) {
    const target = roomAt(view, shape.basin.x, shape.basin.y);
    if (target) wet.add(target.key);
    entries.push({ x1: X(shape.basin.x), y1: 14, x2: X(shape.basin.x), y2: Y(target ? target.y : 0) + 26, label: "雨水ますから", lx: X(shape.basin.x) - 12, ly: 34, anchor: "end" });
  }
  shape.marks
    .filter((mark) => mark.kind === "conduit_hole" || mark.kind === "door_low")
    .forEach((mark) => {
      const target = roomAt(view, mark.x, 0.98);
      if (target) wet.add(target.key);
      const word = mark.kind === "conduit_hole" ? "管から壁の穴へ" : "扉・換気口から";
      entries.push({ x1: X(mark.x), y1: roadY + 36, x2: X(mark.x), y2: Y(1) - 22, label: word, lx: X(mark.x) + 16, ly: roadY + 30, anchor: "start", hole: mark.kind === "conduit_hole" });
    });

  // 部屋。
  view.rooms.forEach((room) => {
    const x = X(room.x);
    const y = Y(room.y);
    const w = room.w * inner;
    const h = room.h * planH;
    const rowKey = KIND_ROWS[room.key];
    const v = rowKey && row(rowKey) ? row(rowKey).verdict : null;
    const flash = S.flash.includes(room.key) ? " flash" : "";
    const cls = v ? `p-room p-key ${v}${flash}` : room.hatch ? "p-room p-soil" : `p-room${flash}`;
    parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" class="${cls}" data-room="${esc(room.key)}"/>`);
    let flooded = false;
    if (level >= 2 && wet.has(room.key)) flooded = true;
    if (level >= 3 && /^corridor/.test(room.key)) flooded = true;
    if (level >= 3 && STOPS_OF_ROOM[room.key]) flooded = STOPS_OF_ROOM[room.key].some((key) => serviceState(level, key) === "stopped");
    if (flooded) parts.push(`<rect x="${x + 3}" y="${y + h * 0.45}" width="${w - 6}" height="${h * 0.55 - 3}" class="p-water"/>`);
    const cx = x + w / 2;
    if (v) {
      const name = ROOM_SHORT[room.key];
      const size = fitText(name, w, 25, 13);
      const badge = Math.min(19, w / 4, h / 4.4);
      const nameY = y + h / 2 - (badge > 9 ? badge * 0.35 : -8);
      if (size) parts.push(`<text x="${cx}" y="${nameY}" class="p-name ${v}" style="font-size:${size}px">${esc(name)}</text>`);
      if (badge > 9) {
        const by = nameY + badge + 8;
        parts.push(`<g class="p-badge ${v}"><circle cx="${cx}" cy="${by}" r="${badge}"/><text x="${cx}" y="${by + badge * 0.36}" style="font-size:${badge * 1.1}px">${LOOK[v].mark}</text></g>`);
      }
    } else if (!room.hatch) {
      const label = room.label.split("\n")[0].replace(/（.*$/, "");
      const size = fitText(label, w, 18, 13);
      if (size && h > 26) parts.push(`<text x="${cx}" y="${y + h / 2 + size / 3}" class="p-label" style="font-size:${size}px">${esc(label)}</text>`);
    }
  });
  // 建物の外の壁。
  parts.push(`<rect x="${PAD}" y="${top}" width="${inner}" height="${planH}" class="p-wall"/>`);

  // 水の入り道（青い矢印）。判定ではなく、入りうる所。
  entries.forEach((entry) => {
    parts.push(`<path d="M${entry.x1} ${entry.y1} L${entry.x2} ${entry.y2}" class="p-arrow${level >= 2 ? " on" : ""}" marker-end="url(#p-head)"/>`);
    if (entry.hole) parts.push(`<circle cx="${entry.x1}" cy="${Y(1)}" r="7" class="p-hole"/>`);
    parts.push(`<text x="${entry.lx}" y="${entry.ly}" class="p-entry" text-anchor="${entry.anchor}">${esc(entry.label)}</text>`);
  });

  // 番号のピン。
  const anchors = pinAnchors(shape, X, Y);
  Object.entries(pins).forEach(([key, number]) => {
    const at = anchors[key];
    if (at) parts.push(`<g class="p-pin"><circle cx="${at[0]}" cy="${at[1]}" r="16"/><text x="${at[0]}" y="${at[1] + 6}">${number}</text></g>`);
  });

  const label = level ? `もし水がここまで来たら：${CAPTIONS[level]}` : titleLine();
  return `<svg class="plan-svg${small ? " small" : ""}" viewBox="0 0 ${VW} ${VH}" role="img" aria-label="${esc(label)}">
    <defs><marker id="p-head" markerWidth="5" markerHeight="5" refX="2.6" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 z" class="p-head"/></marker></defs>
    ${parts.join("")}
  </svg>`;
}

function legend() {
  return `<ul class="legend">
    <li class="risk"><i>！</i>止まるおそれ</li>
    <li class="unconfirmed"><i>？</i>未確認（危険という意味ではありません）</li>
    <li class="clear"><i>✓</i>問題なし</li>
    <li class="water"><i>↓</i>水の入り道</li>
    ${S.building?.sample?.views?.some((v) => v.rooms.some((room) => room.key === "tr")) ? "<li>借室＝東京電力の変圧器の部屋</li>" : ""}
  </ul>`;
}

function lifeChips(level = 0) {
  const n = Number(S.floor);
  return `<ul class="life">${TILES.map((tile) => {
    let state = worst(tile.from);
    let mark = LOOK[state].mark;
    if (level) {
      const raw = serviceState(level, SERVICE_OF_TILE[tile.key]);
      state = raw === "stopped" ? "stopped" : raw === "unknown" ? "unconfirmed" : "clear";
      mark = { stopped: "止まる想定", unknown: "？" }[raw] || "使える";
    }
    return `<li class="${state}"><b>${esc(tile.label)}</b><em>${esc(mark)}</em><small>${esc(state === "clear" ? "使える" : tile.small(n))}</small></li>`;
  }).join("")}</ul>`;
}

// ---- 1 場所 ----

// 地図の下の太字1行。凹みを一番に、次に確かめた立地のリスク（浸水の記録など）、なければ土地の高さ。
function placeHeadline() {
  const terrain = terrainLine();
  if (terrain.verdict === "risk") return { ...terrain, sub: "" };
  const risky = (S.place?.location?.rows || []).filter((item) => item.verdict === "risk");
  if (risky.length) return { verdict: "risk", text: risky.map((item) => item.conclusion || item.label).join("・"), sub: terrain.text };
  return { ...terrain, sub: "" };
}

function terrainLine() {
  const reading = S.place?.location?.reading || {};
  const ground = (S.place?.location?.rows || []).find((item) => item.key === "ground");
  if (reading.basin || ground?.verdict === "risk") return { verdict: "risk", text: "周りより低い凹み。周りの水が集まります" };
  const high = reading.high_directions || [];
  if (high.length) return { verdict: "unconfirmed", text: `${high.join("・")}が高く、水が流れてきます` };
  const points = reading.elevation?.points || [];
  if (points.length >= 5) return { verdict: "unconfirmed", text: "周りより少し高い土地（凹みではない）" };
  return { verdict: "unconfirmed", text: "土地の高さは読めませんでした" };
}

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
  let picked = "";
  if (S.place) {
    const terrain = placeHeadline();
    const rows = (S.place.location.rows || [])
      .map((item) => `<li class="${item.verdict}"><b>${esc(PLACE_SHORT[item.key] || item.label)}</b><span>${esc(item.value || "")}</span></li>`)
      .join("");
    const representative = S.place.site.basis === "representative";
    picked = `<div class="picked">
        <p class="place"><b>${esc(S.place.site.label)}</b></p>
        <h2 class="question">この土地で水が来る道</h2>
        <div class="map-box"><div id="site-map" class="site-map" aria-label="地図：ハザードマップと土地の高さ"></div></div>
        <p class="terrain ${terrain.verdict}">${esc(terrain.text)}${terrain.sub ? `<small>${esc(terrain.sub)}</small>` : ""}</p>
        <ul class="place-chips">${rows}</ul>
        ${representative ? `<p class="hint">高さは町丁の代表点の値です。</p>` : ""}
        <label class="floor">住んでいる階<input id="floor" type="number" inputmode="numeric" min="1" max="80" value="${esc(S.floor)}" placeholder="8">階<small>（なくても進めます）</small></label>
        <button type="button" class="primary" data-act="see"${S.busy ? " disabled" : ""}>この建物で見る</button>
      </div>`;
  }
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

// 地図。地理院タイルとハザードマップの色を重ね、東西南北50mの標高を置く。高い方から建物へ水の矢印を引く。
const TILE_PAGE = "https://maps.gsi.go.jp/development/ichiran.html";
const HAZARD_URL = "https://disaportaldata.gsi.go.jp/raster/{layer}/{z}/{x}/{y}.png";
// [緯度の向き, 経度の向き, 方位角]。矢印の字（➜）は回さないと東を向くので、隣の点から建物へ向けるには方位角＋90度回す。
const DIRS = { north: [1, 0, 0], east: [0, 1, 90], south: [-1, 0, 180], west: [0, -1, 270] };

function drawMap() {
  if (S.map) {
    S.map.remove();
    S.map = null;
  }
  const box = document.getElementById("site-map");
  if (!box || !window.L || !S.place) return;
  const { longitude: lng, latitude: lat } = S.place.site;
  const reading = S.place.location.reading || {};
  const map = L.map(box, { zoomControl: false, attributionControl: false, scrollWheelZoom: false, zoomSnap: 0.25 });
  S.map = map;
  L.control.attribution({ prefix: false }).addTo(map);
  L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png", { maxZoom: 18, attribution: `<a href="${TILE_PAGE}" target="_blank" rel="noopener">地理院タイル</a>` }).addTo(map);
  const hazards = reading.hazards || [];
  const shown = hazards.find((item) => item.status === "color") || hazards.find((item) => item.nearby_legend) || null;
  if (shown) {
    L.tileLayer(HAZARD_URL.replace("{layer}", shown.layer), {
      maxNativeZoom: 17,
      maxZoom: 18,
      opacity: 0.6,
      attribution: '<a href="https://disaportal.gsi.go.jp/hazardmap/copyright/opendata.html" target="_blank" rel="noopener">ハザードマップポータルサイト</a>',
    }).addTo(map);
  }
  const points = reading.elevation?.points || [];
  const center = points.find((p) => p.key === "center");
  const meters = reading.elevation?.distance_m || 50;
  const dLat = meters / 111320;
  const dLng = meters / (111320 * Math.cos((lat * Math.PI) / 180));
  points
    .filter((p) => DIRS[p.key] && typeof p.elevation_m === "number")
    .forEach((p) => {
      const [a, b, angle] = DIRS[p.key];
      const at = [lat + a * dLat, lng + b * dLng];
      const higher = center && p.elevation_m > center.elevation_m;
      L.marker(at, { interactive: false, icon: L.divIcon({ className: `m-height${higher ? " up" : ""}`, html: `${p.elevation_m.toFixed(1)}m`, iconSize: [52, 22], iconAnchor: [26, 11] }) }).addTo(map);
      if (higher || reading.basin) {
        const mid = [lat + a * dLat * 0.5, lng + b * dLng * 0.5];
        L.marker(mid, { interactive: false, icon: L.divIcon({ className: "m-flow", html: `<span style="transform:rotate(${angle + 90}deg)">➜</span>`, iconSize: [26, 26], iconAnchor: [13, 13] }) }).addTo(map);
      }
    });
  L.marker([lat, lng], { interactive: false, icon: L.divIcon({ className: "m-site", html: center ? `<b>${center.elevation_m.toFixed(1)}m</b>` : "<b>●</b>", iconSize: [60, 28], iconAnchor: [30, 14] }) }).addTo(map);
  // 東西南北の札と矢印が真ん中の札に重ならない広さ（50m の点が真ん中から約90px）に寄せる。
  map.fitBounds([[lat - dLat * 1.25, lng - dLng * 1.25], [lat + dLat * 1.25, lng + dLng * 1.25]]);
  if (shown) {
    const legend = L.control({ position: "topleft" });
    legend.onAdd = () => {
      const div = L.DomUtil.create("div", "m-legend");
      div.textContent = `色＝${shown.label}の想定`;
      return div;
    };
    legend.addTo(map);
  }
}

// ---- 2 止まるもの ----

function screenTwo() {
  const b = S.building;
  const count = openCount();
  const playing = S.play > 0;
  const sample = example();
  return `<section class="s2">
    <p class="kicker">${esc(b.sample.custom ? townLabel(S.place.site.label) : where())}</p>
    <h1 class="title">${esc(titleLine())}</h1>
    <div class="plan">${plan({ level: S.play })}</div>
    <div class="play-row">
      <button type="button" class="play" data-act="play">${playing ? "❚❚ 止める" : "▶ 水が入る順に見る"}</button>
      <span class="caption">${playing ? `<b>${S.play}. ${esc(CAPTIONS[S.play])}</b>` : ""}</span>
    </div>
    ${playing ? `<p class="hint">${PLAY_NOTE}</p>` : ""}
    ${b.sample.custom ? `<p class="hint">${BORROWED}</p>` : ""}
    ${playing ? "" : legend()}
    ${lifeChips(S.play)}
    ${sample && !playing ? `<p class="hint">${esc(sample)}</p>` : ""}
    <button type="button" class="primary" data-act="to3">${count ? `？を確かめる（未確認 ${count}）` : "確かめた答えを見直す"}</button>
  </section>`;
}

// ---- 3 確かめる ----

function pinsOf(list) {
  const pins = {};
  list.forEach((step, i) => {
    pins[step.key] = i + 1;
  });
  return pins;
}

function screenThree() {
  const b = S.building;
  const count = openCount();
  const cards = QUESTIONS.map((q) => {
    const kind = q.kind(b);
    const item = row(q.row);
    const v = verdict(q.row);
    const unsure = q.row === "power" && b.sample.engineer_unsure;
    const chosen = S.choices[kind] || "none";
    const options = unsure
      ? `<p class="hint">先に、点検報告書で電気主任技術者の名前を確かめます。</p><div class="options"><button type="button" class="option" data-hv="yes">名前がある</button><button type="button" class="option chosen" data-hv="none" aria-pressed="true">まだ</button></div>`
      : `<div class="options">${[...q.options, "none"]
          .map((o) => `<button type="button" class="option${chosen === o ? " chosen" : ""}" data-kind="${kind}" data-choice="${o}" aria-pressed="${chosen === o}">${OPTION_WORDS[o]}</button>`)
          .join("")}</div>`;
    const engineer = q.row === "power" && S.extra.hv === "yes" ? `<p class="hint">電気主任技術者：点検報告書に名前あり　<button type="button" class="option small" data-hv="none">取り消す</button></p>` : "";
    return `<div class="qcard ${v}">
      <p class="qtitle"><span class="no">${q.no}</span>${esc(q.title)}</p>
      ${engineer}${options}
      <details class="qresult ${v}"><summary><b>${LOOK[v].mark} ${LOOK[v].word}</b></summary>${item ? esc(item.summary) : ""}</details>
    </div>`;
  }).join("");
  return `<section class="s3">
    <div class="sticky">
      <div class="count-bar"><span class="count" id="count"><span>未確認</span><b>${count}</b><span>／3</span></span><span class="kicker">管理会社に竣工図で見てもらった答えを入れると、図の色が変わります</span></div>
      <div class="plan">${plan({ pins: pinsOf(steps()), small: true })}</div>
    </div>
    ${b.sample.custom ? `<p class="hint">${BORROWED}</p>` : ""}
    ${cards}
    <div class="qcard read">
      <p class="qtitle">図面の写真から読む（Claude）</p>
      <div class="options">
        <label class="option file">写真・PDFを選ぶ<input type="file" id="plan-file" accept="image/*,application/pdf"></label>
        ${S.sampleId ? `<button type="button" class="option" data-act="read-sample">見本の図面で試す</button>` : ""}
      </div>
      ${readResult()}
    </div>
    <button type="button" class="primary" data-act="to4">管理会社と理事会に渡す</button>
  </section>`;
}

function floorChoice(floor) {
  const text = String(floor || "");
  if (/地下/.test(text)) return "basement";
  if (/^1階/.test(text)) return "ground";
  const m = text.match(/(\d+)階/);
  if (m && Number(m[1]) >= 2) return "upper";
  return null;
}

function readResult() {
  if (S.busy && !S.read) return `<p class="hint">読んでいます…</p>`;
  if (!S.read) {
    const key = S.claude && !S.claude.claude ? "（APIキーがないときは、見本の答えを出します）" : "";
    return `<p class="hint">Claude が部屋と階を読み、答えの候補を出します。入れるかは、あなたが決めます。${key}</p>`;
  }
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

// ---- 4 渡す ----

function asksList(list) {
  return list
    .map((step, i) => `<li><span class="no">${i + 1}</span><div><b>${esc(PLAIN_ASK[step.key] || step.what)}</b><small>頼む先：${esc(step.who)}</small></div></li>`)
    .join("");
}

function costRows() {
  const aid = subsidy();
  return TIERS.map((tier) => {
    const items = measures()
      .filter((m) => m.tier === tier)
      .map((m) => {
        const chip = AID_REGIONS.includes(aid.region) && AID_WORDS[m[aid.region]] ?`<span class="aid ${m[aid.region]}">${AID_WORDS[m[aid.region]]}</span>` : "";
        const where = /^理事会/.test(m.decision) ? "理事会" : m.decision;
        return `<li><div class="m-head"><b>${esc(measureName(m))}</b><span class="m-range">${esc(m.range)}</span></div><div class="m-sub"><small>${esc(where)}</small>${chip}</div></li>`;
      })
      .join("");
    return items ? `<h3 class="tier">${tier}</h3><ul class="measures">${items}</ul>` : "";
  }).join("");
}

function subsidyBox(all = false) {
  const aid = subsidy();
  const cautions = (aid.cautions || []).slice(0, all ? 3 : 1).map((text) => `<li>${esc(text)}</li>`).join("");
  return `<div class="aid-box"><b>${esc(aid.label || "")}</b><p>${esc(aid.rate_label || "")}</p>${cautions ? `<ul>${cautions}</ul>` : ""}</div>`;
}

function boardDecisions() {
  const list = steps();
  const cost = firstStepCost();
  const aid = subsidy();
  const now = measures().filter((m) => m.tier === "今すぐ").map(measureName);
  return `<ol class="decide">
    <li><b>${list.length ? `管理会社に、残りの確認${list.length}つを頼む` : "大事な確認は済んでいます"}</b><small>依頼メモ（図の番号つき）を渡す</small></li>
    ${now.length ? `<li><b>今すぐの手を選ぶ${cost ? `（${esc(cost)}）` : ""}</b><small>${esc(now.join("・"))}</small></li>` : ""}
    <li><b>補助を確かめる</b><small>${esc(aid.label || "")}</small></li>
  </ol>`;
}

function a4Front(date) {
  const b = S.building;
  const rain = b.rain?.third || "";
  return `<div class="sheet front">
    <p class="sheet-tag">理事会資料（表）　${esc(where())}　${date}</p>
    <h1>${esc(titleLine())}</h1>
    <div class="sheet-plan">${plan({ pins: pinsOf(steps()) })}</div>
    ${b.sample.custom ? `<p class="hint">${BORROWED}</p>` : ""}
    ${lifeChips()}
    <h2>理事会で決めること</h2>
    ${boardDecisions()}
    ${rain ? `<h2>大雨が近づいたら</h2><p class="sheet-line strong">${esc(rain)}</p>` : ""}
    <p class="print-fixed">${esc(disclaimer() || "")}</p>
  </div>`;
}

function a4Back() {
  return `<div class="sheet back">
    <p class="sheet-tag">理事会資料（裏）</p>
    <h2>対策の費用の目安と、決める場</h2>
    ${costRows()}
    <h2>補助</h2>
    ${subsidyBox()}
    <div class="print-fixed">${[disclaimer() || "", ...SHEET_FIXED, ...SCOPE_LINES].map((line) => `<p>${esc(line)}</p>`).join("")}</div>
  </div>`;
}

function screenFour() {
  const list = steps();
  const tabs = TABS.map(([key, word]) => `<button type="button" role="tab" class="tab${S.tab === key ? " current" : ""}" data-tab="${key}" aria-selected="${S.tab === key}">${word}</button>`).join("");
  let body = "";
  if (S.tab === "memo") {
    body = `<h1 class="title">${list.length ? `残りの確認${list.length}つを、管理会社に頼む` : "大事な確認は、済んでいます"}</h1>
      <div class="plan">${plan({ pins: pinsOf(list) })}</div>
      ${list.length ? `<ol class="asks">${asksList(list)}</ol>` : ""}`;
  } else if (S.tab === "a4") {
    body = `<h1 class="title">理事会に出すA4表裏1枚</h1>
      <p class="hint">表は30秒で読める図と3行。裏は費用と補助。</p>
      <div class="paper">${a4Front(today())}</div>
      <div class="paper">${a4Back()}</div>`;
  } else {
    const cost = firstStepCost();
    body = `<h1 class="title">${cost ? `最初の手は ${esc(cost)}` : "対策の費用・補助の目安"}</h1>
      ${costRows()}
      ${subsidyBox()}
      <p class="hint">${COST_FIXED}</p>`;
  }
  const print = TABS.find(([key]) => key === S.tab)[2];
  return `<section class="s4">
    <div class="tabs" role="tablist">${tabs}</div>
    ${body}
    <button type="button" class="primary" data-act="print">${print}</button>
  </section>`;
}

function today() {
  const d = new Date();
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}

function printSheet() {
  const b = S.building;
  const list = steps();
  const date = today();
  const fixed = `<p class="print-fixed">${esc(disclaimer() || document.getElementById("fixed-disclaimer").textContent)}</p>`;
  let html = "";
  if (S.tab === "memo") {
    const asks = list
      .map((step, i) => `<li><b>${i + 1}. ${esc(PLAIN_ASK[step.key] || step.what)}</b><br>頼む先：${esc(step.who)}${step.memo_no ? `（確認の番号 ${esc(step.memo_no)}）` : ""}</li>`)
      .join("");
    html = `<div class="sheet">
      <h1>管理会社への確認のお願い</h1>
      <p>${esc(where())}　作成日：${date}</p>
      <div class="sheet-plan">${plan({ pins: pinsOf(list) })}</div>
      <p>図の番号の所を、竣工図と点検の記録で確かめてください。住民・理事・管理員は、電気やポンプの部屋に入りません。</p>
      <ol class="print-asks">${asks}</ol>
      <p>答えが分かったら、マンション浸水ロードマップの「3 確かめる」に入れると、図の色が変わります。</p>
      ${fixed}
    </div>`;
  } else if (S.tab === "a4") {
    html = a4Front(date) + a4Back();
  } else {
    html = `<div class="sheet"><h1>対策の費用・補助の目安</h1><p>${esc(where())}　${date}</p>${costRows()}${subsidyBox(true)}<p class="sheet-line">${COST_FIXED}</p>${fixed}</div>`;
  }
  const box = document.getElementById("print-memo");
  box.innerHTML = html;
  box.dataset.kind = S.tab;
  window.print();
}

// ---- 描く ----

function render() {
  const views = { 1: screenOne, 2: screenTwo, 3: screenThree, 4: screenFour };
  screen.innerHTML = views[S.screen]();
  document.querySelectorAll("#steps [data-go]").forEach((button) => {
    const n = Number(button.dataset.go);
    button.disabled = n > S.reached;
    button.classList.toggle("current", n === S.screen);
    button.setAttribute("aria-current", n === S.screen ? "step" : "false");
  });
  const text = disclaimer();
  if (text) document.getElementById("fixed-disclaimer").textContent = text;
  if (S.screen === 1) drawMap();
  else if (S.map) {
    S.map.remove();
    S.map = null;
  }
  S.flash = [];
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
    S.candidates = [];
    S.message = "";
    S.building = null;
    S.choices = {};
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

// 判定に送る答え。見本は見本の答えのまま。自分の建物は、画面3で図面の階が分かったときだけ部屋の階を送る。
function answers() {
  if (S.sampleId) return { ...S.extra };
  const floors = Object.values(S.choices);
  const roomsFloor = ["basement", "ground", "upper"].find((f) => floors.includes(f)) || "unknown";
  return { rooms_floor: roomsFloor, basement: roomsFloor === "basement" ? "yes" : "unknown", ...S.extra };
}

function confirmedTokens() {
  return Object.entries(S.choices).flatMap(([kind, choice]) => {
    if (choice === "basement" || choice === "ground") return [kind];
    if (choice === "upper") return [`upper:${kind}`];
    if (choice === "absent") return [`absent:${kind}`];
    return [];
  });
}

async function loadBuilding() {
  const location = S.place.location;
  const reading = location.reading || {};
  const before = S.building ? Object.fromEntries(S.building.equipment.map((item) => [item.key, item.verdict])) : null;
  S.building = await postJSON("/api/building", {
    sample_id: S.sampleId,
    answers: answers(),
    label: S.place.site.label,
    confirmed: confirmedTokens(),
    document_read: false,
    directions: {},
    low_directions: reading.low_directions || [],
    high_directions: reading.high_directions || [],
    basin: Boolean(reading.basin),
    statements: S.statements,
    location_rows: location.rows,
  });
  // 色が変わった部屋を光らせる。
  if (before) {
    S.flash = Object.entries(KIND_ROWS)
      .filter(([, key]) => row(key) && before[key] !== row(key).verdict)
      .map(([room]) => room);
  }
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
  if (choice === "none") delete S.choices[kind];
  else S.choices[kind] = choice;
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
  clearTimeout(S.timer);
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
  } else if (target.dataset.hv) {
    setEngineer(target.dataset.hv);
  } else if (target.dataset.kind) {
    setRoom(target.dataset.kind, target.dataset.choice);
  } else if (target.dataset.tab) {
    S.tab = target.dataset.tab;
    render();
  } else {
    const act = target.dataset.act;
    if (act === "see") seeBuilding();
    if (act === "play") (S.play ? stopPlay() : startPlay());
    if (act === "to3") go(3);
    if (act === "to4") go(4);
    if (act === "read-sample") readPlan(null);
    if (act === "print") printSheet();
  }
});

// 住んでいる階は、描き直さずに覚えるだけ（地図を読み直さない）。
screen.addEventListener("input", (event) => {
  if (event.target.id === "floor") S.floor = event.target.value;
});

screen.addEventListener("change", (event) => {
  if (event.target.id === "plan-file" && event.target.files[0]) readPlan(event.target.files[0]);
});

document.getElementById("steps").addEventListener("click", (event) => {
  const button = event.target.closest("[data-go]");
  if (button && !button.disabled) go(Number(button.dataset.go));
});

// ---- Claude の API キー（このパソコンの localhost で開いたときだけ） ----

function renderKey() {
  renderChatRoute();
  const toggle = document.getElementById("key-toggle");
  const local = ["localhost", "127.0.0.1"].includes(location.hostname);
  if (!S.claude) return;
  toggle.hidden = !local && !S.claude.claude;
  toggle.textContent = S.claude.claude ? "● Claude" : "○ Claude";
  toggle.classList.toggle("on", Boolean(S.claude.claude));
  toggle.disabled = !local || S.claude.key_source === "env";
  toggle.title = S.claude.claude ? "Claude API 接続済み（キーを変える）" : "APIキーを設定";
}

async function loadStatus() {
  try {
    S.claude = await getJSON("/api/status");
  } catch (error) {
    S.claude = null;
  }
  renderKey();
}

document.getElementById("key-toggle").addEventListener("click", () => {
  const form = document.getElementById("key-form");
  form.hidden = !form.hidden;
});

document.getElementById("key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("key-input");
  const note = document.getElementById("key-note");
  const key = input.value;
  input.value = "";
  if (!key.trim()) {
    note.textContent = "キーが入っていません。";
    return;
  }
  try {
    S.claude = await postJSON("/api/key", { key });
    note.textContent = S.claude.key_source === "env" ? "保存しました。環境変数のキーを優先して使います。" : "保存しました。";
    renderKey();
  } catch (error) {
    note.textContent = error.message;
  }
});

// ---- 質問する（チャット） ----
// 答えのたびに、どこから答えたか（Claude／固定の文／説明カード）を出す。
// 立入・操作・接触の危ない質問は、サーバーが AI を通さず固定の文で答える（ここでは何も塞がない）。

// 送る前に、Anthropic の API を通るかを出す（F-038）。表示を替えるだけで API は呼ばない。
const CHAT_ROUTE_TEXT = {
  claude: "送った質問と、この画面の住所・答え・判定は Anthropic の API を通ります。図面と書類の中身は送りません。",
  none: "AI を通さず、説明カードで答えます",
};
const SOURCE_NAMES = { claude: "Claude", fixed: "固定の文（AIを通していません）", fallback: "説明カード（AIを通していません）" };
const chatHistory = [];
let chatWaiting = null;

function renderChatRoute() {
  const route = document.getElementById("chat-route");
  route.textContent = S.claude?.claude ? CHAT_ROUTE_TEXT.claude : CHAT_ROUTE_TEXT.none;
  route.classList.toggle("api", Boolean(S.claude?.claude));
}

// チャットに渡す、この画面の中身。住所は町丁まで。
function chatContext() {
  const b = S.building;
  if (!b) return { sample_id: S.sampleId, site: townLabel(S.place?.site?.label || "") };
  return {
    sample_id: S.sampleId,
    answers: answers(),
    subsidy: b.sample.subsidy,
    name: b.sample.name,
    site: townLabel(S.place.site.label),
    location: S.place.location.rows.map((item) => ({ label: item.label, verdict: item.verdict_label, summary: item.summary, confirm_short: item.confirm_short })),
    equipment: b.equipment.map((item) => ({ label: item.label, verdict: item.verdict_label, summary: item.summary, confirm_by: item.confirm_by })),
    places: b.sample.pins.map((pin) => ({ key: pin.key, title: pin.title, how_water: pin.how_water, who: pin.who })),
    direction: b.direction_line,
    water: S.play || "",
  };
}

// チャットの答えについてくる画面の操作。平面図の部屋を光らせる・水の順を再生する・費用を開く・聞き取りを記録する。
async function applyAction(action) {
  if (!S.building) return;
  if (action.type === "focus") {
    if (![2, 3, 4].includes(S.screen)) go(2);
    if (S.screen === 4) S.tab = "memo";
    S.flash = [action.target];
    render();
  } else if (action.type === "water") {
    go(2);
    startPlay();
  } else if (action.type === "measure") {
    S.tab = "cost";
    go(4);
  } else if (action.type === "statement") {
    S.statements = [...S.statements, action.text];
    await loadBuilding();
    render();
  }
}

function chatAdd(role, text, note) {
  const log = document.getElementById("chat-log");
  const message = document.createElement("div");
  message.className = `chat-message chat-${role}`;
  const body = document.createElement("p");
  body.textContent = text;
  message.append(body);
  if (note) {
    const small = document.createElement("small");
    small.textContent = note;
    message.append(small);
  }
  log.append(message);
  log.scrollTop = log.scrollHeight;
  return message;
}

document.getElementById("chat-toggle").addEventListener("click", () => {
  document.getElementById("chat").hidden = false;
  document.getElementById("chat-toggle").hidden = true;
  renderChatRoute();
  document.getElementById("chat-input").focus();
});

document.getElementById("chat-close").addEventListener("click", () => {
  document.getElementById("chat").hidden = true;
  document.getElementById("chat-toggle").hidden = false;
});

document.getElementById("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  // 答えの順番が入れ替わらないよう、答えが返るまで次を受けない。
  if (!text || chatWaiting) return;
  input.value = "";
  chatAdd("user", text);
  chatWaiting = chatAdd("wait", "考えています。");
  try {
    const result = await postJSON("/api/chat", { message: text, history: chatHistory, context: chatContext() });
    chatWaiting.remove();
    chatWaiting = null;
    chatAdd("assistant", result.text, [SOURCE_NAMES[result.source], result.notice].filter(Boolean).join("　"));
    chatHistory.push({ role: "user", content: text }, { role: "assistant", content: result.text });
    for (const action of result.actions || []) await applyAction(action);
  } catch (error) {
    chatWaiting?.remove();
    chatWaiting = null;
    chatAdd("assistant", "接続できませんでした。");
  }
});

render();
loadPoints();
loadStatus();
