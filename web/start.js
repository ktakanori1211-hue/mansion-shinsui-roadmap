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
  // 建物名から Web で探した階数の候補（人が「この値を使う」を押すまで使わない）。
  query: "",
  facts: null,
  factsBusy: false,
  sendMsg: "",
  sendText: "",
  // 画面2の対策の切り替え（what-019）：plate（止水板だけ）／hole（壁の穴を塞ぐ）／raise（盤を高くする）。
  measure: "plate",
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
// サーバーの scenario の wet（浸かる設備）と、平面図の部屋。hv＝受電の箱の部屋、panel＝ポンプの制御盤の部屋。
const WET_ROOMS = { ev: ["ev"], hv: ["elec", "panel_room"], panel: ["pump"], tr: ["tr"], gen: ["gen"], tank: ["tank"] };
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
// 再生の注意書き（平面図の水の位置①②③の再生）。時刻や速さは出さない。
const PLAY_NOTE = "実際の浸水速度の予測ではなく、水が順番に入る仕組みの模式です。";
const CAPTIONS = {
  1: "大雨で、道路に水がたまる",
  2: "水が、入り道から建物に入る",
  3: "機械の部屋が水につかり、止まる想定",
};
// 画面3の問い。kind は今の判定が読む部屋の語。「地下」「1階」は、図面でその部屋を確かめた印になる。
const QUESTIONS = [
  { no: "①", row: "water", kind: () => "pump", title: "ポンプ室（水を送るポンプの部屋）は、図面で何階ですか？", options: ["basement", "ground", "upper", "absent"] },
  { no: "②", row: "power", kind: (b) => (b.sample.has_chief_engineer ? "elec" : "panel_room"), title: "電気室（共用の分電盤室のこともあります）は、図面で何階ですか？", options: ["basement", "ground", "upper"] },
  { no: "③", row: "tr", kind: () => "tr", title: "借室（東京電力の変圧器の部屋）は、図面で何階ですか？", options: ["basement", "ground", "upper", "absent"] },
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
  main_panel: "共用の主な盤を高く付け替える",
  gen_move: "非常用発電機を上の階へ",
};
const TIERS = ["今すぐ", "工事が要る", "更新と一緒"];
// 補助の印。前の試算の画面と同じ言い方（言い切らない）。東京都と千葉市のほかは、制度を調べていないので出さない。
const AID_WORDS = { yes: "補助の対象になりうる", with_plate: "止水板などと併せるときに限る", no: "対象外になりうる", unknown: "補助は未確認" };
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

function scenario(level) {
  return S.building?.scenarios?.[`${level}:${S.measure}`] || null;
}

function serviceState(level, key) {
  const services = scenario(level)?.services || [];
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

// 部屋が浸かると止まる暮らし（サーバーの停電の連鎖と同じつながり。分電盤室から各戸へ電気が行く建物では各戸も）。
function roomStops(key) {
  const homesFromPanel = (S.building?.chain?.edges || []).some(([a, b]) => a === "hv" && b === "homes");
  return { ev: "エレベーター", pump: "水・トイレ", elec: "水・エレベーター", panel_room: homesFromPanel ? "水・エレベーター・各戸の電気" : "水・エレベーター", tr: "各戸の電気" }[key] || "";
}

// 平面図のすぐ下：水につかる想定の部屋と、そこで止まる暮らしを、1行ずつ言葉で出す（部屋が小さくて図に書き切れないときも読めるように）。
function wetList(level) {
  if (level < 2) return "";
  const rooms = new Set((S.building?.sample?.views || []).flatMap((view) => view.rooms.map((room) => room.key)));
  const wet = [...new Set((scenario(level)?.wet || []).flatMap((key) => WET_ROOMS[key] || []))].filter((key) => rooms.has(key) && roomStops(key));
  if (!wet.length) return "";
  return `<ul class="wet-list">${wet.map((key) => `<li><b>${esc(ROOM_SHORT[key] || key)}に水</b><span>→ 止まる：${esc(roomStops(key))}</span></li>`).join("")}</ul>`;
}

// 水の位置①②③の見出し。サーバーの water_levels の文は、その下に小さく添える。
const LEVEL_HEAD = { 1: "① 道路が冠水", 2: "② 一番低い床に水", 3: "③ 機械の部屋に水" };

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
  parts.push(sample.custom ? `<text x="${PAD}" y="30" class="p-floor small">${floorName}（よくある形の例）</text>` : `<text x="${PAD}" y="30" class="p-floor">${floorName}の平面図</text>`);

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
    // 水の位置（what-018）。①は道路と入り道まで。②は一番低い床（車路・廊下・EVの底）に浅く。③は盤や受電の箱の高さまで。
    // 機械の部屋が浸かるかは、サーバーの scenario（選んだ対策）の wet のまま。対策で浸からない部屋は塗らない。
    const wetNow = new Set((level >= 2 ? scenario(level)?.wet || [] : []).flatMap((key) => WET_ROOMS[key] || []));
    const lowFloor = /^(aisle|corridor)/.test(room.key) || room.key === "park";
    let depth = 0;
    if (level >= 2 && (lowFloor || wetNow.has(room.key))) depth = level >= 3 ? 0.55 : 0.25;
    if (depth) parts.push(`<rect x="${x + 3}" y="${y + h * (1 - depth)}" width="${w - 6}" height="${h * depth - 3}" class="p-water"/>`);
    // 浸かる想定の機械の部屋には、何が止まるかを部屋の中に直接書く（2026-11-06 本人の指摘「浸水の状況が理解しにくい」）。
    const stops = wetNow.has(room.key) ? roomStops(room.key) : "";
    const stopSize = stops ? fitText(`止まる：${stops}`, w, 15, 12) : 0;
    if (stopSize) parts.push(`<text x="${x + w / 2}" y="${y + h - 8}" class="p-stops" style="font-size:${stopSize}px">止まる：${esc(stops)}</text>`);
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
    // 「壁の穴を塞ぐ」を選んだときは、管から壁の穴への入り道を塞いだ印にする（ほかの入り道は残る）。
    const blocked = entry.hole && S.measure === "hole";
    parts.push(`<path d="M${entry.x1} ${entry.y1} L${entry.x2} ${entry.y2}" class="p-arrow${blocked ? " blocked" : level >= 1 ? " on" : ""}"${blocked ? "" : ' marker-end="url(#p-head)"'}/>`);
    if (entry.hole) parts.push(blocked ? `<g class="p-sealed"><circle cx="${entry.x1}" cy="${Y(1)}" r="11"/><path d="M${entry.x1 - 6} ${Y(1) - 6} L${entry.x1 + 6} ${Y(1) + 6} M${entry.x1 + 6} ${Y(1) - 6} L${entry.x1 - 6} ${Y(1) + 6}"/></g>` : `<circle cx="${entry.x1}" cy="${Y(1)}" r="7" class="p-hole"/>`);
    parts.push(`<text x="${entry.lx}" y="${entry.ly}" class="p-entry${blocked ? " sealed" : ""}" text-anchor="${entry.anchor}">${esc(blocked ? "壁の穴を塞いだ" : entry.label)}</text>`);
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

// 暮らしの札（2026-11-05 本人の指摘「これだとわかりにくい」）。
// 水の位置を出しているときは、札の上に「水が③まで来たら」と書き、どの状態の札かを言う。
// 「？」は言葉で「分からない」と言い、なぜ分からないかを添える。止まる想定に入らない札は「使える」と言わない（what-029）。
const LEVEL_MARK = { 1: "①", 2: "②", 3: "③" };

function lifeChips(level = 0) {
  const n = Number(S.floor);
  const tiles = TILES.map((tile) => {
    let state = worst(tile.from);
    let mark = LOOK[state].mark;
    let small = state === "clear" ? "問題なし" : `止まると、${tile.small(n)}`;
    if (level) {
      const raw = serviceState(level, SERVICE_OF_TILE[tile.key]);
      state = { stopped: "stopped", unknown: "unconfirmed" }[raw] || "running";
      mark = { stopped: "止まる想定", unknown: "分からない" }[raw] || "止まる想定に入らない";
      small = { stopped: tile.small(n), unknown: "東京電力の設備しだいで、建物側からは分からない" }[raw] || "遮断や点検で止まることはあります";
    }
    return `<li class="${state}"><b>${esc(tile.label)}</b><em>${esc(mark)}</em><small>${esc(small)}</small></li>`;
  }).join("");
  const head = level ? `<p class="life-head">${LEVEL_HEAD[level] || `水が${LEVEL_MARK[level] || ""}まで来たら`}（想定）</p>` : "";
  return `${head}<ul class="life">${tiles}</ul>`;
}

// ---- 地図の深さの帯（立地の行の value のまま） ----
// 一番深い帯は、画面1の地図に重ねる層と、土地の一行に使うだけ。建物の階には置き換えない（深さを主役にしない。CLAUDE.md の6）。
const HAZARD_WORDS = { flood: "川があふれると", inland: "下水や水路があふれると", surge: "高潮のとき" };

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



// 深さの札の行と、地図に重ねる層の対応（洪水は想定最大を先に）。地図と札で同じ層を使う。
const LAYERS_OF_ROW = { flood: ["flood_max", "flood_planned"], inland: ["inland"], surge: ["storm_surge"] };

function hazardLayer(band) {
  if (!band) return null;
  const hazards = S.place?.location?.reading?.hazards || [];
  const usable = (item) => item.status === "color" || item.nearby_legend;
  return (LAYERS_OF_ROW[band.key] || []).map((key) => hazards.find((item) => item.key === key && usable(item))).find(Boolean) || null;
}











// ---- 内水と、この辺りの経験（2026-11-05） ----
// 内水（下水や水路があふれる）は、国の重ねるハザードマップにデータがない所が多い。市区町村が別に出していることがあるので案内する。
const WAGAMACHI = "https://disaportal.gsi.go.jp/hazardmap/";

function inlandNote() {
  const inland = (S.place?.location?.reading?.hazards || []).find((item) => item.key === "inland");
  if (inland && (inland.legend || inland.nearby_legend)) return "";
  return `<p class="inland-note">下水や水路があふれる浸水（内水）は、この地図にデータがありません。道路の冠水はこちらのことがあります。市区町村の地図は<a href="${WAGAMACHI}" target="_blank" rel="noopener">わがまちハザードマップ（国土地理院）</a>で。</p>`;
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
    <p class="hint">依頼メモに載せます（判定の色は変えません）。</p>
  </div>`;
}

// 依頼メモの一行。建物の図面ではなく、市区町村（下水道の担当）に内水の記録と想定を確かめてもらう。
function experienceLine() {
  const says = EXPERIENCE_SAYS[S.exp];
  // 見出し「住民の話・見たこと」の下に並べるので、文の頭に「住民の話」は付けない。
  if (!says || S.exp === "none") return says ? `${says}。` : "";
  return `${says}。地図にない内水の手がかりなので、管理会社から市区町村（下水道の担当）に、この辺りの浸水の記録と内水の想定を確かめてください。`;
}

// ---- 土地を横から見た図（2026-11-05） ----
// サーバーが読んだ「建物の点と、北南（東西）50m・100m の高さ」を横から見た線にし、建物・海面・想定の水面を重ねる。
// 高さの差が大きい向き（北南か東西）を選ぶ。水面は「建物の点の高さ＋想定の深さ」で、深さの帯の両端を引く。説明用の目安。
function profileAxis() {
  const profile = S.place?.location?.reading?.profile || {};
  const range = (list) => {
    const values = (list || []).map(([, h]) => h).filter((h) => typeof h === "number");
    return values.length >= 3 ? Math.max(...values) - Math.min(...values) : -1;
  };
  const ns = range(profile.ns);
  const ew = range(profile.ew);
  if (ns < 0 && ew < 0) return null;
  // 北南は北を左に、東西は西を左に置く。
  if (ns >= ew) return { left: "北", right: "南", points: [...profile.ns].sort((a, b) => b[0] - a[0]).filter(([, h]) => typeof h === "number") };
  return { left: "西", right: "東", points: [...profile.ew].sort((a, b) => a[0] - b[0]).filter(([, h]) => typeof h === "number") };
}

// 図の下の一行。データから言えることだけ（海面より低いか・まわりより低いか高いか）。
function profileWords(axis) {
  const center = axis.points.find(([d]) => d === 0)?.[1];
  if (typeof center !== "number") return "";
  const others = axis.points.filter(([d]) => d !== 0).map(([, h]) => h);
  const mean = others.reduce((sum, h) => sum + h, 0) / (others.length || 1);
  const parts = [];
  if (center < 0) parts.push(`海面より低い土地（${center.toFixed(1)}m）`);
  const reading = S.place?.location?.reading || {};
  // 片側が高く、反対側が低いときは「坂の途中」と言う。標高の細かな差を坂と言わないよう、1m 以上の差のときだけ（仮の目安）。
  const ci = axis.points.findIndex(([d]) => d === 0);
  const lefts = axis.points.slice(0, ci).map(([, h]) => h);
  const rights = axis.points.slice(ci + 1).map(([, h]) => h);
  const slopeDown = lefts.length && rights.length && Math.max(...lefts) >= center + 1 && Math.min(...rights) <= center - 1;
  const slopeUp = lefts.length && rights.length && Math.min(...lefts) <= center - 1 && Math.max(...rights) >= center + 1;
  if (reading.basin) parts.push("まわりより低い凹み");
  else if (slopeDown) parts.push(`${axis.left}が高く${axis.right}が低い坂の途中`);
  else if (slopeUp) parts.push(`${axis.right}が高く${axis.left}が低い坂の途中`);
  else if (center < mean - 0.1) parts.push("まわりより低い所");
  else if (center > mean + 0.1) parts.push("まわりより少し高い所");
  else parts.push("まわりとほぼ同じ高さ");
  let line = `この建物は、${parts.join("で、")}にあります。`;
  if (deepestHazard() && (center < 0 || reading.basin || center < mean - 0.1)) line += "川があふれると、低い所に水が集まります。";
  return line;
}


// ---- WHY に沿った画面1・2の部品（2026-11-05 作り直し） ----
// 画面1の一行：命を守る避難の判断と、機械を守る足元の対策を混ぜない。
const EVAC_LINE = "避難するかどうかは、自治体のハザードマップと警戒レベルで決めます。この道具は、地図に色がなくても浅い水で止まる、建物の電気と水の足元の対策を整理します。";

// 画面1の土地の一行（横から見た図はやめ、言葉だけ）。
function landLine() {
  const axis = profileAxis();
  return axis ? profileWords(axis) : "";
}

// 対策の切り替え（what-019）。名前はサーバーの model_measures のまま。選んだ対策の固定の文（what-026）を言い換えずに添える。
function measureChips() {
  const b = S.building;
  const list = b.model_measures || [];
  if (!list.length) return "";
  const chips = list.map((m) => `<button type="button" class="option${S.measure === m.key ? " chosen" : ""}" data-measure="${esc(m.key)}" aria-pressed="${S.measure === m.key}">${esc(m.short)}</button>`).join("");
  const chosen = list.find((m) => m.key === S.measure);
  const fixed = [];
  if (S.measure === "hole") fixed.push(b.fixed.hole);
  if (S.measure === "raise") fixed.push(b.fixed.raise);
  fixed.push(b.fixed.tr_box ? `借室：${b.fixed.tr_box}` : "");
  return `<div class="measures-switch">
    <p class="own-head">対策を選ぶと、止まり方が変わります</p>
    <div class="options">${chips}</div>
    ${chosen ? `<p class="hint">${esc(chosen.label)}</p>` : ""}
    ${decideLine()}
    ${fixed.filter(Boolean).map((text) => `<p class="fixed-line">${esc(text)}</p>`).join("")}
  </div>`;
}

// 選んだ対策の「だれが決めるか」と「費用の桁」（what-017：切り替えると要る決議と桁が変わる。W1・W5：理事長が知りたいこと）。
// 文はサーバーの measures の decision・range・account のまま。桁には固定の文を必ず添える（what-038）。
const MODEL_MEASURE = { plate: "plate", hole: "hole", raise: "panel" };

function decideLine() {
  const m = measures().find((item) => item.key === MODEL_MEASURE[S.measure]);
  if (!m) return "";
  const cost = m.range ? `${m.range}${m.account ? `（${m.account}）` : ""}` : "";
  return `<p class="decide-line"><span><b>だれが決める</b>${esc(m.decision || "")}</span>${cost ? `<span><b>費用の桁</b>${esc(cost)}</span>` : ""}</p>
    ${cost ? `<p class="hint">${COST_FIXED}</p>` : ""}`;
}

// ---- 1 場所 ----

// 地図の下の表面（2026-11-05 本人の指摘：1回目「要素が多すぎる」、2回目「折りたたまないと状況が分からないのは不親切」）。
// 5つの項目を、1行ずつ必ず表面に出す（9章 how-035 の一段目）。印と色はサーバーの判定のまま（画面で risk を作らない）。
// 文は、電気も防災も知らない人の言葉にする。未確認には、だれが確かめるかを添える。数値と出典は二段目（折りたたみ）に置く。
// 凹みを一番に（原則3）。深さの数字は表面に出さない（原則6）。
const PLACE_PLAIN = {
  flood: "川があふれると、水につかる想定の場所です",
  inland: "下水や水路があふれると、水につかる想定の場所です",
  surge: "高潮のとき、水につかる想定の場所です",
};

// ハザードの行（洪水・内水・高潮）の言葉。値の形（深さの帯・色なし・データなし）と、読んだ点（建物の位置か代表点か）で言い分ける。
function hazardPlain(item) {
  const atBuilding = S.place?.site?.basis === "building";
  if (/数m先/.test(item.conclusion || "")) return "すぐ近く（数m先）に、水につかる想定の色があります";
  if (parseBand(item.value)) return item.verdict === "risk" || atBuilding ? PLACE_PLAIN[item.key] : `${PLACE_PLAIN[item.key].replace("場所です", "場所")}（町丁の代表点の色。建物の位置ではまだ確かめていません）`;
  if (item.value === "色なし") return "地図に色はありません。色がないことは、安全という意味ではありません";
  return "国の地図にデータがなく、色があるかどうかも分かりません";
}

function recordPlain(item) {
  if (item.verdict === "risk") return item.conclusion;
  if (item.value === "未収録") return "この町丁の記録は、まだ手元の表に入っていません";
  return "記録がないことは、浸水がなかったことを示しません";
}

// 土地の高さの言葉。凹みでも、サーバーの判定が未確認（代表点・仮の目安）なら、そう添える（判定表1-3・1-4）。
function groundPlain(item) {
  const text = terrainLine().text;
  if (item.verdict === "risk") return text;
  return S.place?.location?.reading?.basin ? `${text}（地図の標高による仮の目安。建物の位置で確かめます）` : text;
}

function placeLines() {
  const rows = S.place?.location?.rows || [];
  const basin = S.place?.location?.reading?.basin;
  const rank = (item) => (item.key === "ground" && basin ? 0 : { risk: 1, unconfirmed: 2, clear: 3 }[item.verdict] ?? 2);
  return [...rows].sort((a, b) => rank(a) - rank(b)).map((item) => ({
    verdict: item.verdict,
    name: PLACE_SHORT[item.key] || item.label,
    text: item.key === "ground" ? groundPlain(item) : item.key === "record" ? recordPlain(item) : PLACE_PLAIN[item.key] ? hazardPlain(item) : item.conclusion || item.value || "",
    who: item.verdict === "unconfirmed" ? item.confirm_short || "" : "",
  }));
}

// 土地の高さの文（判定は付けない。色は ground の行の verdict から取る）。
function terrainLine() {
  const reading = S.place?.location?.reading || {};
  if (reading.basin) return { text: "周りより低い凹み。周りの水が集まります" };
  const high = reading.high_directions || [];
  if (high.length) return { text: `${high.join("・")}が高く、水が流れてきます` };
  const points = reading.elevation?.points || [];
  if (points.length >= 5) return { text: "周りより少し高い土地（凹みではない）" };
  return { text: "土地の高さは読めませんでした" };
}

// ---- 建物名から Web で階数を探す（Claude、2026-11-05） ----
// 押したときだけ、建物名と所在地を Anthropic の API に送り、Web を検索する。答えは出典つきの候補で、人が「この値を使う」を押すまで使わない。
function factsBox() {
  const name = S.query && !/[都道府県市区町村]\S*[0-9０-９一二三四五六七八九十]/.test(S.query) ? S.query : "";
  let result = "";
  if (S.factsBusy) result = `<p class="hint">Web で探しています…</p>`;
  else if (S.facts?.found) {
    const f = S.facts.found;
    const floors = [f.floors_above ? `地上${f.floors_above}階` : "", f.floors_below === null ? "地下は書かれていない" : f.floors_below ? `地下${f.floors_below}階` : "地下なし"].filter(Boolean).join("・");
    result = `<div class="facts-found"><p><b>${esc(floors)}</b>${f.building ? `（${esc(f.building)}）` : ""}</p>
      <p class="hint">出典：<a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(f.source_title || f.source_url)}</a>${f.quote ? `「${esc(f.quote)}」` : ""}</p>
      <p class="hint">${esc(S.facts.message)}</p>
      <button type="button" class="option" data-act="use-facts">この値を使う</button></div>`;
  } else if (S.facts) result = `<p class="hint">${esc(S.facts.message)}</p>`;
  return `<details class="facts"${S.facts || S.factsBusy ? " open" : ""}><summary>建物名から階数を探す</summary>
    <label class="facts-name">建物名<input id="facts-name" type="text" autocomplete="off" value="${esc(name)}" placeholder="〇〇マンション"></label>
    <button type="button" class="option" data-act="facts"${S.factsBusy ? " disabled" : ""}>Web で階数を探す</button>
    <p class="hint">押すと、建物名と所在地を Anthropic の API に送り、Web を検索します。</p>
    ${result}
  </details>`;
}

async function findFacts() {
  const name = (document.getElementById("facts-name")?.value || "").trim();
  if (!name) {
    S.facts = { found: null, message: "建物名を入れてください。" };
    render();
    return;
  }
  S.factsBusy = true;
  S.facts = null;
  render();
  try {
    S.facts = await postJSON("/api/building-facts", { name, address: townLabel(S.place?.site?.label || "") });
  } catch (error) {
    S.facts = { found: null, message: error.message };
  } finally {
    S.factsBusy = false;
    S.query = name;
    render();
  }
}

// 候補を使う：地上の階数を「何階建て」に、地下の階数を「地下は ある／ない」に入れる（地下が書かれていなければ変えない）。
function useFacts() {
  const f = S.facts?.found;
  if (!f) return;
  if (f.floors_above) S.own.floors = String(f.floors_above);
  if (f.floors_below !== null && f.floors_below !== undefined) S.own.basement = f.floors_below > 0 ? "yes" : "no";
  render();
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
    ${factsBox()}
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
    const lines = placeLines();
    const rows = (S.place.location.rows || [])
      .map((item) => `<li class="${item.verdict}"><b>${esc(PLACE_SHORT[item.key] || item.label)}</b><span>${esc(item.value || "")}</span></li>`)
      .join("");
    const representative = S.place.site.basis === "representative";
    picked = `<div class="picked">
        <p class="place"><b>${esc(S.place.site.label)}</b></p>
        <h2 class="question">この土地で水が来る道</h2>
        <div class="map-box"><div id="site-map" class="site-map" aria-label="地図：ハザードマップと土地の高さ"></div></div>
        ${mapLegend()}
        ${S.sampleId ? "" : `<p class="pin-hint ${S.place.site.basis === "building" ? "done" : ""}">${S.place.site.basis === "building" ? "建物の位置の値で読んでいます（地図を押すと選び直せます）" : "地図で、建物の場所を押してください（今は町丁の代表点の値）"}</p>`}
        <ul class="place-lines">${lines.map((line) => `<li class="${line.verdict}"><i>${LOOK[line.verdict]?.word || "未確認"}</i><p><b>${esc(line.name)}</b>${esc(line.text)}${line.who ? `<small>確かめる：${esc(line.who)}</small>` : ""}</p></li>`).join("")}</ul>
        <details class="place-more more"><summary>数値と出典を見る</summary>
          <ul class="place-chips">${rows}</ul>
          ${landLine() ? `<p class="land-line">${esc(landLine())}</p>` : ""}
          ${recordNote()}
          ${representative ? `<p class="hint">高さと色は町丁の代表点の値です。</p>` : ""}
          ${inlandNote()}
        </details>
        ${placeAid()}
        <p class="evac">${EVAC_LINE}</p>
        ${S.sampleId ? "" : ownQuestions()}
        ${S.sampleId ? "" : experienceQuestion()}
        <label class="floor">住んでいる階<input id="floor" type="number" inputmode="numeric" min="1" max="80" value="${esc(S.floor)}" placeholder="8">階<small>（なくても進めます）</small></label>
        <button type="button" class="primary" data-act="see"${S.busy ? " disabled" : ""}>この建物で見る</button>
      </div>`;
  }
  return `<section class="s1">
    ${S.openId ? openBox() : ""}
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
    ${S.openId ? "" : openBox()}
    ${picked}
  </section>`;
}

// 地図。地理院タイルとハザードマップの色を重ね、東西南北50mの標高を置く。高い方から建物へ水の矢印を引く。
const TILE_PAGE = "https://maps.gsi.go.jp/development/ichiran.html";
const HAZARD_URL = "https://disaportaldata.gsi.go.jp/raster/{layer}/{z}/{x}/{y}.png";

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
  const shown = shownLayer();
  if (shown) {
    L.tileLayer(HAZARD_URL.replace("{layer}", shown.layer), {
      maxNativeZoom: 17,
      maxZoom: 18,
      opacity: 0.6,
      attribution: '<a href="https://disaportal.gsi.go.jp/hazardmap/copyright/opendata.html" target="_blank" rel="noopener">ハザードマップポータルサイト</a>',
    }).addTo(map);
  }
  // 地図は「場所の確認」と「建物の位置を押す」だけに使う。高さの数字と矢印は、地図の下の「土地を横から見た図」で見せる（2026-11-05）。
  const meters = reading.elevation?.distance_m || 50;
  const dLat = meters / 111320;
  const dLng = meters / (111320 * Math.cos((lat * Math.PI) / 180));
  L.marker([lat, lng], { interactive: false, icon: L.divIcon({ className: "m-site", html: "<b>建物</b>", iconSize: [48, 26], iconAnchor: [24, 13] }) }).addTo(map);
  map.fitBounds([[lat - dLat * 1.6, lng - dLng * 1.6], [lat + dLat * 1.6, lng + dLng * 1.6]]);
  if (shown) {
    const legend = L.control({ position: "topleft" });
    legend.onAdd = () => {
      const div = L.DomUtil.create("div", "m-legend");
      div.textContent = `色＝${LAYER_PLAIN[shown.key]?.short || shown.label}`;
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
// 2段で見せる。①構内平面図の上で、水の位置①②③の順に水が入り、選んだ対策で浸かる部屋が変わる ②暮らしが止まるまでの時間。
// 部屋の色は判定のまま、浸かる部屋と止まるかはサーバーの scenario（水の位置:対策）のまま。

// 住民が過ごす時間の順（前の時間の再生と同じ段の名前。サーバーの五段の表の列の順）。
const PHASES = [
  { key: "before", name: "大雨が近づいたとき", line: "外の道路に水がたまり始める。建物の中はまだ使える" },
  { key: "day", name: "水が来た当日", line: "スロープや壁の穴から地下へ水が入り、エレベーター、続いて水と電気が止まる" },
  { key: "morning", name: "水が引いた翌朝", line: "外の道路は乾いても、地下には水が残る。水を抜くまで機械室に入れない" },
  { key: "week", name: "数日〜1週間", line: "水を抜いても、浸かった機械は止まったまま。点検と修理を待つ" },
  { key: "months", name: "約2か月〜本復旧", line: "浸かった盤や部品が届いて付け替わるまで、止まったままのことがある" },
];


// 時間の段の文（サーバーの五段の表のその列の文のまま。重ねて出さない）。
function phaseFacts(index) {
  const table = scenario(3)?.table || [];
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
  const notes = scenario(3)?.notes || [];
  const stopped = TILES.filter((tile) => serviceState(3, SERVICE_OF_TILE[tile.key]) === "stopped").map((tile) => tile.label);
  const items = PHASES.map((phase, i) => {
    const facts = phaseFacts(i);
    let lead = "";
    if (phase.key === "before") lead = "建物の中は、まだ使える";
    if (phase.key === "day") lead = stopped.length ? `止まる想定：${stopped.join("・")}` : phase.line;
    if (phase.key === "morning") lead = n >= 2 ? `${n}階まで、水もごみも階段で運ぶ` : S.building?.sample?.archetype === "ground" ? "機械の部屋に水が残り、入れない" : "地下に水が残り、機械室に入れない";
    if (phase.key === "week") lead = facts.find((cell) => /ほかの建物の例/.test(cell) && !/本復旧/.test(cell)) || facts.find(hasGuide) || phase.line;
    // 約2か月〜本復旧は、この建物の同じ設備の行の目安が出るか消えるか（「目安なし＊」）を表面で見せる（what-019、what-020）。
    if (phase.key === "months") lead = ownGuide(i) || facts.find(hasGuide) || phase.line;
    const head = lead.replace(/（.*$/, "");
    const note = lead.slice(head.length);
    const rest = facts.filter((cell) => cell !== lead);
    return `<li class="phase ${phase.key}">
      <p class="phase-name">${esc(phase.name)}</p>
      <p class="phase-lead">${esc(shapeWords(head))}${note ? `<small>${esc(note)}</small>` : ""}</p>
      <details class="phase-more"><summary>くわしく</summary><p class="phase-line">${esc(shapeWords(phase.line))}</p>${rest.length ? `<ul class="facts">${rest.map(factLine).join("")}</ul>` : ""}</details>
    </li>`;
  }).join("");
  // 目安が消えたマス（＊）の理由の文は、折りたたまずに出す（what-028、how-035）。
  const below = scenario(3)?.below || [];
  return `<ol class="timeline">${items}</ol>${notes[0] ? `<p class="hint">${esc(notes[0])}</p>` : ""}${below.map((text) => `<p class="fixed-line">${esc(text)}</p>`).join("")}`;
}

// 目安の文があるマスか（「—」「止まる想定」「目安なし＊」は目安ではない）。
function hasGuide(cell) {
  return Boolean(cell) && cell !== "—" && cell !== "止まる想定" && !cell.startsWith("目安なし");
}

// 太字に読む行は、対策を変えても同じ行にする（what-020：変わるのは目安が出るか出ないかだけ。別の行の目安に入れ替えると「早く戻る」と読めるため）。
// 行は、止水板だけのときに目安が出ている、この建物の設備の行（受電の箱、給水の盤の順）。ほかの建物の例は使わない。
function ownGuide(index) {
  const base = S.building?.scenarios?.["3:plate"]?.table || [];
  const anchor = ["hv", "water"].find((key) => hasGuide(base.find((item) => item.key === key)?.cells?.[index]));
  if (!anchor) return "";
  const cell = (scenario(3)?.table || []).find((item) => item.key === anchor)?.cells?.[index];
  return cell && cell !== "—" ? cell : "";
}

function screenTwo() {
  const b = S.building;
  const count = openCount();
  // S.play は平面図に出している水の位置（0 は判定のまま）。再生中かは S.timer で見る。再生が終わっても③のまま止める（2026-11-05）。
  const playing = Boolean(S.timer);
  const shown = S.play > 0;
  const levels = b.water_levels || [];
  const now = levels.find((item) => item.key === S.play);
  return `<section class="s2">
    <p class="kicker">${esc(b.sample.custom ? townLabel(S.place.site.label) : where())}</p>
    <h1 class="title">${esc(b.top_line.lead)}</h1>
    <p class="lead-why">${esc(titleLine())}</p>
    ${b.sample.custom ? ownDrawingFirst() : ""}
    <h2 class="part"><span>1</span>水が入る順と、止まるもの</h2>
    <div class="plan">${plan({ level: S.play })}</div>
    ${wetList(S.play)}
    <div class="play-row">
      <button type="button" class="play" data-act="play">${playing ? "❚❚ 止める" : shown ? "▶ もう一度見る" : "▶ 水が入る順に見る"}</button>
      <span class="caption">${shown ? `<b class="level-head">${LEVEL_HEAD[S.play] || ""}</b><small>${esc(now ? now.text : CAPTIONS[S.play])}</small>` : "道路 → 入り道 → 一番低い床 → 盤"}</span>
    </div>
    ${shown ? `<p class="hint">${PLAY_NOTE}</p>` : ""}
    ${measureChips()}
    ${b.sample.custom ? `<p class="hint">${BORROWED}</p>` : ""}
    ${lifeChips(S.play)}
    ${legend()}
    <h2 class="part"><span>2</span>暮らしが止まるまで</h2>
    ${timeline()}
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
    const chosen = S.choices[kind] || "none";
    // 主任技術者の名前の問いは、見出しの問いと混ぜず、別の札にする（2026-11-05 本人の指摘⑤）。
    const options = `<div class="options">${[...q.options, "none"]
          .map((o) => `<button type="button" class="option${chosen === o ? " chosen" : ""}" data-kind="${kind}" data-choice="${o}" aria-pressed="${chosen === o}">${OPTION_WORDS[o]}</button>`)
          .join("")}</div>`;
    const engineer = q.row === "power" && S.extra.hv === "yes" ? `<p class="hint">電気主任技術者：点検報告書に名前あり　<button type="button" class="option small" data-hv="none">取り消す</button></p>` : "";
    // 判定の結果は折りたたまずに出す（状況が分かる情報は表面に）。
    const before = q.row === "power" && b.sample.engineer_unsure ? `<div class="qcard engineer">${engineerQuestion()}</div>` : "";
    return `${before}<div class="qcard ${v}">
      <p class="qtitle"><span class="no">${q.no}</span>${esc(q.title)}</p>
      ${engineer}${options}
      <p class="qresult ${v}"><b>${LOOK[v].mark} ${LOOK[v].word}</b>${item ? `<small>${esc(item.summary)}</small>` : ""}</p>
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
  const seen = OBSERVE.map((q) => q.says[S.obs[q.key]]).filter(Boolean);
  if (S.hvSaid === "no") seen.push("電気設備の点検の報告書に、電気主任技術者の名前が見当たらなかった");
  return seen.map((text) => `住民が見たこと：${text}`);
}

// ②の前に聞く、電気主任技術者の名前（2026-11-05 本人の指摘「名前があるの意味がよく分からない」）。
// 何の紙の、どこを見るか、だれが持っているか（what-046）と、なぜ聞くか（what-022：主任技術者がいるかで、浸水の日の連絡先と手順が変わる）を添える。
// 「書いていない」では判定を変えない。受電設備なしと読むのは、書類に「受電設備なし」と「選任なし」の両方があるときだけ（hantei-030、how-017）。
function engineerQuestion() {
  const said = S.hvSaid || "";
  const chip = (key, word) => `<button type="button" class="option${said === key ? " chosen" : ""}" data-hv="${key}" aria-pressed="${said === key}">${word}</button>`;
  return `<p class="qtitle">電気の点検の報告書に、電気主任技術者の名前はありますか？</p>
    <p class="qsub">管理会社か理事会が持っている「電気設備の点検の報告書」を見ます。</p>
    <p class="hint">電気の点検を任された人がいるかで、浸水の日にだれへ連絡し、だれが電気を切るかが変わります。</p>
    <div class="options">${chip("yes", "書いてある")}${chip("no", "書いていない")}${chip("none", "分からない")}</div>
    ${said === "no" ? `<p class="hint">名前がないことだけでは、電気を受ける部屋がないとは決めません。依頼メモで管理会社に確かめてもらいます。</p>` : ""}`;
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

// 図面を読むときの、送る前の明示（what-063）。
const READ_NOTICE = "選んだ図面は、Anthropic の API に送って読みます（APIキーがないときは送らず、見本の答えを出します）。";

// 自分の建物：下の平面図は見本の形を借りた「よくある形の例」だと大きく言い、図面を入れる場所（3「確かめる」）へ案内する。
// 図面を入れる欄は3の1か所だけにする（2026-11-06 本人の指摘「画面2と3で重複」「導線がおかしい」）。
function ownDrawingFirst() {
  return `<div class="qcard own-drawing">
      <p class="example-tag">下の図は「よくある形の例」です。あなたの建物の図ではありません。</p>
      <p class="qsub">竣工図（建物の図面）があれば、3「確かめる」で入れると、電気室・ポンプ室・借室の階が答えに入り、図の色が変わります。</p>
      <button type="button" class="option" data-act="to3">図面を入れる（3へ）</button>
    </div>`;
}

function readCard() {
  return `<div class="qcard read">
      <p class="qtitle">図面の写真から読む</p>
      <div class="options">
        <label class="option file">写真・PDFを選ぶ<input type="file" id="plan-file" accept="image/*,application/pdf"></label>
        ${S.sampleId ? `<button type="button" class="option" data-act="read-sample">見本の図面で試す</button>` : ""}
      </div>
      <p class="hint">${READ_NOTICE}</p>
      ${readResult()}
    </div>`;
}

// 地図の下の凡例：数字の意味・矢印の意味・色の深さの帯（サーバーの hazard_legend のまま）。
// 地図に重ねる層（上の深さの札と同じ想定。洪水は想定最大を先に）。なければ色のある層。
function shownLayer() {
  const hazards = S.place?.location?.reading?.hazards || [];
  return hazardLayer(deepestHazard()) || hazards.find((item) => item.status === "color") || hazards.find((item) => item.nearby_legend) || null;
}

// 地図の色が「何の水か」を、知らない人の言葉で言う（2026-11-05 本人の指摘「この色が何の水位か分かりにくい」）。
// 正式な層の名前は（ ）に残す。深さを階に置き換える説明や、出典のない「何年に1度」は足さない（原則6、数字の決まり）。
const LAYER_PLAIN = {
  flood_max: { family: "flood", short: "川があふれたとき", long: "近くの川があふれたときに、水につかる想定の範囲（洪水・想定最大規模＝考えうる最大の大雨の想定）" },
  flood_planned: { family: "flood", short: "川があふれたとき", long: "近くの川があふれたときに、水につかる想定の範囲（洪水・計画規模）" },
  storm_surge: { family: "surge", short: "高潮のとき", long: "高潮のときに、水につかる想定の範囲（高潮）" },
  inland: { family: "inland", short: "下水・水路があふれたとき", long: "下水や水路があふれたときに、水につかる想定の範囲（内水）" },
};
const FAMILY_NAME = { flood: "川の洪水", surge: "高潮", inland: "下水・水路" };

// 深さを判定表1-1の3段（0.5m 未満／0.5〜3m／3m 超）で言う。札はこの帯で動かさない。
function bandWord(label) {
  const band = parseBand(label);
  if (!band) return "";
  return band.high !== null && band.high <= 0.5 ? "0.5m未満" : band.low >= 3 ? "3m超" : "0.5〜3m";
}

// 地図の下：建物（または町丁の代表点）の場所の色を、色見本つきで表面に出す（2026-11-05 本人の指摘「プルダウンいる？位置の色を見せた方がいい」）。
function mapLegend() {
  const reading = S.place?.location?.reading || {};
  const shown = shownLayer();
  if (!shown) return `<p class="map-caption">この地図には、水につかる想定の色を重ねていません（この地点では、川・高潮・下水の想定の色が読めなかったため）。色がないことは、安全という意味ではありません。</p>`;
  const plain = LAYER_PLAIN[shown.key] || { family: "", long: shown.label };
  // 地図に重ねていない層にも色があるときは、そう言う（見出しと地図が食い違って見えないように）。
  // 「下水・水路」の中黒と区別するため、読点でつなぐ。
  const others = [...new Set((reading.hazards || [])
    .filter((item) => (item.status === "color" || item.nearby_legend) && LAYER_PLAIN[item.key]?.family !== plain.family)
    .map((item) => FAMILY_NAME[LAYER_PLAIN[item.key]?.family] || item.label))];
  const label = shown.status === "color" ? shown.legend : shown.nearby_legend;
  const color = (reading.hazard_legend || []).find((item) => item.label === label)?.color || "";
  const where = S.place?.site?.basis === "building" ? "建物の場所" : "町丁の代表点";
  const point = shown.status === "color" ? `${where}の色` : `${where}のすぐ近く（数m先）の色`;
  return `<div class="map-legend">
    <p class="map-point">${color ? `<i style="background:${esc(color)}"></i>` : ""}<b>${point}：${esc(bandWord(label) || label)}の深さの想定</b><small>（地図の凡例では ${esc(label)}）</small></p>
    <p class="map-caption">地図の色は、${esc(plain.long)}です。色が濃いほど深い想定です。${others.length ? `${esc(others.join("、"))}の色は、この地図には重ねていません。` : ""}</p>
  </div>`;
}

// 浸水の記録がリスクありでないときの添え書き（判定表1-1：記録なし＝浸水なし、とは読まない）。
function recordNote() {
  const record = (S.place?.location?.rows || []).find((item) => item.key === "record");
  if (!record || record.verdict === "risk") return "";
  return `<p class="hint">浸水の記録：記録がないことは、浸水がなかったことを示しません。</p>`;
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
  // 名前は画面3の問いの見出しとそろえる。図面に書かれた語は小さく添える。
  const names = { pump: "ポンプ室", elec: "電気室", panel_room: "分電盤室", tr: "借室（東京電力の変圧器の部屋）" };
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
      const word = room.word && room.word !== names[room.kind] ? `<small>（図面では「${esc(room.word)}」）</small>` : "";
      return `<li><b>${names[room.kind]}</b>${word}：${esc(room.floor || "階は読めず")}　${button}</li>`;
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

// 費用の欄（2026-11-05 本人の指摘「工事金額がわかりにくい。これでは理事会が進めようと思えない」）。
// 出典のない円の数字は足さない（費用の桁はサーバーの帯のまま）。そのかわり、工事の中身・見積りを頼む先・決め方を出し、
// 見積り額を入れたときだけ、補助を使えた場合の計算例と1戸あたりを計算する（what-064）。補助の率と上限は、出典を確かめた制度だけ。
// 補助の率と上限は、サーバーの SUBSIDIES の calc（都・市の全体）か covers（区市の、対策ごと）のまま。
function aidCalc(m, aid) {
  if (aid.covers) return aid.covers[m.key] || null;
  const status = m[aid.region];
  return aid.calc && (status === "yes" || status === "with_plate") ? aid.calc : null;
}

// 対策の行の印。都・千葉市は対策ごとの読み（m.tokyo など）、区市は covers にある対策だけ。
function aidStatus(m, aid) {
  if (aid.covers) return aid.covers[m.key] ? "yes" : "";
  return m[aid.region] || "";
}

function yen(value) {
  return `${Math.round(value).toLocaleString("ja-JP")}円`;
}

// 入れた見積り額からの計算。率と上限と切り捨ては、制度の文のまま。計算例で、交付を約束しない。
function estimateLine(m, aid) {
  const amount = Number(S.est?.[m.key]);
  if (!(amount > 0)) return "";
  const units = Number(S.units);
  const calc = aidCalc(m, aid);
  const status = aidStatus(m, aid);
  const parts = [`見積り ${yen(amount)}`];
  let own = amount;
  if (calc) {
    const grant = Math.floor(Math.min(amount * calc.rate, calc.cap) / calc.unit) * calc.unit;
    own = amount - grant;
    parts.push(`${aid.label}を使えた場合：補助 ${yen(grant)}、組合の負担 ${yen(own)}${status === "with_plate" ? "（止水板などと併せる場合に限る）" : ""}`);
  }
  if (units >= 1) parts.push(`1戸あたり ${yen(own / units)}（${units}戸で割った計算）`);
  return `<p class="m-calc">${esc(parts.join("／"))}</p>`;
}

// print：入力欄を出さない（紙）。compact：A4の裏に収めるため、工事の中身と頼む先を省く。
function costRows(print = false, compact = false) {
  const aid = subsidy();
  return TIERS.map((tier) => {
    const items = measures()
      .filter((m) => m.tier === tier)
      .map((m) => {
        const status = aidStatus(m, aid);
        const chip = AID_WORDS[status] ? `<span class="aid ${status}">${AID_WORDS[status]}</span>` : "";
        const input = print ? "" : `<label class="m-est">見積り額<input type="number" inputmode="numeric" min="0" step="1000" data-est="${esc(m.key)}" value="${esc(S.est?.[m.key] || "")}" placeholder="例：見積書の金額">円</label>`;
        return `<li><div class="m-head"><b>${esc(measureName(m))}</b><span class="m-range">${esc(m.range)}${m.account ? `（${esc(m.account)}）` : ""}</span></div>
          <div class="m-sub"><small>決め方：${esc(m.decision)}</small>${chip}</div>
          ${compact ? "" : `<p class="m-what"><b>工事の中身</b>${esc(m.label)}</p>`}
          ${!compact && m.owner ? `<p class="m-what"><b>見積りを頼む先</b>${esc(m.owner)}</p>` : ""}
          ${!compact && m.cost_basis ? `<p class="m-what"><b>金額の出どころ</b>${esc(m.cost_basis)}${m.cost_url ? `（<a href="${esc(m.cost_url)}" target="_blank" rel="noopener">事例集</a>）` : ""}</p>` : ""}
          ${input}${estimateLine(m, aid)}</li>`;
      })
      .join("");
    return items ? `<h3 class="tier">${tier}</h3><ul class="measures">${items}</ul>` : "";
  }).join("");
}

// 建物全体での比べ方の参考（日本建築学会 技術報告集 28巻68号、2022年2月。仮想のマンションの試算で、直接工事費のみ・諸経費と消費税は別）。
// 対策の費用と、対策をせずに浸水したときの修復の費用を並べる。この建物の金額ではない。
const MODEL_COSTS = {
  source: "日本建築学会 技術報告集「既存分譲マンションの浸水対策改修とその費用対効果に関するモデル的検討」（2022年2月）",
  url: "https://www.jstage.jst.go.jp/article/aijt/28/68/28_442/_pdf/-char/ja",
  rows: [
    ["地下に電気室がある型（65戸）", "床上10cm：対策 39万円／修復 1,900万円", "床上30cm：対策 1,775万円／修復 2,800万円", "床上130cm：対策 3,065万円／修復 6,100万円"],
    ["電気室が1階の型（62戸）", "住棟には浸水なし（ポンプ室・駐車場に浸水）：対策 405万円／修復 2,500万円", "床上10cm：対策 2,170万円／修復 4,850万円", "床上110cm：対策 3,215万円／修復 9,500万円"],
  ],
};

function modelCosts() {
  const rows = MODEL_COSTS.rows.map(([name, ...cells]) => `<li><b>${esc(name)}</b>${cells.map((cell) => `<span>${esc(cell)}</span>`).join("")}</li>`).join("");
  return `<div class="model-costs"><p class="qtitle">参考：対策の費用と、浸水したときの修復の費用</p>
    <ul>${rows}</ul>
    <p class="hint">仮想のマンションの試算です（直接工事費のみ、諸経費と消費税は別。電力会社の負担分と専有部分は除く）。この建物の金額ではありません。出典：<a href="${MODEL_COSTS.url}" target="_blank" rel="noopener">${esc(MODEL_COSTS.source)}</a></p></div>`;
}

// 業者の確かめ方（2026-11-06 本人の指摘「サクラではない業者を選べるように」）。
// この道具は特定の業者を勧めず、紹介料も取らない（what-044）。だから業者の名前は出さず、自分で確かめる方法だけを出す。
const CONTRACTOR_CHECKS = [
  ["建設業の許可を調べる", "見積りを出した会社の名前で、国土交通省の「建設業者・宅建業者等企業情報検索システム」を引きます。", "https://etsuran2.mlit.go.jp/TAKKEN/"],
  ["電気の工事は登録を聞く", "盤や電気室に関わる工事は、電気工事業の登録（都道府県など）があるかを、登録番号で確かめます。工事の前に、主任技術者（いない建物は電気工事の業者）と停電の要否を決めます。", ""],
  ["止水板は性能の書類を求める", "JIS A 4716 の等級（Ws-1〜Ws-6）や「Ws-3相当」などの表示が、どの試験によるものかを書面で出してもらいます。", ""],
  ["見積りは2社以上から", "「無料で点検する」と訪ねてくる業者には応じず、急がされてもその場で契約しません。保険金の申請を前提にした工事の勧誘にも応じません。困ったときは消費者ホットライン（188）へ。", "https://www.kokusen.go.jp/pdf/tenken_reform.pdf"],
];

function contractorBox() {
  const items = CONTRACTOR_CHECKS.map(([head, text, url]) => `<li><b>${esc(head)}</b><span>${esc(text)}${url ? ` <a href="${url}" target="_blank" rel="noopener">出典・検索先</a>` : ""}</span></li>`).join("");
  return `<div class="contractor-box"><p class="qtitle">業者の確かめ方</p><p class="hint">この道具は、特定の業者を勧めず、紹介料も受け取りません。業者は、管理会社と理事会が次のことを確かめて選びます。</p><ul>${items}</ul></div>`;
}

function unitsBox() {
  return `<label class="m-est units">このマンションの戸数<input type="number" inputmode="numeric" min="1" step="1" data-units="1" value="${esc(S.units || "")}" placeholder="例：50">戸<small>（入れると、見積り額から1戸あたりを計算します）</small></label>`;
}

function subsidyBox(all = false) {
  const aid = subsidy();
  const cautions = (aid.cautions || []).slice(0, all ? 4 : 2).map((text) => `<li>${esc(text)}</li>`).join("");
  const source = aid.url ? `<p class="hint">出典：<a href="${esc(aid.url)}" target="_blank" rel="noopener">${esc(aid.label.replace(/（.*$/, ""))}の公式の案内</a>（${esc(aid.checked || "")} 確認）。申請を勧めるものではありません。</p>` : "";
  return `<div class="aid-box"><b>${esc(aid.label || "")}</b><p>${esc(aid.rate_label || "")}</p>${cautions ? `<ul>${cautions}</ul>` : ""}${source}</div>`;
}

// 画面1：場所を選んだらすぐ、この市区町村の補助を出す（2026-11-06 本人の指摘「マンション名から即座に」）。
function placeAid() {
  const aid = S.place?.subsidy;
  if (!aid) return "";
  return `<div class="place-aid"><p><b>この地域の補助</b>${esc(aid.label)}</p><small>${esc(aid.rate_label)}</small></div>`;
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
    ${costRows(true, true)}
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
      ${list.length ? `<ol class="asks">${asksList(list)}</ol>` : ""}
      ${heardItems().length || experienceLine() ? `<div class="heard"><p class="hint"><b>住民の話・見たこと（依頼メモに載ります）</b></p><ul>${experienceLine() ? `<li>${esc(experienceLine())}</li>` : ""}${heardItems().map((text) => `<li>${esc(text)}</li>`).join("")}</ul></div>` : ""}`;
  } else if (S.tab === "a4") {
    body = `<h1 class="title">理事会に出すA4表裏1枚</h1>
      <p class="hint">表は30秒で読める図と3行。裏は費用と補助。</p>
      <div class="paper">${a4Front(today())}</div>
      <div class="paper">${a4Back()}</div>`;
  } else {
    const cost = firstStepCost();
    body = `<h1 class="title">${cost ? `最初の手は ${esc(cost)}` : "対策の費用・補助の目安"}</h1>
      <p class="hint">${COST_FIXED}。円の金額は、見積り額を入れたときだけ計算します。</p>
      ${unitsBox()}
      ${costRows()}
      ${subsidyBox()}
      ${contractorBox()}
      ${modelCosts()}`;
  }
  const print = TABS.find(([key]) => key === S.tab)[2];
  return `<section class="s4">
    <div class="tabs" role="tablist">${tabs}</div>
    ${body}
    <button type="button" class="primary" data-act="print">${print}</button>
    <button type="button" class="send" data-act="send">文で送る（LINE・メールなど）</button>
    ${S.sendMsg ? `<p class="hint" role="status">${esc(S.sendMsg)}</p>` : ""}
    ${S.sendText ? `<textarea class="send-text" readonly rows="10">${esc(S.sendText)}</textarea>` : ""}
    ${saveBox()}
  </section>`;
}

// ---- 文で送る（2026-11-05） ----
// 理事会の仲間に、要点を文で送る。スマホでは共有の画面（LINE・メールなど）を開き、パソコンでは文をコピーする。
// 住所は町丁まで。固定の免責は言い換えずに付ける。サーバーには何も送らない。
function summaryText() {
  const b = S.building;
  const lines = [`【マンション浸水ロードマップ】${where()}`, `・${titleLine()}`];
  // 立地は札の値のまま（地図の想定）。深さを主役にしない。避難の判断は自治体の警戒レベルで。
  const rows = (S.place?.location?.rows || []).map((item) => `${PLACE_SHORT[item.key] || item.label} ${item.value || ""}`.trim());
  if (rows.length) lines.push(`・立地（地図の想定）：${rows.join("／")}`);
  lines.push(`・${EVAC_LINE}`);
  const exp = experienceLine();
  if (exp) lines.push(`・この辺りの経験（住民の話）：${exp}`);
  const list = steps();
  if (list.length) {
    lines.push(`・管理会社に頼む確認（${list.length}つ）`);
    list.forEach((step, i) => lines.push(`  ${i + 1}. ${PLAIN_ASK[step.key] || step.what}`));
  }
  const cost = firstStepCost();
  if (cost) lines.push(`・今すぐの手の費用の目安：${cost}（${COST_FIXED}）`);
  // 文には図がないので、「図は」ではなく、建物の形を確かめていないことを言う。
  if (b.sample.custom) lines.push("・建物の形（階数・機械の部屋の位置）はまだ確かめておらず、見本の形を借りた説明です");
  lines.push(`※${disclaimer() || ""}`);
  return lines.join("\n");
}

async function sendSummary() {
  const text = summaryText();
  S.sendText = "";
  if (navigator.share) {
    try {
      await navigator.share({ title: "マンション浸水ロードマップ", text });
      S.sendMsg = "共有の画面を開きました。";
      render();
      return;
    } catch (error) {
      if (error?.name === "AbortError") {
        S.sendMsg = "";
        render();
        return;
      }
    }
  }
  if (await copyText(text)) {
    S.sendMsg = "要点の文をコピーしました。LINE やメールに貼り付けて送ってください。";
  } else {
    // コピーできない環境では、文をそのまま見せて、手でコピーしてもらう。
    S.sendText = text;
    S.sendMsg = "自動でコピーできませんでした。下の文を長押し（パソコンは選んで右クリック）してコピーしてください。";
  }
  render();
}

// 文をコピーする。新しい方法がだめなら、古い方法でも試す。
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (error) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (fallbackError) {
      ok = false;
    }
    area.remove();
    return ok;
  }
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
    html = `<div class="sheet"><h1>対策の費用・補助の目安</h1><p>${esc(where())}　${date}</p>${costRows(true)}${subsidyBox(true)}<p class="sheet-line">${COST_FIXED}</p>${fixed}</div>`;
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
    S.hvSaid = "";
    S.est = {};
    S.units = "";
    S.exp = "";
    S.facts = null;
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
  S.hvSaid = answer === "none" ? "" : answer;
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

// ---- 図面の写真を送る前に縮める（2026-11-05） ----
// 長辺を 2000px 以下にし（それ以下なら等倍のまま）、JPEG（品質0.85）にする。部屋の名前の字が読める解像度は保つ。
// 1MB を超えたら、品質だけを少しずつ下げる（0.75 → 0.65）。寸法は下げない。
// API の画像の上限は1枚 10MB（base64）で、モデルの元の解像度は長辺 2,576px（Claude の Vision の資料、2026-11-05 に確認）。
const SHRINK_EDGE = 2000;
const SHRINK_QUALITIES = [0.85, 0.75, 0.65];
const SHRINK_TARGET_BYTES = 1024 * 1024;

async function shrinkImage(file) {
  try {
    // 写真の向き（EXIF）を反映して読む。
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, SHRINK_EDGE / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    // 透明な所は白にする（JPEG は透明を持てず、黒くなるのを防ぐ）。
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close?.();
    let blob = null;
    for (const quality of SHRINK_QUALITIES) {
      blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
      if (!blob) return null;
      if (blob.size <= SHRINK_TARGET_BYTES) break;
    }
    return blob;
  } catch (error) {
    // 縮められない画像（ブラウザが読めない形など）は、今まで通りそのまま送る。
    return null;
  }
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
      // 写真は、送る前にブラウザの中で縮めて JPEG にする（スマホの写真は1枚5〜10MB以上あり、API の画像の上限を超えるため）。
      // 縮められなかったときと PDF は、今まで通りそのまま送る。
      const shrunk = file.type.startsWith("image/") ? await shrinkImage(file) : null;
      const source = shrunk || file;
      body.data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = () => reject(new Error("ファイルを読めませんでした。"));
        reader.readAsDataURL(source);
      });
      body.media_type = shrunk ? "image/jpeg" : file.type;
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
  // 先にタイマーを置いてから描く（ボタンを最初から「止める」にするため）。
  S.timer = setInterval(() => {
    if (S.play >= 3) {
      // ③で止め、判定の見た目には戻さない。対策を押すと、その場で③の止まり方が変わる。
      clearInterval(S.timer);
      S.timer = 0;
      render();
      return;
    }
    S.play += 1;
    render();
  }, 1800);
  render();
}

screen.addEventListener("submit", async (event) => {
  if (event.target.id !== "find") return;
  event.preventDefault();
  const q = document.getElementById("q").value.trim();
  S.query = q;
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
  } else if (target.dataset.saveDays) {
    S.saveDays = Number(target.dataset.saveDays);
    render();
  } else if (target.dataset.hv) {
    setEngineer(target.dataset.hv);
  } else if (target.dataset.kind) {
    setRoom(target.dataset.kind, target.dataset.choice);
  } else if (target.dataset.measure) {
    // 対策は水の位置の上で比べるもの。判定の見た目のまま押されたら、③に切り替えて違いを見せる。
    S.measure = target.dataset.measure;
    if (!S.play) S.play = 3;
    render();
  } else if (target.dataset.drawing) {
    S.drawing = target.dataset.drawing;
    render();
  } else if (target.dataset.obs) {
    setObservation(target.dataset.obs, target.dataset.value);
  } else if (target.dataset.act === "facts") {
    findFacts();
  } else if (target.dataset.act === "use-facts") {
    useFacts();
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
    if (act === "play") (S.timer ? stopPlay() : startPlay());
    if (act === "to3") go(3);
    if (act === "to4") go(4);
    if (act === "read-sample") readPlan(null);
    if (act === "print") printSheet();
    if (act === "send") sendSummary();
    if (act === "pass-random") {
      S.savePass = randomPassword();
      S.saveMsg = "ランダムなパスワードを作りました。控えてから保存してください。";
      render();
    }
    if (act === "pass-copy") copyText(document.getElementById("save-pass")?.value || "", "パスワードをコピーしました。");
    if (act === "link-copy") copyText(S.saveLink, "リンクをコピーしました。");
    if (act === "save-link") saveAs("link");
    if (act === "save-file") saveAs("file");
    if (act === "open-saved") openSaved();
    if (act === "open-show") {
      S.openShown = true;
      render();
    }
  }
});

// 住んでいる階は、描き直さずに覚えるだけ（地図を読み直さない）。
screen.addEventListener("input", (event) => {
  if (event.target.id === "floor") S.floor = event.target.value;
  if (event.target.id === "own-floors") S.own.floors = event.target.value;
  if (event.target.id === "save-pass") S.savePass = event.target.value;
});

screen.addEventListener("change", (event) => {
  if (event.target.id === "plan-file" && event.target.files[0]) readPlan(event.target.files[0]);
  if (event.target.id === "open-file" && event.target.files[0]) {
    S.openFile = event.target.files[0];
    S.openMsg = "";
    render();
  }
  // 見積り額と戸数（この画面の中だけで計算する。サーバーには送らない）。
  if (event.target.dataset.est) {
    S.est = { ...(S.est || {}), [event.target.dataset.est]: event.target.value };
    render();
  }
  if (event.target.dataset.units) {
    S.units = event.target.value;
    render();
  }
});

document.getElementById("steps").addEventListener("click", (event) => {
  const button = event.target.closest("[data-go]");
  if (button && !button.disabled) go(Number(button.dataset.go));
});

// ---- 入力した内容の保存と共有（パスワードつき・期限つき。2026-11-05 本人の指示で戻した） ----
// この道具は入力を残さないので、次に開くときに入れ直さずに済むよう、ブラウザの中で暗号にして、リンクかファイルで持つ。
// 暗号の仕組みは 11/5 の一本化の前の web/share-crypto.js のまま（PBKDF2 → AES-GCM。鍵はパスワードと、リンクの # の後ろの値から作る）。
// パスワードはリンクにもファイルにも入れない。入れるのは場所・答え・住んでいる階・選んだ対策・見たこと・見積り額だけで、図面・チャット・APIキーは入れない。
// 「データが外に出ない」とは書かない（what-063）。
const ShareCrypto = (() => {
  const ITERATIONS = 200000;

  function toBase64(buffer) {
    let binary = "";
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.length; i += 32768) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    }
    return btoa(binary);
  }

  function fromBase64(text) {
    return Uint8Array.from(atob(text), (char) => char.charCodeAt(0));
  }

  async function deriveKey(password, linkKey, salt) {
    const material = await crypto.subtle.importKey("raw", new TextEncoder().encode(`${password}.${linkKey}`), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey(
      { name: "PBKDF2", salt, iterations: ITERATIONS, hash: "SHA-256" },
      material,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"],
    );
  }

  function available() {
    return Boolean(window.crypto && crypto.subtle);
  }

  async function encrypt(data, password) {
    const linkKey = toBase64(crypto.getRandomValues(new Uint8Array(24))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const key = await deriveKey(password, linkKey, salt);
    const plain = new TextEncoder().encode(JSON.stringify(data));
    const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, plain);
    return { linkKey, ciphertext: toBase64(cipher), iv: toBase64(iv), salt: toBase64(salt) };
  }

  async function decrypt(stored, password, linkKey) {
    const key = await deriveKey(password, linkKey, fromBase64(stored.salt));
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: fromBase64(stored.iv) }, key, fromBase64(stored.ciphertext));
    return JSON.parse(new TextDecoder().decode(plain));
  }

  return { available, encrypt, decrypt };
})();

const SAVE_DAYS = [[7, "1週間"], [30, "1か月"], [90, "3か月"]];
const SAVE_FIELDS = ["place", "demoId", "sampleId", "choices", "extra", "floor", "measure", "obs", "exp", "own", "statements", "hvSaid", "est", "units", "drawing", "screen", "reached"];
const PASS_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";

// 見分けにくい字（0/O、1/l/I）を除いた16字。偏りが出ないよう、使えない値は捨てて引き直す。
function randomPassword(length = 16) {
  const limit = 256 - (256 % PASS_CHARS.length);
  let out = "";
  while (out.length < length) {
    for (const byte of crypto.getRandomValues(new Uint8Array(length * 2))) {
      if (byte < limit && out.length < length) out += PASS_CHARS[byte % PASS_CHARS.length];
    }
  }
  return out;
}

function saveData() {
  return Object.fromEntries(SAVE_FIELDS.map((key) => [key, S[key]]));
}

function savePassword() {
  const pass = (document.getElementById("save-pass")?.value || S.savePass || "").trim();
  if (pass.length < 8) throw new Error("パスワードは8文字以上にしてください（「ランダムに作る」も使えます）。");
  return pass;
}

function saveBox() {
  const days = S.saveDays || 30;
  const chips = SAVE_DAYS.map(([d, word]) => `<button type="button" class="option${days === d ? " chosen" : ""}" data-save-days="${d}" aria-pressed="${days === d}">${word}</button>`).join("");
  return `<div class="save-box">
    <p class="qtitle">入力した内容を保存する（パスワードつき）</p>
    <p class="qsub">次に開くとき、場所と答えを入れ直さずに続きから見られます。入れるのは、場所・答え・住んでいる階・選んだ対策・見たこと・見積り額です。図面・チャット・APIキーは入れません。</p>
    <div class="own-row"><span>期限</span><div class="options">${chips}</div></div>
    <label class="save-pass">パスワード<input id="save-pass" type="text" autocomplete="off" spellcheck="false" value="${esc(S.savePass || "")}" placeholder="8文字以上"></label>
    <div class="options"><button type="button" class="option" data-act="pass-random">ランダムに作る</button><button type="button" class="option" data-act="pass-copy">パスワードをコピー</button></div>
    <p class="hint">パスワードを忘れると、元に戻せません。リンクやファイルとは別の方法で伝えてください。</p>
    <div class="options"><button type="button" class="option" data-act="save-link">期限つきのリンクを作る</button><button type="button" class="option" data-act="save-file">暗号にしたファイルを保存する</button></div>
    ${S.saveLink ? `<p class="save-link"><input readonly value="${esc(S.saveLink)}"><button type="button" class="option small" data-act="link-copy">リンクをコピー</button></p>` : ""}
    ${S.saveMsg ? `<p class="hint" role="status">${esc(S.saveMsg)}</p>` : ""}
    <p class="hint">ブラウザの中で暗号にしてから置くので、サーバーは中身を読めません。リンクは手元のサーバーに置くので、今は同じパソコンでだけ開けます。ファイルは、期限を過ぎるとこの道具では開けません。受け取った人が保存した写しや印刷した紙は消せません。</p>
  </div>`;
}

async function copyText(text, done) {
  try {
    await navigator.clipboard.writeText(text);
    S.saveMsg = done;
  } catch (error) {
    S.saveMsg = "コピーできませんでした。選んでコピーしてください。";
  }
  render();
}

async function saveAs(kind) {
  S.saveMsg = "";
  S.saveLink = "";
  try {
    if (!ShareCrypto.available()) throw new Error("このブラウザでは暗号にできません。");
    const password = savePassword();
    const days = S.saveDays || 30;
    const sealed = await ShareCrypto.encrypt(saveData(), password);
    const until = new Date(Date.now() + days * 86400000);
    const untilWord = `${until.getFullYear()}年${until.getMonth() + 1}月${until.getDate()}日`;
    if (kind === "link") {
      const stored = await postJSON("/api/share", { days, ciphertext: sealed.ciphertext, iv: sealed.iv, salt: sealed.salt });
      S.saveLink = `${location.origin}/?open=${stored.id}#${sealed.linkKey}`;
      S.saveMsg = `リンクを作りました。${untilWord} まで開けます。`;
    } else {
      const file = { kind: "shinsui-roadmap-save", version: 1, expires_at: until.getTime(), key: sealed.linkKey, ciphertext: sealed.ciphertext, iv: sealed.iv, salt: sealed.salt };
      const url = URL.createObjectURL(new Blob([JSON.stringify(file)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `shinsui-save-${today().replace(/\D/g, "")}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      S.saveMsg = `ファイルを保存しました。${untilWord} まで、この道具の「保存したものを開く」で開けます。`;
    }
  } catch (error) {
    S.saveMsg = error.message || "保存できませんでした。";
  }
  render();
}

// 開く：リンク（?open=…#…）か、保存したファイル。パスワードで戻し、続きの画面へ。
// 初めての人には関係がないので、画面1では小さなボタンだけにし、押したときだけ開く欄を出す（2026-11-06 本人の指摘「最初にパスワードがあるのは意味がない」）。
// リンクから来たときだけ、はじめから開いて画面の一番上に出す。
function openBox() {
  const fromLink = Boolean(S.openId);
  if (!fromLink && !S.openShown) return `<button type="button" class="link-like" data-act="open-show">前に保存したものを開く</button>`;
  return `<div class="open-box${fromLink ? " from-link" : ""}">
    <p class="qtitle">${fromLink ? "保存したリンクを開く" : "保存したものを開く"}</p>
    ${fromLink ? "" : `<label class="option file">保存したファイルを選ぶ<input type="file" id="open-file" accept="application/json,.json"></label>${S.openFile ? `<p class="hint">選んだファイル：${esc(S.openFile.name)}</p>` : ""}`}
    <label class="save-pass">パスワード<input id="open-pass" type="password" autocomplete="off"></label>
    <button type="button" class="option" data-act="open-saved">開く</button>
    ${S.openMsg ? `<p class="hint" role="status">${esc(S.openMsg)}</p>` : ""}
  </div>`;
}

async function openSaved() {
  S.openMsg = "";
  try {
    const password = document.getElementById("open-pass")?.value || "";
    let stored;
    let key;
    if (S.openId) {
      const response = await fetch(`/api/share/${encodeURIComponent(S.openId)}`);
      if (!response.ok) throw new Error("このリンクは期限が過ぎたか、見つかりません。");
      stored = await response.json();
      key = S.openKey;
    } else {
      if (!S.openFile) throw new Error("保存したファイルを選んでください。");
      stored = JSON.parse(await S.openFile.text());
      if (stored.kind !== "shinsui-roadmap-save") throw new Error("この道具で保存したファイルではありません。");
      if (!(stored.expires_at > Date.now())) throw new Error("このファイルは期限が過ぎています。");
      key = stored.key;
    }
    let data;
    try {
      data = await ShareCrypto.decrypt(stored, password, key);
    } catch (error) {
      throw new Error("パスワードが違うか、リンク・ファイルが壊れています。");
    }
    SAVE_FIELDS.forEach((field) => {
      if (field in data) S[field] = data[field];
    });
    S.openId = "";
    S.openFile = null;
    history.replaceState(null, "", location.pathname);
    const screenNo = Math.min(Math.max(Number(data.screen) || 1, 1), 4);
    if (S.place && screenNo >= 2) {
      await loadBuilding();
      S.reached = Math.max(Number(data.reached) || screenNo, screenNo);
      go(screenNo);
    } else {
      S.screen = 1;
      render();
    }
    return;
  } catch (error) {
    S.openMsg = error.message || "開けませんでした。";
  }
  render();
}

// リンクから来たとき：?open=id と、# の後ろの鍵を覚える（鍵はサーバーへ送らない）。
(() => {
  const id = new URLSearchParams(location.search).get("open");
  if (id && /^[0-9a-f]{32}$/.test(id)) {
    S.openId = id;
    S.openKey = location.hash.slice(1);
  }
})();

// ---- Claude の API キー（このパソコンの localhost で開いたときだけ） ----

function renderKey() {
  renderChatRoute();
  const toggle = document.getElementById("key-toggle");
  const local = ["localhost", "127.0.0.1"].includes(location.hostname);
  if (!S.claude) return;
  toggle.hidden = !local && !S.claude.claude;
  toggle.textContent = "設定";
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
