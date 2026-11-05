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
  // 自分の建物で、住民が答えられる2つ（何階建てか・地下はあるか）。分からないときは空のまま。
  own: { floors: "", basement: "unknown" },
  // 画面3：図面が手元にあるか（null は未回答）と、図面がない人が見て答えたこと。
  drawing: null,
  obs: {},
  // 画面1：この辺りが水につかった経験（住民の話。判定は変えず、依頼メモに載せる）。
  exp: "",
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
  // 自分の建物は「（見本の形）」と添える。上の「スロープから」の札と重ならないよう、短く小さく書く。
  const floorName = esc(view.name.replace("平面図", ""));
  parts.push(sample.custom ? `<text x="${PAD}" y="30" class="p-floor small">${floorName}（見本の形）</text>` : `<text x="${PAD}" y="30" class="p-floor">${floorName}の平面図</text>`);

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

// ---- 浸水の深さを建物に重ねる（2026-11-05） ----
// ハザードマップの深さの帯（立地の行の value のまま）を、建物の階に置き換えて見せる。
// 階の高さは分からないので「1階を約3m」とした描くための目安とし、その旨を必ず添える。判定はしない。
const STORY_M = 3;
const HAZARD_WORDS = { flood: "川があふれると", inland: "下水や水路があふれると", surge: "高潮のとき" };
const STORY_NOTE = "1階を約3mとした目安です。実際の階の高さは建物で違います。";

function parseBand(value) {
  const m = String(value || "").match(/^(\d+(?:\.\d+)?)?m?〜(\d+(?:\.\d+)?)?m?$/);
  if (!m || (m[1] === undefined && m[2] === undefined)) return null;
  const low = m[1] === undefined ? 0 : Number(m[1]);
  const high = m[2] === undefined ? null : Number(m[2]);
  return { low, high };
}

// 立地の行のうち、一番深い想定（洪水・内水・高潮）。なければ null。
function deepestHazard() {
  const rows = (S.place?.location?.rows || []).filter((item) => HAZARD_WORDS[item.key]);
  let best = null;
  rows.forEach((item) => {
    const band = parseBand(item.value);
    if (!band) return;
    const depth = band.high === null ? band.low + 10 : band.high;
    if (!best || depth > best.depth) best = { ...band, depth, key: item.key, value: item.value, conclusion: item.conclusion || "" };
  });
  return best;
}

// 深さを階の言葉にする（1階を約3mとした割り算だけ）。
function storyWords(band) {
  if (band.high === null) return `${Math.ceil(band.low / STORY_M) + 1}階より上まで`;
  if (band.high <= 0.5) return "1階の床の近くまで";
  const floor = Math.ceil(band.high / STORY_M);
  return floor <= 1 ? "1階が水につかる深さ" : `1階の天井を超え、${floor}階まで`;
}

// 小さな建物の横から見た絵に、想定の深さの水を重ねる。人の背丈を目盛りに添える。
function depthPicture(band) {
  const G = 150;
  const px = 10; // 1m あたり
  const top = 20;
  const parts = [`<rect x="0" y="0" width="340" height="190" class="c-sky"/>`];
  parts.push(`<rect x="0" y="${G}" width="340" height="40" class="c-soil"/>`);
  for (let i = 0; i < 4; i += 1) {
    const y = G - (i + 1) * STORY_M * px;
    parts.push(`<rect x="150" y="${y}" width="130" height="${STORY_M * px}" class="c-floor"/>`);
    parts.push(`<text x="158" y="${y + 19}" class="c-label">${i + 1}階</text>`);
  }
  parts.push(`<text x="286" y="${G - 4 * STORY_M * px + 4}" class="c-label">↑上の階</text>`);
  parts.push(`<rect x="150" y="${G}" width="130" height="30" class="c-under"/>`);
  parts.push(`<text x="158" y="${G + 20}" class="c-label">地下（あれば）</text>`);
  const high = band.high === null ? (G - top) / px : Math.min(band.high, (G - top) / px);
  parts.push(`<rect x="0" y="${G - high * px}" width="340" height="${high * px}" class="d-water"/>`);
  if (band.low > 0) parts.push(`<line x1="0" y1="${G - band.low * px}" x2="340" y2="${G - band.low * px}" class="d-low"/>`);
  parts.push(`<line x1="0" y1="${G - high * px}" x2="340" y2="${G - high * px}" class="d-high"/>`);
  parts.push(`<text x="8" y="${G - high * px - 6}" class="d-label">${esc(band.value)}</text>`);
  // 人の背丈（約1.7m）の目盛り
  const h = 17;
  parts.push(`<g class="d-person"><circle cx="100" cy="${G - h + 3}" r="3"/><line x1="100" y1="${G - h + 6}" x2="100" y2="${G - 6}"/><line x1="100" y1="${G - 6}" x2="96" y2="${G}"/><line x1="100" y1="${G - 6}" x2="104" y2="${G}"/><line x1="95" y1="${G - 12}" x2="105" y2="${G - 12}"/></g>`);
  parts.push(`<line x1="0" y1="${G}" x2="340" y2="${G}" class="c-ground"/>`);
  return `<svg class="depth-svg" viewBox="0 0 340 190" role="img" aria-label="${esc(`${HAZARD_WORDS[band.key]}${band.value}。${storyWords(band)}`)}">${parts.join("")}</svg>`;
}

// 深さの札の行と、地図に重ねる層の対応（洪水は想定最大を先に）。地図と札で同じ層を使う。
const LAYERS_OF_ROW = { flood: ["flood_max", "flood_planned"], inland: ["inland"], surge: ["storm_surge"] };

function hazardLayer(band) {
  if (!band) return null;
  const hazards = S.place?.location?.reading?.hazards || [];
  const usable = (item) => item.status === "color" || item.nearby_legend;
  return (LAYERS_OF_ROW[band.key] || []).map((key) => hazards.find((item) => item.key === key && usable(item))).find(Boolean) || null;
}

// 札の前提（2026-11-05 本人の指摘で足した）。どの雨の想定か・どこの値か・帯のどちらの端か・1階の床の高さ。
// 想定の名前の意味（言葉の意味だけ。確率の数字は書かない）。
const SCENARIO_WORDS = { flood_max: "想定しうる最大の大雨", flood_planned: "川の整備の目標の大雨" };
const SCENARIO_ORDER = ["flood_planned", "flood_max", "inland", "storm_surge", "tsunami"];

// 同じ場所の想定を並べる（サーバーの reading.hazards のまま）。一番深いものだけを見せない。
function scenarioRows() {
  const hazards = S.place?.location?.reading?.hazards || [];
  return SCENARIO_ORDER.map((key) => hazards.find((item) => item.key === key)).filter(Boolean).map((item) => {
    let value = "データなし";
    let cls = "none";
    if (item.legend) {
      value = item.legend;
      cls = "color";
    } else if (item.nearby_legend) {
      value = `${item.nearby_legend}（この点ではなく近くに色）`;
      cls = "color";
    } else if (item.status === "no_color") {
      value = "この点に色なし";
      cls = "nocolor";
    }
    return { key: item.key, name: item.label, words: SCENARIO_WORDS[item.key] || "", value, cls };
  });
}

// 水が引くまでの時間（浸水継続時間、想定最大規模）。サーバーが凡例の色で読んだ区分のまま。読めないときは出さない。
function durationLine() {
  const reading = S.place?.location?.reading || {};
  const item = (reading.durations || []).find((d) => d.legend || d.nearby_legend);
  if (!item) return "";
  const value = item.legend || `${item.nearby_legend}（この点ではなく近くに色）`;
  const note = /2週間以上/.test(value) && reading.duration_note ? `<small>${esc(reading.duration_note)}</small>` : "";
  return `<p class="duration">水が引くまで <b>${esc(value)}</b><small>${esc(item.label)}の想定</small>${note}</p>`;
}

function scenarioTable() {
  const rows = scenarioRows();
  if (!rows.length) return "";
  return `<table class="scenarios"><caption>同じ場所の、ほかの想定</caption>${rows
    .map((row) => `<tr class="${row.cls}"><th>${esc(row.name)}${row.words ? `<small>${esc(row.words)}</small>` : ""}</th><td>${esc(row.value)}</td></tr>`)
    .join("")}</table>`;
}

function depthConditions(band) {
  const lines = [];
  lines.push(S.place?.site?.basis === "representative" ? "町丁の代表点の値で、建物の位置の値ではありません" : "建物の位置として選んだ点の値です");
  // 点そのものに色がなく、近くの色の値を使ったときは、その旨（サーバーの文のまま）。
  if (/先に色/.test(band.conclusion)) lines.push(band.conclusion);
  if (band.high !== null && band.low > 0) lines.push(`${band.value}の深い方（${band.high}m）で描いています`);
  lines.push("深さは地面から。1階の床が地面より高い建物では、その分浅くなります");
  lines.push(STORY_NOTE);
  return lines;
}

function depthCard() {
  const band = deepestHazard();
  if (!band) return `<p class="depth-none">ハザードマップの深さの色は、この点にありません（データがない所もあり、浸水しないという意味ではありません）。</p>${inlandNote()}`;
  return `<div class="depth">
    <p class="depth-lead">${esc(leadWords(band))} <b>${esc(band.value)}</b></p>
    <p class="depth-words">${esc(storyWords(band))}</p>
    <div class="depth-art">${depthPicture(band)}</div>
    ${durationLine()}
    ${scenarioTable()}
    ${inlandNote()}
    <ul class="depth-conds">${depthConditions(band).map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
  </div>`;
}

// 札の一行目。どの想定の深さかを、頭に言う（例：想定しうる最大の大雨で川があふれると）。
function leadWords(band) {
  const layer = hazardLayer(band);
  const words = layer && SCENARIO_WORDS[layer.key];
  return words ? `${words}で${HAZARD_WORDS[band.key]}` : HAZARD_WORDS[band.key];
}

// ---- 内水と、この辺りの経験（2026-11-05） ----
// 内水（下水や水路があふれる）は、国の重ねるハザードマップにデータがない所が多い。市区町村が別に出していることがあるので案内する。
const WAGAMACHI = "https://disaportal.gsi.go.jp/hazardmap/";

function inlandNote() {
  const inland = (S.place?.location?.reading?.hazards || []).find((item) => item.key === "inland");
  if (inland && (inland.legend || inland.nearby_legend)) return "";
  return `<p class="inland-note">下水や水路があふれる浸水（内水）は、この地図にデータがありません。大雨のときの道路の冠水は、こちらによることがあります。市区町村が別に地図を出していることがあるので、<a href="${WAGAMACHI}" target="_blank" rel="noopener">わがまちハザードマップ（国土地理院）</a>で市区町村を選んで確かめてください。</p>`;
}

// 住民が知っている、この辺りの経験。地図にない内水の手がかりになる。判定は変えず、依頼メモに「聞き取り」として載せる。
const EXPERIENCE = [
  ["none", "ない"],
  ["shallow", "くるぶし〜すねくらい"],
  ["deep", "ひざより上"],
  ["unknown", "分からない"],
];
const EXPERIENCE_SAYS = {
  none: "この辺りで、道路や敷地が水につかったのを見たことはない",
  shallow: "この辺りで、道路や敷地がくるぶし〜すねくらいまで水につかったことがある",
  deep: "この辺りで、道路や敷地がひざより上まで水につかったことがある",
};

function experienceQuestion() {
  const chips = EXPERIENCE.map(([key, word]) => `<button type="button" class="option${S.exp === key ? " chosen" : ""}" data-exp="${key}" aria-pressed="${S.exp === key}">${word}</button>`).join("");
  return `<div class="own">
    <p class="own-head">この辺りで、大雨のときに道路や敷地が水につかったことはありますか？</p>
    <div class="options">${chips}</div>
    <p class="hint">地図にない浸水の手がかりになります。判定の色は変えず、管理会社への依頼メモに載せます。</p>
  </div>`;
}

// 依頼メモの一行。建物の図面ではなく、市区町村（下水道の担当）に内水の記録と想定を確かめてもらう。
function experienceLine() {
  const says = EXPERIENCE_SAYS[S.exp];
  // 見出し「住民の話・見たこと」の下に並べるので、文の頭に「住民の話」は付けない。
  if (!says || S.exp === "none") return says ? `${says}。` : "";
  return `${says}。地図にない内水の手がかりなので、管理会社から市区町村（下水道の担当）に、この辺りの浸水の記録と内水の想定を確かめてください。`;
}

// ---- 1 場所 ----

// 地図の下の太字1行。凹みを一番に、次に確かめた立地のリスク（浸水の記録など）、なければ土地の高さ。
function placeHeadline() {
  const terrain = terrainLine();
  if (terrain.verdict === "risk") return { ...terrain, sub: "" };
  const risky = (S.place?.location?.rows || []).filter((item) => item.verdict === "risk");
  // どの項目の話かが分かるよう、項目の短い名前を頭に付ける（例：高潮：想定に色あり）。
  if (risky.length) return { verdict: "risk", text: risky.map((item) => `${PLACE_SHORT[item.key] || item.label}：${item.conclusion || item.value || ""}`).join("／"), sub: terrain.text };
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

// 自分の建物だけ、住民が外から答えられる2つを聞く（分からなくても進める）。
function ownQuestions() {
  const chips = [["yes", "ある"], ["no", "ない"], ["unknown", "分からない"]]
    .map(([key, word]) => `<button type="button" class="option${S.own.basement === key ? " chosen" : ""}" data-own="${key}" aria-pressed="${S.own.basement === key}">${word}</button>`)
    .join("");
  return `<div class="own">
    <p class="own-head">あなたの建物（分からなくても進めます）</p>
    <label class="floor">何階建て<input id="own-floors" type="number" inputmode="numeric" min="1" max="80" value="${esc(S.own.floors)}" placeholder="11">階建て</label>
    <div class="own-row"><span>地下は</span><div class="options">${chips}</div></div>
  </div>`;
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
        ${depthCard()}
        <div class="map-box"><div id="site-map" class="site-map" aria-label="地図：ハザードマップと土地の高さ"></div></div>
        ${mapLegend()}
        ${S.sampleId ? "" : `<p class="pin-hint ${S.place.site.basis === "building" ? "done" : ""}">${S.place.site.basis === "building" ? "建物の位置として選んだ点の値で読んでいます。違えば、もう一度地図を押してください。" : "地図で、あなたの建物の場所を押してください。その位置の値で読み直します（今は町丁の代表点の値です）。"}</p>`}
        <p class="terrain ${terrain.verdict}">${esc(terrain.text)}${terrain.sub ? `<small>${esc(terrain.sub)}</small>` : ""}</p>
        <ul class="place-chips">${rows}</ul>
        ${representative ? `<p class="hint">高さは町丁の代表点の値です。</p>` : ""}
        ${S.sampleId ? "" : ownQuestions()}
        ${S.sampleId ? "" : experienceQuestion()}
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
  // 上の深さの札と同じ想定の層を重ねる（洪水は想定最大を先に）。なければ色のある層。
  const shown = hazardLayer(deepestHazard())
    || hazards.find((item) => item.status === "color") || hazards.find((item) => item.nearby_legend) || null;
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
      // 高い・低いは、サーバーと同じ目安（0.1m 以上の差）で決める。差がそれより小さい所は「ほぼ同じ」。
      const higher = (reading.high_directions || []).includes(p.label);
      const lower = (reading.low_directions || []).includes(p.label);
      const cls = higher ? " up" : lower ? " down" : " same";
      L.marker(at, { interactive: false, icon: L.divIcon({ className: `m-height${cls}`, html: `${p.elevation_m.toFixed(1)}m`, iconSize: [52, 22], iconAnchor: [26, 11] }) }).addTo(map);
      // 水の矢印は、建物より高い方からだけ引く（凹みでも、低い方からは引かない）。
      if (higher) {
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
  // 自分の建物は、地図を押すと、その点を建物の位置として読み直す（見本は架空の建物なので動かさない）。
  if (!S.sampleId) {
    map.on("click", (event) => movePin(event.latlng.lat, event.latlng.lng));
    box.classList.add("pickable");
  }
}

// 地図で押した点を、建物の位置として読み直す（サーバーの pin=1。値の説明は「建物の位置として選んだ点」になる）。
// 住所の名前・建物の答え（階数・地下）はそのまま。読み直すまで、ほかの操作は待たせる。
async function movePin(lat, lng) {
  if (S.busy || !S.place) return;
  S.busy = true;
  S.error = "";
  render();
  try {
    const params = { address: S.place.site.label, longitude: lng.toFixed(6), latitude: lat.toFixed(6), pin: "1" };
    S.place = await getJSON(`/api/location?${new URLSearchParams(params)}`);
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

// ---- 2 止まるもの ----
// 3段で見せる。①断面の切り絵で、どう浸水するか ②暮らしが止まるまでの時間 ③平面図で、どこを確かめるか。
// 切り絵は見本の形（階数・地下の有無・機械の部屋）から描く説明用の模式で、部屋の色は判定のまま、止まるかはサーバーの scenario のまま。

// 住民が過ごす時間の順（前の時間の再生と同じ段の名前。サーバーの五段の表の列の順）。
const PHASES = [
  { key: "before", name: "大雨が近づいたとき", line: "外の道路に水がたまり始める。建物の中はまだ使える" },
  { key: "day", name: "水が来た当日", line: "スロープや壁の穴から地下へ水が入り、エレベーター、続いて水と電気が止まる" },
  { key: "morning", name: "水が引いた翌朝", line: "外の道路は乾いても、地下には水が残る。水を抜くまで機械室に入れない" },
  { key: "week", name: "数日〜1週間", line: "水を抜いても、浸かった機械は止まったまま。点検と修理を待つ" },
  { key: "months", name: "約2か月〜本復旧", line: "浸かった盤や部品が届いて付け替わるまで、止まったままのことがある" },
];
const MACHINE_KEYS = [["elec", "panel_room"], ["tr"], ["pump"]];

// 断面の切り絵（斜めから見た建物の切り口）。説明用の模式で、高さの値ではない。
function cutaway(level = 0) {
  const b = S.building;
  const sample = b.sample;
  const under = sample.archetype !== "ground";
  const W = 360;
  const G = under ? 196 : 236;
  const x0 = 64;
  const x1 = 262;
  const dx = 30;
  const dy = 18;
  const top = 34;
  const shown = Math.min(sample.floors || 6, 6);
  // 地下のない建物は、1階を機械の部屋の帯（高め）にし、住まいの階をその上に並べる。
  const band_ = under ? 0 : 62;
  const homesShown = under ? shown : shown - 1;
  const fh = (G - band_ - top) / homesShown;
  const homes = level ? serviceState(level, "homes") : "running";
  const evOff = level && serviceState(level, "ev") === "stopped";
  const parts = [];
  parts.push(`<rect x="0" y="0" width="${W}" height="300" class="c-sky"/>`);
  // 地面と土
  parts.push(`<rect x="0" y="${G}" width="${W}" height="${300 - G}" class="c-soil"/>`);
  // 建物の上と横（斜めの面）
  parts.push(`<polygon points="${x0},${top} ${x1},${top} ${x1 + dx},${top - dy} ${x0 + dx},${top - dy}" class="c-roof"/>`);
  parts.push(`<polygon points="${x1},${top} ${x1 + dx},${top - dy} ${x1 + dx},${G - dy} ${x1},${G}" class="c-side"/>`);
  // 住まいの階（窓の明かり）
  for (let i = 0; i < homesShown; i += 1) {
    const y = top + i * fh;
    parts.push(`<rect x="${x0}" y="${y}" width="${x1 - x0}" height="${fh}" class="c-floor"/>`);
    // 窓は4つ。右のエレベーターの通り道に重ねない。
    for (let k = 0; k < 4; k += 1) {
      const wx = x0 + 12 + k * 40;
      const off = homes === "stopped";
      parts.push(`<rect x="${wx}" y="${y + fh * 0.26}" width="26" height="${fh * 0.48}" rx="2" class="c-win${off ? " off" : ""}"/>`);
    }
  }
  // 階数は、見本なら見本の値、自分の建物なら答えたときだけ。分からなければ「未確認」と書く。
  const knownFloors = sample.custom ? Number(sample.answers?.floors) || 0 : sample.floors;
  if (!knownFloors || knownFloors > shown) parts.push(`<path d="M${x0 - 4} ${top + fh * 1.5} l8 -5 l8 5 l8 -5" class="c-break"/>`);
  parts.push(`<text x="${x1 + dx + 4}" y="${top - dy + 4}" class="c-label" text-anchor="end">${knownFloors ? `${knownFloors}階建て` : "階数は未確認"}</text>`);
  // 機械の部屋（地下の階、なければ1階）
  const roomTop = under ? G + 6 : G - band_ + 4;
  const roomBottom = under ? G + 66 : G;
  if (under) parts.push(`<rect x="${x0}" y="${G}" width="${x1 - x0}" height="${roomBottom - G + 4}" class="c-basement"/>`);
  else parts.push(`<rect x="${x0}" y="${G - band_}" width="${x1 - x0}" height="${band_}" class="c-basement"/>`);
  const roomW = (x1 - x0 - 40) / 3;
  MACHINE_KEYS.forEach((keys, i) => {
    const room = b.sample.views.flatMap((v) => v.rooms).find((r) => keys.includes(r.key));
    if (!room) return;
    const rowKey = KIND_ROWS[room.key];
    const v = row(rowKey) ? row(rowKey).verdict : "unconfirmed";
    const rx = x0 + 4 + i * (roomW + 2);
    parts.push(`<rect x="${rx}" y="${roomTop}" width="${roomW}" height="${roomBottom - roomTop - 2}" class="c-room ${v}"/>`);
    parts.push(`<text x="${rx + roomW / 2}" y="${roomTop + 16}" class="c-room-name ${v}">${esc(ROOM_SHORT[room.key])}</text>`);
    parts.push(`<rect x="${rx + roomW / 2 - 12}" y="${roomBottom - 30}" width="24" height="18" rx="2" class="c-box"/>`);
  });
  // エレベーター（地下まで通る）
  const evX = x1 - 32;
  parts.push(`<rect x="${evX}" y="${top + 4}" width="26" height="${roomBottom - top - 2}" class="c-ev${evOff ? " off" : ""}"/>`);
  parts.push(`<rect x="${evX + 4}" y="${top + fh * 1.2}" width="18" height="${fh * 0.7}" class="c-car"/>`);
  parts.push(`<text x="${evX + 13}" y="${top + fh * 1.2 - 4}" class="c-ev-label">EV</text>`);
  if (evOff) parts.push(`<text x="${evX + 13}" y="${top + fh * 2.4}" class="c-stop">止</text>`);
  // 地面の線・道路・入り道
  parts.push(`<line x1="0" y1="${G}" x2="${W}" y2="${G}" class="c-ground"/>`);
  parts.push(`<text x="6" y="${G - 8}" class="c-label">道路</text>`);
  // 自分の建物は、機械の部屋の位置が分からない。見本の形を借りていることを、絵の中に書く。
  if (sample.custom) {
    const where = sample.answers?.basement === "yes" ? "地下あり（機械の部屋の階は未確認）" : sample.answers?.basement === "no" ? "地下なし（機械の部屋の階は未確認）" : "地下の有無は未確認";
    // 右上の「階数」の札と重ならないよう、左上に2行で書く。
    parts.push(`<rect x="4" y="4" width="196" height="34" rx="4" class="c-tag"/>`);
    parts.push(`<text x="10" y="18" class="c-tag-text">見本の形を借りた絵</text>`);
    parts.push(`<text x="10" y="32" class="c-tag-sub">${esc(where)}</text>`);
  }
  const routes = [];
  if (under) {
    // スロープ（右から地下へ）と、道路の下の管から電気室の壁の穴へ
    routes.push(`M${W - 6} ${G} L${x1 + 30} ${G} L${x1 + 2} ${roomBottom - 8}`);
    parts.push(`<path d="M${W} ${G + 1} L${x1 + 30} ${G + 1} L${x1 + 2} ${roomBottom - 6} L${x1 + 2} ${roomBottom + 6} L${W} ${roomBottom + 6} Z" class="c-ramp"/>`);
    parts.push(`<rect x="22" y="${G + 2}" width="16" height="16" class="c-hh"/>`);
    routes.push(`M30 ${G + 18} L30 ${roomTop + 34} L${x0 + 2} ${roomTop + 34}`);
    parts.push(`<circle cx="${x0 + 1}" cy="${roomTop + 34}" r="4" class="c-hole"/>`);
  } else {
    routes.push(`M8 ${G - 4} L${x0 + 2} ${G - 6}`);
  }
  // この場所の想定の深さ（ハザードマップの帯）。1階を約3mとして、切り絵の階の高さに合わせて引く。
  const band = deepestHazard();
  if (band) {
    const yOf = (m) => {
      if (under) return G - (m / STORY_M) * fh;
      if (m <= STORY_M) return G - (m / STORY_M) * band_;
      return G - band_ - ((m - STORY_M) / STORY_M) * fh;
    };
    const highM = band.high === null ? band.low + STORY_M : band.high;
    const yHigh = Math.max(top - dy, yOf(highM));
    parts.push(`<rect x="0" y="${yHigh}" width="${W}" height="${G - yHigh}" class="h-band"/>`);
    parts.push(`<line x1="0" y1="${yHigh}" x2="${W}" y2="${yHigh}" class="h-line"/>`);
    parts.push(`<text x="4" y="${yHigh - 5}" class="h-label">この場所の想定 ${esc(band.value)}</text>`);
  }
  // 水
  if (level >= 1) {
    parts.push(`<rect x="0" y="${G - 7}" width="${x0}" height="7" class="c-water"/>`);
    parts.push(`<rect x="${x1 + dx}" y="${G - 7}" width="${W - x1 - dx}" height="7" class="c-water"/>`);
  }
  if (level >= 2) parts.push(`<rect x="${x0 + 2}" y="${roomBottom - 10}" width="${x1 - x0 - 4}" height="10" class="c-water"/>`);
  if (level >= 3) parts.push(`<rect x="${x0 + 2}" y="${roomBottom - 34}" width="${x1 - x0 - 4}" height="34" class="c-water"/>`);
  routes.forEach((d) => parts.push(`<path d="${d}" class="c-route${level >= 1 ? " on" : ""}" marker-end="url(#c-head)"/>`));
  const label = level ? `もし水がここまで来たら：${CAPTIONS[level]}` : "建物の断面の模式";
  return `<svg class="cut-svg" viewBox="0 0 ${W} ${under ? 270 : 252}" role="img" aria-label="${esc(label)}">
    <defs><marker id="c-head" markerWidth="5" markerHeight="5" refX="2.6" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 z" class="p-head"/></marker></defs>
    ${parts.join("")}
  </svg>`;
}

// 時間の段の文（サーバーの五段の表のその列の文のまま。重ねて出さない）。
function phaseFacts(index) {
  const table = S.building?.scenarios?.["3:plate"]?.table || [];
  const seen = new Set();
  return table
    .filter((item) => item.key !== "actions" && (item.stopped || item.key === "others"))
    .map((item) => item.cells?.[index])
    .filter((cell) => cell && cell !== "—" && cell !== "止まる想定" && !seen.has(cell) && seen.add(cell));
}

function factLine(text) {
  const head = text.replace(/（.*$/, "");
  const note = text.slice(head.length);
  return `<li><b>${esc(head)}</b>${note ? `<small>${esc(note)}</small>` : ""}</li>`;
}

// 時間の段。表面は段の名前と太字1行（原則1）。段の説明と、ほかの目安は折りたたみに入れる。
// 地下のない形の建物では、段の文の「地下」を「機械の部屋」に言い換える（機械が1階にある形のため）。
function shapeWords(text) {
  if (S.building?.sample?.archetype !== "ground") return text;
  return text.replace(/地下へ/g, "1階の機械の部屋へ").replace(/地下には/g, "機械の部屋には").replace(/地下に/g, "機械の部屋に");
}

function timeline() {
  const n = Number(S.floor);
  const notes = S.building?.scenarios?.["3:plate"]?.notes || [];
  const stopped = TILES.filter((tile) => serviceState(3, SERVICE_OF_TILE[tile.key]) === "stopped").map((tile) => tile.label);
  const items = PHASES.map((phase, i) => {
    const facts = phaseFacts(i);
    let lead = "";
    if (phase.key === "before") lead = "建物の中は、まだ使える";
    if (phase.key === "day") lead = stopped.length ? `止まる想定：${stopped.join("・")}` : phase.line;
    if (phase.key === "morning") lead = n >= 2 ? `${n}階まで、水もごみも階段で運ぶ` : S.building?.sample?.archetype === "ground" ? "機械の部屋に水が残り、入れない" : "地下に水が残り、機械室に入れない";
    if (phase.key === "week" || phase.key === "months") lead = facts.find((cell) => /ほかの建物の例/.test(cell) && !/本復旧/.test(cell)) || facts[0] || phase.line;
    const head = lead.replace(/（.*$/, "");
    const note = lead.slice(head.length);
    const rest = facts.filter((cell) => cell !== lead);
    return `<li class="phase ${phase.key}">
      <p class="phase-name">${esc(phase.name)}</p>
      <p class="phase-lead">${esc(shapeWords(head))}${note ? `<small>${esc(note)}</small>` : ""}</p>
      <details class="phase-more"><summary>くわしく</summary><p class="phase-line">${esc(shapeWords(phase.line))}</p>${rest.length ? `<ul class="facts">${rest.map(factLine).join("")}</ul>` : ""}</details>
    </li>`;
  }).join("");
  return `<ol class="timeline">${items}</ol>${notes[0] ? `<p class="hint">${esc(notes[0])}</p>` : ""}`;
}

function screenTwo() {
  const b = S.building;
  const count = openCount();
  const playing = S.play > 0;
  const levels = b.water_levels || [];
  const now = levels.find((item) => item.key === S.play);
  return `<section class="s2">
    <p class="kicker">${esc(b.sample.custom ? townLabel(S.place.site.label) : where())}</p>
    <h1 class="title">${esc(titleLine())}</h1>
    <h2 class="part"><span>1</span>どう浸水するか</h2>
    <div class="cut">${cutaway(S.play)}</div>
    <div class="play-row">
      <button type="button" class="play" data-act="play">${playing ? "❚❚ 止める" : "▶ 水が入る順に見る"}</button>
      <span class="caption">${playing ? `<b>${esc(now ? `${now.label} ${now.text}` : CAPTIONS[S.play])}</b>` : (b.sample.custom ? "機械の部屋が止まると、上の階まで止まる" : `${b.sample.archetype === "ground" ? "1階" : "地下"}の機械が止まると、上の階まで止まる`)}</span>
    </div>
    ${playing ? `<p class="hint">${PLAY_NOTE}</p>` : ""}
    ${b.sample.custom ? `<p class="hint">${BORROWED}</p>` : ""}
    ${lifeChips(S.play)}
    <h2 class="part"><span>2</span>暮らしが止まるまで</h2>
    ${timeline()}
    <h2 class="part"><span>3</span>どこを確かめるか</h2>
    <div class="plan">${plan()}</div>
    ${legend()}
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
    ${drawingQuestion()}
    ${hasDrawing() ? cards + readCard() : observeCards()}
    <button type="button" class="primary" data-act="to4">${hasDrawing() ? "管理会社と理事会に渡す" : "管理会社に頼む紙を作る"}</button>
  </section>`;
}

// ---- 図面がない人の道（2026-11-05） ----
// 色が赤・緑に変わるのは、図面で確かめた答えのときだけ（見た目や聞いた話では変えない）。
// 図面がない人は、住民が見て答えられる3つを「聞き取り」として依頼メモに載せ、管理会社が竣工図で確かめる材料にする。
const OBSERVE = [
  { key: "slope", title: "地下へ降りる車路のスロープや、地下への階段はありますか？", options: [["yes", "ある"], ["no", "ない"], ["unknown", "分からない"]], says: { yes: "地下へ降りるスロープか階段がある", no: "地下へ降りるスロープや階段は見当たらない" } },
  { key: "door", title: "「電気室」「受変電室」などの表示がある扉を見たことはありますか？", options: [["basement", "地下で見た"], ["ground", "1階で見た"], ["none", "見たことがない"]], says: { basement: "「電気室」などの表示の扉を地下で見た", ground: "「電気室」などの表示の扉を1階で見た" } },
  { key: "plate", title: "入口や駐車場の入口に、止水板が置いてありますか？", options: [["yes", "ある"], ["no", "ない"], ["unknown", "分からない"]], says: { yes: "入口か駐車場の入口に止水板が置いてある", no: "止水板は見当たらない" } },
];

function hasDrawing() {
  if (S.drawing) return S.drawing === "yes";
  return Boolean(S.sampleId);
}

function drawingQuestion() {
  const chosen = S.drawing || (S.sampleId ? "yes" : "");
  const chips = [["yes", "ある（管理会社に見てもらえる）"], ["no", "ない・分からない"]]
    .map(([key, word]) => `<button type="button" class="option${chosen === key ? " chosen" : ""}" data-drawing="${key}" aria-pressed="${chosen === key}">${word}</button>`)
    .join("");
  return `<div class="qcard ask-drawing"><p class="qtitle">竣工図（建物の図面）は、ありますか？</p><div class="options">${chips}</div></div>`;
}

function observeCards() {
  const cards = OBSERVE.map((q) => {
    const chosen = S.obs[q.key] || "";
    const chips = q.options
      .map(([key, word]) => `<button type="button" class="option${chosen === key ? " chosen" : ""}" data-obs="${q.key}" data-value="${key}" aria-pressed="${chosen === key}">${word}</button>`)
      .join("");
    return `<div class="qcard observe"><p class="qtitle">${esc(q.title)}</p><div class="options">${chips}</div></div>`;
  }).join("");
  return `<p class="hint observe-note">図面がなくても進めます。見て分かることを入れると、管理会社への依頼メモに「住民が見たこと」として載ります。色は、図面で確かめるまで変えません。</p>${cards}`;
}

// 住民が見たことを、サーバーの聞き取り（statements）の文にする。
function obsStatements() {
  return OBSERVE.map((q) => q.says[S.obs[q.key]]).filter(Boolean).map((text) => `住民が見たこと：${text}`);
}

// 依頼メモに載せる、聞き取りの文（サーバーの memos の文のまま）。
function heardItems() {
  // 見出し「住民が見たこと」の下に並べるので、文の頭の同じ言葉は外す。
  return (S.building?.memos || []).flatMap((section) => section.items || []).filter((item) => item.from === "聞き取り").map((item) => item.text.replace("「住民が見たこと：", "「"));
}

async function setObservation(key, value) {
  if (S.obs[key] === value) delete S.obs[key];
  else S.obs[key] = value;
  await loadBuilding();
  render();
}

function readCard() {
  return `<div class="qcard read">
      <p class="qtitle">図面の写真から読む（Claude）</p>
      <div class="options">
        <label class="option file">写真・PDFを選ぶ<input type="file" id="plan-file" accept="image/*,application/pdf"></label>
        ${S.sampleId ? `<button type="button" class="option" data-act="read-sample">見本の図面で試す</button>` : ""}
      </div>
      ${readResult()}
    </div>`;
}

// 地図の下の凡例：数字の意味・矢印の意味・色の深さの帯（サーバーの hazard_legend のまま）。
function mapLegend() {
  const reading = S.place?.location?.reading || {};
  const chips = (reading.hazard_legend || []).map((item) => `<span class="lg"><i style="background:${esc(item.color)}"></i>${esc(item.label)}</span>`).join("");
  return `<div class="map-legend">
    <p>数字＝海面からの高さ（標高）。<span class="up">茶</span>は建物より0.1m以上高い所、<span class="down">青</span>は低い所、灰はほぼ同じ高さ。矢印は高い方から。</p>
    ${chips ? `<p class="lg-row">色の深さ：${chips}</p>` : ""}
  </div>`;
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
    return `<p class="hint">Claude が部屋と階を読み、答えの候補を出します。入れるかは、あなたが決めます。${key}</p><p class="hint">入れるのは、機械のある階の平面図のページだけ（32MBまで）。</p>`;
  }
  const kinds = { pump: "①", elec: "②", panel_room: "②", tr: "③" };
  // 同じ部屋の種類と階の候補は1つにまとめる（Claude が同じ部屋を2度挙げることがあるため。2026-11-05 の実機で確かめた）。
  const seen = new Set();
  const proposals = (S.read.rooms || [])
    .filter((room) => kinds[room.kind])
    .filter((room) => {
      const key = `${room.kind}:${floorChoice(room.floor) || room.floor}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
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
      ${heardItems().length || experienceLine() ? `<p><b>住民の話・見たこと</b></p><ul>${experienceLine() ? `<li>${esc(experienceLine())}</li>` : ""}${heardItems().map((text) => `<li>${esc(text)}</li>`).join("")}</ul>` : ""}
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
    S.own = { floors: "", basement: "unknown" };
    S.drawing = null;
    S.obs = {};
    S.exp = "";
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
  // 地下の有無は、画面1の答えを先に。画面3で部屋が地下と分かれば「ある」。
  const basement = roomsFloor === "basement" ? "yes" : S.own.basement;
  const built = Number(S.own.floors);
  return { rooms_floor: roomsFloor, basement, ...(built >= 1 ? { floors: built } : {}), ...S.extra };
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
    statements: [...S.statements, ...obsStatements()],
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

// 送れる図面の大きさ。サーバーの上限（app/server.py の MAX_BODY_BYTES は、32MB の PDF を base64 にした大きさ）と同じ。
// 何百MB・何GBの全部込みの竣工図は、ブラウザで読み込む前に止める（読み込むとタブが固まるため）。
const MAX_FILE_BYTES = 32 * 1024 * 1024;
const FILE_TYPES = /^(image\/(png|jpeg|gif|webp)|application\/pdf)$/;

// 選んだファイルを読む前に確かめる。だめなら、その理由と、どうすればよいかの文を返す。
function fileProblem(file) {
  if (!FILE_TYPES.test(file.type)) return "読めるのは、写真（PNG・JPEG など）と PDF です。";
  if (file.size > MAX_FILE_BYTES) {
    const gb = file.size >= 1024 ** 3;
    const amount = gb ? `${(file.size / 1024 ** 3).toFixed(1)}GB` : `${(file.size / 1024 ** 2).toFixed(1)}MB`;
    return `このファイルは ${amount} あります。送れるのは 32MB までです。全部込みの竣工図は送らず、機械のある階の平面図のページだけを切り出すか、そのページを写真に撮って入れてください。`;
  }
  return "";
}

async function readPlan(file) {
  const problem = file ? fileProblem(file) : "";
  if (problem) {
    S.read = { message: problem, rooms: [] };
    render();
    return;
  }
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
  } else if (target.dataset.drawing) {
    S.drawing = target.dataset.drawing;
    render();
  } else if (target.dataset.obs) {
    setObservation(target.dataset.obs, target.dataset.value);
  } else if (target.dataset.exp) {
    S.exp = S.exp === target.dataset.exp ? "" : target.dataset.exp;
    document.querySelectorAll("[data-exp]").forEach((b) => {
      b.classList.toggle("chosen", b.dataset.exp === S.exp);
      b.setAttribute("aria-pressed", String(b.dataset.exp === S.exp));
    });
  } else if (target.dataset.own) {
    S.own.basement = target.dataset.own;
    document.querySelectorAll("[data-own]").forEach((b) => {
      b.classList.toggle("chosen", b === target);
      b.setAttribute("aria-pressed", String(b === target));
    });
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
  if (event.target.id === "own-floors") S.own.floors = event.target.value;
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
