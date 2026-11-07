"use strict";

// マンション浸水チェック（2026-11-05 一本化）。
// 4つの画面を順に進む：1 場所 → 2 確かめる → 3 止まるもの → 4 渡す。
// 絵は構内平面図だけ。部屋の位置は /api/building の sample.views から描き、部屋の色はサーバーの判定（equipment の verdict）のまま塗る。
// この画面では新しい判定を作らない。色は 赤＝確かめて止まるおそれ／橙＝未確認（危険という意味ではない）／緑＝問題なし。
// 青い矢印は水の入り道（入りうる所）で、判定ではない。
// 画面2（確かめる）の答えは「管理会社が図面で確かめた答え」で、今の判定の語（pump・upper:pump・absent:pump など）のまま送る。

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
  // 画面2（確かめる）で分かった、判定が読む答え（hv：主任技術者がいるか、tr：東京電力の部屋があるか）。
  extra: {},
  // 画面2（確かめる）の答え。部屋の種類ごとに basement / ground / upper / absent。
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
  // 画面2（確かめる）：図面が手元にあるか（null は未回答）と、図面がない人が見て答えたこと。
  drawing: null,
  obs: {},
  // 画面1：この辺りが水につかった経験（住民の話。判定は変えず、依頼メモに載せる）。
  exp: "",
  // 建物名から Web で探した階数の候補（人が「この値を使う」を押すまで使わない）。
  query: "",
  facts: null,
  factsBusy: false,
  // 住所で選んだとき、その住所の建物名と階数を Web で探した候補（busy / found / message / answer：yes・no）。人が「はい」を押すまで使わない。
  at: null,
  sendMsg: "",
  sendText: "",
  // 画面2の対策の切り替え（what-019）：plate（止水板だけ）／hole（壁の穴を塞ぐ）／raise（盤を高くする）。
  measure: "none",
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
  { key: "homes", label: "各戸の電気", short: "電気", from: ["tr"], small: () => "冷蔵庫も冷房も止まる" },
];
const SERVICE_OF_TILE = { water: "pump", ev: "ev", homes: "homes" };
// 平面図の部屋と、判定の行（サーバーの _UPPER_ROWS・_ABSENT_ROWS と同じ対応）。ほかの部屋は色を塗らない。
const KIND_ROWS = { pump: "water", elec: "power", panel_room: "power", tr: "tr", gen: "gen", tank: "tank", park: "park", ev: "ev" };
const ROOM_SHORT = { elec: "電気室", tr: "借室", panel_room: "分電盤室", pump: "ポンプ室", gen: "発電機室", tank: "雨水槽", park: "駐車場ピット", ev: "EV" };
// サーバーの scenario の wet（浸かる設備）と、平面図の部屋。hv＝高圧受変電設備の部屋、panel＝ポンプの制御盤の部屋。
const WET_ROOMS = { ev: ["ev"], hv: ["elec", "panel_room"], panel: ["pump"], tr: ["tr"], gen: ["gen"], tank: ["tank"] };
// 管理会社に頼む確認を、電気を知らない人の言葉で言う（サーバーの top_line.steps の key ごと。中身は同じ確認）。
const PLAIN_ASK = {
  water: "給水ポンプ制御盤の下端が、床から何cmの高さにあるか",
  power: "受変電設備（電気室・共用分電盤室）がどの階にあり、高圧受電か低圧受電か",
  tr: "借室（東京電力の変圧器室）が建物内のどの階にあるか",
  entry: "電気室・機械室の壁のケーブル管路口（貫通穴）が止水処理されているか",
  ev: "浸水警報時のエレベーター最上階退避手順があるか",
  drain: "汚水・排水ポンプの設置階と制御盤の高さ",
  backflow: "前面道路の下水道整備状況（合流式・分流式・側溝放流）と逆止弁の有無",
  lock: "停電時のオートロック・自動ドアの解錠・開閉方式",
  park: "機械式駐車場ピットの排水ポンプ容量と止水手順",
};
// 再生の注意書き（平面図の水の位置①②③の再生）。時刻や速さは出さない。
const PLAY_NOTE = "実際の浸水速度の予測ではなく、水が順番に入る仕組みの模式です。";
const CAPTIONS = {
  1: "大雨で、道路に水がたまる",
  2: "水が、入り道から建物に入る",
  3: "機械の部屋が水につかり、止まる想定",
};
// 画面2（確かめる）の問い。kind は今の判定が読む部屋の語。「地下」「1階」は、図面でその部屋を確かめた印になる。
const QUESTIONS = [
  { no: "①", row: "water", kind: () => "pump", title: "給水ポンプ室は、図面で何階ですか？", options: ["basement", "ground", "upper", "absent"] },
  { no: "②", row: "power", kind: (b) => (b.sample.has_chief_engineer ? "elec" : "panel_room"), title: "電気室（共用分電盤室のこともあります）は、図面で何階ですか？", options: ["basement", "ground", "upper"] },
  { no: "③", row: "tr", kind: () => "tr", title: "借室（東京電力の変圧器室）は、図面で何階ですか？", options: ["basement", "ground", "upper", "absent"] },
];
const OPTION_WORDS = { basement: "地下", ground: "1階", upper: "2階以上", absent: "図面にない", none: "未確認" };
// 進み具合の行に出す、問いの部屋の短い名前。
const ROOM_ASK_SHORT = { pump: "給水ポンプ室", elec: "電気室", panel_room: "電気室", tr: "借室" };
// 画面2（確かめる）の一文（2026-11-07・13回目：本人の指示で骨組みから作り直し）。
const CHECK_LEAD = "機械室の階によって、浸水時に止まる設備が決まります。竣工図で3項目を確認してください。";
// 図面がない人向けの一文（見て分かる3つで建物の形を仮に決め、確認は管理会社に頼む）。
const CHECK_LEAD_NO_DRAWING = "竣工図がなくても進められます。外観から分かる3項目で建物の形を仮設定し、確認事項は管理会社への依頼メモにまとめます。";
// 立地の行の短い名前。
const PLACE_SHORT = { flood: "川の洪水", inland: "下水・水路", surge: "高潮", ground: "土地の高さ", landform: "土地の成り立ち", rainband: "線状降水帯", record: "浸水の記録" };
// 対策の短い名前（サーバーの measures の key ごと。くわしい文は折りたたみに入れる）。
const MEASURE_SHORT = {
  hole: "壁の穴をふさぐ",
  plate: "置くだけの止水板と土のう",
  procedure: "大雨の前の手順を決める",
  tepco: "借室の対策を東京電力に照会",
  pump_check: "排水ポンプの点検",
  panel: "給水ポンプ制御盤を高く付け替える",
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
  ["memo", "① 管理会社への依頼メモ", "依頼メモを印刷"],
  ["a4", "② 理事会A4資料（1枚）", "理事会A4資料を印刷"],
  ["cost", "③ 対策費用・補助金試算", "費用・補助金試算を印刷"],
];
const BORROWED = "※表示している平面図・断面図は、入力された階数・設備位置をもとにした模式図です。実際の図面ではありません。";
// 引込みが未確認のとき、図の HH・管路の絵は借りた見本の形（仮の表示）。前提文の「引込み方式は未確認」と食い違わないように添える（2026-11-07・13回目）。
const FEED_UNKNOWN_NOTE = "引込み経路（HH・管路）は仮の表示で、単線結線図で未確認です。";
function borrowedNote() {
  const sample = S.building?.sample;
  if (!sample?.custom) return "";
  return BORROWED + (sample.feed_unknown ? FEED_UNKNOWN_NOTE : "");
}
// 紙の裏に出す固定の文（前の A4 の裏と同じ。言い換えない）。
const SHEET_FIXED = [
  "浸水実績は自治体の公表データを独自に集計・加工したもので、自治体の公式証明ではない",
  "本シートは予報ではなく、現時点の静的な整理である",
  "費用は桁の目安で、保安法人・工事業者の見積りに置き換えること",
];
const COST_FIXED = SHEET_FIXED[2];

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

// 未回答の数：①②③で、まだ答えを選んでいないもの（1階を選んでも減る）。
function openCount() {
  if (!S.building) return 0;
  return QUESTIONS.filter((q) => !S.choices[q.kind(S.building)] && !(q.row === "power" && S.building.sample.engineer_unsure && !S.extra.hv)).length;
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

function foundName() {
  return (!S.sampleId && S.facts?.found?.building) || "";
}

function where() {
  const b = S.building;
  return `${b.sample.custom ? foundName() || "（建物名）" : b.sample.name}／${townLabel(S.place.site.label)}`;
}

// 画面の上の小さな行：建物名が分かっていれば「建物名／町丁」、分からなければ町丁だけ。
function kicker() {
  if (!S.building || !S.place) return "";
  return S.building.sample.custom && !foundName() ? townLabel(S.place.site.label) : where();
}

function joinJa(words) {
  if (words.length <= 1) return words.join("");
  if (words.length === 2) return `${words[0]}と${words[1]}`;
  return words.join("・");
}

function titleLine() {
  if (MAIN.every((key) => verdict(key) === "clear")) return S.building.top_line.lead;
  if (roomsFloor() === "upper") return "主要設備の設置階を図面で確認";
  const names = TILES.filter((tile) => worst(tile.from) !== "clear").map((tile) => tile.short);
  const where = { basement: "地下", ground: "1階" }[roomsFloor()] || "";
  return `${where ? `${where}の` : ""}機械室が浸水すると、全戸で${joinJa(names)}が止まります`;
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


function subsidy() {
  // 画面1で住所から取った制度（S.place.subsidy）を最優先。見本の地域は、場所がないときだけ（2026-11-07・13回目）。
  const region = S.place?.subsidy?.region || S.building?.sample?.subsidy || "none";
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
function pinAnchors(cad) {
  const anchors = {};
  const corner = (keys) => {
    const key = keys.find((k) => cad.rooms[k]);
    if (!key) return null;
    const box = cad.rooms[key];
    // 部屋の名前に重ならないよう、壁の角に立てる。小さい部屋（EV など）は部屋の真ん中。
    return box.w < 60 ? [box.x + box.w / 2, box.y + box.h / 2] : [box.x + box.w - 8, box.y + 8];
  };
  anchors.water = corner(["pump"]);
  anchors.power = corner(["elec", "panel_room"]);
  anchors.tr = corner(["tr"]);
  anchors.ev = corner(["ev"]);
  anchors.park = corner(["park"]);
  const hole = cad.marks.find((m) => m.kind === "conduit_hole" || m.kind === "door_low");
  if (hole) anchors.entry = [hole.x, hole.y];
  return anchors;
}

// 水位の段（2026-11-06 本人の指摘「浸水の状況をどう見たらいいか分からない」）：平面図の下に3段の表。今の段に「いま」。
// 床からの高さは一般的な目安で、建物ごとに竣工図か実測で確かめる。
const GAUGE = [
  [3, "③ 機械の部屋に水", "床から50cm", "盤・高圧受変電設備・借室の下端まで → 水も電気も止まる"],
  [2, "② 一番低い床に水", "床から20〜30cm", "床置きの給水ポンプ制御盤・EVピット → 断水、EV停止"],
  [1, "① 道路が冠水", "0cm", "道路・壁の穴から水が入り始める"],
];

function gauge(level) {
  const rows = GAUGE.map(([n, name, cm, what]) => `<tr class="${level === n ? "now" : level > n ? "under" : ""}"><th>${level === n ? "いま" : ""}</th><td><b>${name}</b><small>${cm}</small></td><td>${what}</td></tr>`).join("");
  return `<table class="gauge"><caption>水位の段（高さは一般的な目安。建物ごとに竣工図か実測で確かめます）</caption><tbody>${rows}</tbody></table>`;
}

// 水の位置①②③の見出し。サーバーの water_levels の文は、その下に小さく添える。
const LEVEL_HEAD = { 1: "① 道路が冠水", 2: "② 一番低い床に水", 3: "③ 機械の部屋に水" };

// 部屋の状態（判定の色 → 水位・対策で「浸水・停止」「止水・稼働」に変わる。2026-11-06 本人の指示・7回目）。
const MACHINE_ROOMS = ["pump", "elec", "panel_room", "tr", "gen", "tank", "ev"];
function roomStates(level) {
  const out = {};
  const wet = new Set((level ? scenario(level)?.wet : []) || []);
  const protectedNow = S.measure !== "none" && level > 0;
  Object.entries(KIND_ROWS).forEach(([key, rowKey]) => {
    const r = row(rowKey);
    if (!r) return;
    let state = r.verdict;
    let word = LOOK[r.verdict]?.word || "未確認";
    const isWet = [...wet].some((w) => (WET_ROOMS[w] || []).includes(key));
    if (level && isWet) {
      state = "wet";
      word = "浸水・停止";
      out[key] = { state, word, depth: level >= 3 ? "deep" : "shallow" };
      return;
    } else if (level && protectedNow && MACHINE_ROOMS.includes(key)) {
      state = "safe";
      word = "止水・稼働";
    }
    out[key] = { state, word };
  });
  return out;
}

// 部屋の色と札を、CAD の線の上に半透明で重ねる（平面図・断面図で共通）。
function roomOverlay(key, box, st, big, place = "plan") {
  // 部屋の名前は cad.js が1回だけ描く（上寄せ）。ここでは色と札だけを重ね、文字を二重にしない（2026-11-07 本人の指摘・14回目）。
  const flash = S.flash.includes(key) ? " flash" : "";
  const parts = [`<rect x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}" class="p-over ${st.state}${st.depth ? ` ${st.depth}` : ""}${flash}" data-room="${esc(key)}"/>`];
  const cx = box.x + box.w / 2;
  const fs = Math.min(fitText(st.word, box.w - 6, big ? 13 : 11, 7) || 0, box.h / (place === "section" ? 4 : 3.2));
  if (fs > 7) {
    const bw = st.word.length * fs * 1.05 + 8;
    // 平面図は部屋の下寄り、断面図は名前（上）と機器の文字（下）の間（2026-11-07・22回目：重なりの指摘）。
    const by = box.y + box.h * (place === "section" ? 0.4 : 0.62);
    parts.push(`<g class="p-badge ${st.state}"><rect x="${cx - bw / 2}" y="${by - fs * 0.8}" width="${bw}" height="${fs * 1.6}"/><text x="${cx}" y="${by + fs * 0.38}" style="font-size:${fs}px">${esc(st.word)}</text></g>`);
  }
  return parts.join("");
}

// 構内平面図：建築CAD風の線（web/cad.js）の上に、判定の色・水の入り道・止水ガード・番号のピンを重ねる。
function plan({ level = 0, pins = {}, small = false } = {}) {
  const sample = S.building.sample;
  const view = machineView(sample);
  // 自分の建物は「（よくある形の例）」と添える（借りた見本の形）。
  const cad = CAD.plan(sample, sample.views.indexOf(view), { compact: small, title: sample.custom ? `${view.name}（よくある形の例）` : view.name });
  const shape = planShape(sample);
  const states = roomStates(level);
  const protectedNow = S.measure !== "none" && level > 0;
  const parts = [];
  Object.entries(cad.rooms).forEach(([key, box]) => {
    if (states[key]) parts.push(roomOverlay(key, box, states[key], !small));
    // 浸かる部屋には青い波の模様を重ねる（水が来ている見た目。2026-11-07・25回目）。
    if (states[key]?.state === "wet") parts.push(`<rect x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}" class="p-water-pattern ${states[key].depth || ""}"/>`);
  });
  // 道路の冠水。
  const road = cad.marks.find((m) => m.kind === "road");
  if (road && level >= 1) parts.push(`<rect x="0" y="${road.y}" width="${cad.w}" height="${cad.h - road.y}" class="p-flood-band"/>${wave(0, cad.w, road.y + 10, 3, 22)}`);

  // 水の入り道（青い矢印）。判定ではなく、入りうる所。対策①②を選ぶと、入口に青い止水ライン、壁の穴に塞いだ印が入り、矢印は止まる。
  const entries = [];
  const topOf = (xmm) => cad.px(xmm, 0);
  if (shape.slope) {
    const [x, y] = topOf((shape.slope.mm[0] + shape.slope.mm[2]) / 2);
    const target = roomAt(view, shape.slope.x + shape.slope.w / 2, 0.02);
    const box = target && cad.rooms[target.key];
    entries.push({ x1: x, y1: y - 34, x2: x, y2: box ? box.y + Math.min(40, box.h * 0.45) : y + 30, label: "スロープから", lx: x - 10, ly: y - 22, anchor: "end" });
  }
  if (shape.basin) {
    const [x, y] = topOf(shape.basin.x * shape.W);
    entries.push({ x1: x, y1: y - 34, x2: x, y2: y + 40, label: "雨水ますから", lx: x - 10, ly: y - 22, anchor: "end" });
  }
  cad.marks.filter((m) => m.kind === "conduit_hole" || m.kind === "door_low").forEach((m) => {
    const target = roomAt(view, (m.x - cad.px(0, 0)[0]) / (cad.px(shape.W, 0)[0] - cad.px(0, 0)[0]), 0.98);
    const box = target && cad.rooms[target.key];
    entries.push({ x1: m.x, y1: m.y + 46, x2: m.x, y2: box ? box.y + box.h - Math.min(40, box.h * 0.45) : m.y - 30, label: m.kind === "conduit_hole" ? "管から壁の穴へ" : "扉・換気口から", lx: m.x + 14, ly: m.y + 40, anchor: "start", hole: m.kind === "conduit_hole", wallY: m.y });
  });
  entries.forEach((entry) => {
    const blocked = protectedNow;
    // 止める位置：スロープ・雨水ますは建物の縁（矢印の向きで y1 と y2 の間の縁）、壁の穴・扉は壁の位置。
    const down = entry.y2 > entry.y1;
    const stopY = entry.wallY ?? (down ? entry.y1 + 34 : entry.y1 - 46);
    const endY = blocked ? (down ? stopY - 8 : stopY + 8) : entry.y2;
    parts.push(`<path d="M${entry.x1} ${entry.y1} L${entry.x2} ${endY}" class="p-arrow${level >= 1 ? " on" : ""}${blocked ? " cut" : ""}" marker-end="url(#p-head)"/>`);
    if (blocked) {
      // 水が止まった印：赤い×と、壁の穴は埋めた印、それ以外は横一文字の止水板。
      if (entry.hole) parts.push(`<g class="p-sealed"><circle cx="${entry.x1}" cy="${entry.wallY}" r="11"/><path d="M${entry.x1 - 5} ${entry.wallY - 5} L${entry.x1 + 5} ${entry.wallY + 5} M${entry.x1 + 5} ${entry.wallY - 5} L${entry.x1 - 5} ${entry.wallY + 5}"/></g>`);
      else parts.push(`<path d="M${entry.x1 - 26} ${stopY} L${entry.x1 + 26} ${stopY}" class="p-plate big"/>`);
      parts.push(`<g class="p-stop"><circle cx="${entry.x1 + (down ? 18 : -18)}" cy="${endY}" r="9"/><path d="M${entry.x1 + (down ? 18 : -18) - 4} ${endY - 4} l8 8 m0 -8 l-8 8"/></g>`);
    } else if (entry.hole) parts.push(`<circle cx="${entry.x1}" cy="${entry.wallY}" r="7" class="p-hole"/>`);
    parts.push(`<text x="${entry.lx}" y="${entry.ly}" class="p-entry${blocked ? " sealed" : ""}" text-anchor="${entry.anchor}">${esc(blocked ? (entry.hole ? "穴を埋めて止める" : "止水板で止める") : entry.label)}</text>`);
  });
  // 外壁の扉に止水ガード（対策①②）。
  if (protectedNow) {
    cad.marks.filter((m) => m.kind === "opening" && m.openingKind !== "window").forEach((m) => {
      const vertical = m.side === "left" || m.side === "right";
      const off = m.side === "top" || m.side === "left" ? -7 : 7;
      parts.push(vertical ? `<path d="M${m.x + off} ${m.y} L${m.x + off} ${m.y + m.w}" class="p-plate"/>` : `<path d="M${m.x} ${m.y + off} L${m.x + m.w} ${m.y + off}" class="p-plate"/>`);
    });
  }
  // 番号のピン。
  const anchors = pinAnchors(cad);
  Object.entries(pins).forEach(([key, number]) => {
    const at = anchors[key];
    if (at) parts.push(`<g class="p-pin"><circle cx="${at[0]}" cy="${at[1]}" r="15"/><text x="${at[0]}" y="${at[1] + 6}">${number}</text></g>`);
  });
  const label = level ? `もし水がここまで来たら：${CAPTIONS[level]}` : titleLine();
  return `<svg class="plan-svg cad${small ? " small" : ""}" viewBox="0 0 ${cad.w} ${cad.h}" role="img" aria-label="${esc(label)}">
    <defs><marker id="p-head" markerWidth="5" markerHeight="5" refX="2.6" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 z" class="p-head"/></marker>
      <pattern id="p-waves" width="24" height="12" patternUnits="userSpaceOnUse"><path d="M0 6 q6 -4 12 0 t12 0" class="p-wave-line"/></pattern></defs>
    ${cad.svg}${parts.join("")}
  </svg>`;
}

// 建物の断面図（web/cad.js）：前面道路のGL・歩道のハンドホール・地中の管と壁の穴・スロープ・機械室と盤の高さ・上の階。
// 水位①②③で青い水位線と水の面が入り、対策①②で入り道に止水ガードが入る。部屋の色と札は平面図と同じ。
// 水面の波（x0〜x1 の上端 y に、山と谷を繰り返す線）。
function wave(x0, x1, y, amp = 2.5, step = 14) {
  if (x1 - x0 < step) return "";
  let d = `M${x0} ${y}`;
  for (let x = x0; x < x1; x += step) d += ` q${step / 4} ${-amp} ${step / 2} 0 t${step / 2} 0`;
  return `<path d="${d}" class="s-wave"/>`;
}

function sectionFigure(level = 0, small = false) {
  if (typeof CAD === "undefined" || !S.building) return "";
  const sample = S.building.sample;
  const view = machineView(sample);
  const shape = planShape(sample);
  const spec = {
    floors: Number(sample.floors) || 5,
    basement: /地下/.test(view.name) ? 1 : 0,
    rooms: view.rooms.filter((r) => ["elec", "tr", "panel_room", "pump", "water_tank", "ev", "stair", "park", "gen", "tank"].includes(r.key)).map((r) => ({ key: r.key, label: r.label.split("\n")[0] })),
    panelMount: sample.panel_mount,
    undergroundFeed: Boolean(sample.underground_feed),
    feedUnknown: Boolean(sample.feed_unknown),
    hasSlope: Boolean(shape.slope),
    pit: true,
  };
  const sec = CAD.section(spec);
  const states = roomStates(level);
  const protectedNow = S.measure !== "none" && level > 0;
  const parts = [];
  const boxes = Object.values(sec.rooms);
  const left = Math.min(...boxes.map((b) => b.x));
  const right = Math.max(...boxes.map((b) => b.x + b.w));
  const bottom = Math.max(...boxes.map((b) => b.y + b.h));
  // 水の面（道路の外は①の高さ、中は水位の段の高さ）。対策で守れたときは中に水を入れない。
  Object.entries(sec.rooms).forEach(([key, box]) => {
    if (states[key]) parts.push(roomOverlay(key, box, states[key], !small, "section"));
  });
  // 水は部屋の色の上に描く（濃い青の面＋動く波の線。2026-11-07・25回目：点線だけでは水に見えないという指摘）。
  if (level >= 1) {
    const gl = sec.levels[1];
    parts.push(`<rect x="0" y="${gl - 7}" width="${Math.max(0, left - 6)}" height="7" class="s-water deep"/>${wave(0, Math.max(0, left - 6), gl - 7)}`);
    const inside = sec.levels[level];
    const wetKeys = Object.keys(states).filter((key) => states[key].state === "wet" && sec.rooms[key]);
    if (!protectedNow && wetKeys.length) {
      // 水面は地下の端から端まで一続きの帯（部屋ごとの切れ目を作らない）。部屋の下端は一番深い部屋に合わせる。
      const top = Math.min(inside, bottom);
      parts.push(`<rect x="${left}" y="${top}" width="${right - left}" height="${bottom - top}" class="s-water deep"/>${wave(left, right, top)}`);
      parts.push(`<text x="${left + 4}" y="${top - 6}" class="s-level-label" text-anchor="start">水位${["", "①", "②", "③"][level]}</text>`);
    }
  }
  // 水の入り道と止水ガード。
  (sec.routes || []).forEach((route) => {
    // 対策のときは、止める位置までの道だけを描き、そこに立てた止水板（または埋めた穴）と赤い×を置く。
    let pts = route.points;
    if (protectedNow && route.block) {
      const [bx, by] = route.block;
      const near = pts.reduce((best, pt, i) => (Math.hypot(pt[0] - bx, pt[1] - by) < Math.hypot(pts[best][0] - bx, pts[best][1] - by) ? i : best), 0);
      pts = [...pts.slice(0, Math.max(1, near)), [bx, by]];
    }
    const d = pts.map((pt, i) => `${i ? "L" : "M"}${pt[0]} ${pt[1]}`).join(" ");
    parts.push(`<path d="${d}" class="p-arrow s-route${level >= 1 ? " on" : ""}${protectedNow ? " cut" : ""}"${protectedNow ? "" : ' marker-end="url(#s-head)"'}/>`);
    if (protectedNow && route.block) {
      const [x, y] = route.block;
      if (route.key === "hole") parts.push(`<g class="p-sealed"><circle cx="${x}" cy="${y}" r="9"/><path d="M${x - 4} ${y - 4} L${x + 4} ${y + 4} M${x + 4} ${y - 4} L${x - 4} ${y + 4}"/></g><text x="${x}" y="${y + 20}" class="p-entry sealed s-small" text-anchor="middle">穴を埋める</text>`);
      else parts.push(`<path d="M${x} ${y + 3} L${x} ${y - 24}" class="p-plate big"/><g class="p-stop"><circle cx="${x - 12}" cy="${y - 10}" r="7"/><path d="M${x - 15} ${y - 13} l6 6 m0 -6 l-6 6"/></g><text x="${x}" y="${y - 29}" class="p-entry sealed s-small" text-anchor="middle">止水板で止める</text>`);
    }
  });
  if (protectedNow && S.measure === "full") {
    // 対策②：床置きの盤を高くした印（給水ポンプ室・電気室の上の端）。
    ["pump", "elec"].forEach((key) => {
      const b = sec.rooms[key];
      if (b) parts.push(`<g class="s-raise"><rect x="${b.x + 3}" y="${b.y + 3}" width="44" height="14"/><text x="${b.x + 25}" y="${b.y + 14}">盤↑高く</text></g>`);
    });
  }
  return `<svg class="plan-svg cad section${small ? " small" : ""}" viewBox="0 0 ${sec.w} ${sec.h}" role="img" aria-label="建物の断面図（水の入り道と盤の高さ）">
    <defs><marker id="s-head" markerWidth="5" markerHeight="5" refX="2.6" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 z" class="p-head"/></marker></defs>
    ${sec.svg}${parts.join("")}
  </svg>`;
}


// 暮らしの札（2026-11-05 本人の指摘「これだとわかりにくい」）。
// 水の位置を出しているときは、札の上に「水が③まで来たら」と書き、どの状態の札かを言う。
// 「？」は言葉で「分からない」と言う。止まらない札は「止まらない（稼働）」（2026-11-06 本人の指示）。
const LEVEL_MARK = { 1: "①", 2: "②", 3: "③" };

function lifeChips(level = 0) {
  const n = Number(S.floor);
  const tiles = TILES.map((tile) => {
    let state = worst(tile.from);
    let mark = LOOK[state].word;
    let small = state === "clear" ? "" : `止まると、${tile.small(n)}`;
    if (level) {
      const raw = serviceState(level, SERVICE_OF_TILE[tile.key]);
      state = { stopped: "stopped", unknown: "unconfirmed" }[raw] || "clear";
      mark = { stopped: "止まる想定", unknown: "分からない" }[raw] || "止まらない（稼働）";
      small = { stopped: tile.small(n), unknown: "東京電力の設備しだい" }[raw] || "";
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



// 深さの札の行と、地図に重ねる層の対応（洪水は想定最大を先に）。地図と札で同じ層を使う。











// ---- 内水と、この辺りの経験（2026-11-05） ----
// 内水（下水や水路があふれる）は、国の重ねるハザードマップにデータがない所が多い。市区町村が別に出していることがあるので案内する。
const WAGAMACHI = "https://disaportal.gsi.go.jp/hazardmap/";


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




// ---- WHY に沿った画面1・2の部品（2026-11-05 作り直し） ----
// 画面1の一行：命を守る避難の判断と、機械を守る足元の対策を混ぜない。
const EVAC_LINE = "避難するかどうかは、自治体のハザードマップと警戒レベルで決めます。この道具は、地図に色がなくても浅い水で止まる、建物の電気と水の足元の対策を整理します。";


// 対策の切り替え（what-019）。名前はサーバーの model_measures のまま。選んだ対策の固定の文（what-026）を言い換えずに添える。
const MEASURE_GAIN = { none: "出入口・壁の穴・床から水が入り、機械の部屋が浸かる", basic: "出入口の止水板と壁の穴埋めで、水は建物の縁で止まる（電気室・ポンプ室・借室が浸からない）", full: "さらに盤を高くして、止水板を越える水でも床置きの盤は浸からない" };
// 段階ごとの費用の目安（単価の表と同じ数字）。
const MEASURE_COST = { basic: "約40万円〜（通用口の止水板35万円＋穴埋め5万円）", full: "＋35万円（盤の壁掛け・かさ上げ。ケーブル延長ありは120万円）" };

function measureChips() {
  const b = S.building;
  const list = b.model_measures || [];
  if (!list.length) return "";
  const chips = list.map((m) => `<button type="button" class="option${S.measure === m.key ? " chosen" : ""}" data-measure="${esc(m.key)}" aria-pressed="${S.measure === m.key}">${esc(m.short)}</button>`).join("");
  // 対策で何が助かるかを1行で（2026-11-06 本人の指示：言い訳の固定文は出さない）。
  return `<div class="measures-switch big"><span class="sim-label">対策を切り替えて比べる</span><div class="options big">${chips}</div></div>`;
}

// 選んだ対策の「だれが決めるか」と「費用の桁」（what-017：切り替えると要る決議と桁が変わる。W1・W5：理事長が知りたいこと）。
// 文はサーバーの measures の decision・range・account のまま。桁には固定の文を必ず添える（what-038）。
const MODEL_MEASURE = { basic: "plate", full: "panel" };

// この建物で一番クリティカルな対策（サーバーの critical。建物の形で切り替わる。2026-11-06 本人の指示・7回目）。
// 2段構え（2026-11-06 本人の指示・8回目）：頻発する内水（〜1m）で止めない対策／万一の大洪水（3〜5m）で全損を防ぐ対策。各提案に、どの深さへの手かと根拠1行。
function criticalBox(print = false) {
  const c = S.building?.critical;
  if (!c) return "";
  const shortDec = (d) => String(d || "").replace(/（.*?）/g, "");
  const shortBasis = (b) => String(b || "").split("。")[0];
  // 表の中は対策名と金額を大きく、理由は最初の文だけ、決議は括弧を外す。全文は下の折りたたみ（2026-11-07・14回目）。
  const rows = (items) => items.map((item) => `<tr>
    <td class="c-no"><b>${item.no === 1 ? "最優先" : `優先${item.no}`}</b></td>
    <td class="c-main"><b>${esc(item.title)}</b><span class="c-depth">${esc(item.depth || "")}</span>${print ? "" : `<small class="c-basis">${esc(shortBasis(item.basis || item.why))}</small>`}</td>
    <td class="c-cost">${esc(item.cost.replace(/（.*?）/g, ""))}</td>
    <td class="c-dec">${esc(shortDec(item.decision))}</td>
  </tr>`).join("");
  // A4 では 0 円の項目（手順・ルール）は「本日決めること」に残し、表からは省いて文字を減らす（2026-11-07・22回目）。
  const tiers = (c.tiers || [{ title: "", items: c.items }])
    .map((tier) => ({ ...tier, items: print ? tier.items.filter((item) => !/^0円/.test(item.cost || "")) : tier.items }))
    .filter((tier) => tier.items.length)
    .map((tier) => `
    <p class="tier-head">${esc(tier.title)}</p>
    <table class="crit-table">
      <colgroup><col class="col-no"><col><col class="col-cost"><col class="col-dec"></colgroup>
      <thead><tr><th>優先</th><th>対策${print ? "" : "と理由（図面・立地の条件から）"}</th><th>概算目安</th><th>決議</th></tr></thead>
      <tbody>${rows(tier.items)}</tbody>
    </table>`).join("");
  const facts = c.facts?.length ? `<p class="c-facts"><b>前提：</b>${esc(c.facts.join("／"))}</p>` : "";
  // 画面では前提と理由・決議の全文を折りたたみに置く。A4（print）は今までどおり前提を表の上に出す。
  const detail = print ? "" : `<details class="more c-more"><summary>前提と、理由・決議のくわしい文</summary>${facts}<ul class="c-detail">${c.items.map((item) => `<li><b>${esc(item.title)}</b>：${esc(item.basis || item.why || "")}　決議：${esc(item.decision || "")}　${esc(item.cost)}</li>`).join("")}</ul></details>`;
  return `<div class="critical${print ? " print" : ""}"><p class="own-head">この建物のクリティカル対策（${esc(c.shape_name)}）</p>${tiers}${detail}${print ? "" : `<p class="hint c-note">※${COST_FIXED}</p>`}</div>`;
}

// 画面2：答えを入れた瞬間に、提案の1行目（最優先）が変わるのを見せる（入力→提案を一息に。2026-11-06 本人の指示）。
function criticalPreview() {
  const c = S.building?.critical;
  if (!c || !c.items.length) return "";
  const top = c.items[0];
  return `<p class="critical-line"><b>${esc(c.shape_name)}</b>の最優先の対策：<span>${esc(top.title)}</span><small>（${esc(top.cost)}。${esc(top.depth || "")}の水に対して）　詳しくは次の画面</small></p>`;
}

function decideLine() {
  const m = measures().find((item) => item.key === MODEL_MEASURE[S.measure]);
  if (!m) return "";
  const cost = MEASURE_COST[S.measure] || "";
  return `<p class="decide-line"><span><b>だれが決める</b>${esc(m.decision || "")}</span>${cost ? `<span><b>費用の目安</b>${esc(cost)}</span>` : ""}</p>
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

// 5項目の表の「短い理由」（2026-11-06 本人の指示：判定は国のデータから一発で出し、数値も表に出す）。html は表に入れる形。
function hazardPlain(item) {
  if (/数m先/.test(item.conclusion || "")) return esc("数m先に色あり");
  if (parseBand(item.value)) return esc(`${item.value}の想定`);
  if (item.value === "色なし") return esc("色なし");
  // 内水は国の地図にない市区町村が多い。市区町村の地図の案内を短く添える。
  // 内水のデータなしの理由は、カードでは「国のデータなし」だけにして、ここに全文を置く（2026-11-07・14回目）。
  if (item.key === "inland") return `${esc(item.conclusion || "データなし")}（<a href="${WAGAMACHI}" target="_blank" rel="noopener">わがまちハザードマップ</a>）`;
  return esc("データなし");
}

// 線状降水帯の行の理由（折りたたみ）：結論と、3つの型の全文（4方向の標高の数値を含む）。
function rainbandPlain(item) {
  const lines = (item.accent?.lines || []).map((line) => `${line.name}：${line.text}`).join("／");
  return esc(`${item.conclusion || ""}${lines ? `。${lines}` : ""}`);
}

function recordPlain(item) {
  if (item.verdict === "risk") return esc("同じ丁目に記録あり");
  return esc("記録なし（浸水なしの意味ではない）");
}

function placeLines() {
  const rows = S.place?.location?.rows || [];
  const rank = (item) => ({ risk: 0, unconfirmed: 1, clear: 2 }[item.verdict] ?? 1);
  return [...rows].sort((a, b) => rank(a) - rank(b)).map((item) => ({
    verdict: item.verdict_label === "注意" ? "caution" : item.verdict,
    word: item.verdict_label === "注意" ? "注意" : LOOK[item.verdict]?.word || "未確認",
    name: PLACE_SHORT[item.key] || item.label,
    conclusion: item.conclusion || "",
    key: item.key,
    value: item.value || "",
    accent: item.accent || null,
    html: item.key === "record" ? recordPlain(item) : PLACE_PLAIN[item.key] ? hazardPlain(item) : item.key === "rainband" ? rainbandPlain(item) : esc(item.conclusion || item.value || ""),
  }));
}

// 土地の高さの文（判定は付けない。色は ground の行の verdict から取る）。
function terrainLine() {
  const reading = S.place?.location?.reading || {};
  if (reading.basin) return { text: "周りより低い凹み" };
  const high = reading.high_directions || [];
  if (high.length) return { text: `${high.join("・")}が高い` };
  const points = reading.elevation?.points || [];
  if (points.length >= 5) return { text: "周りより少し高い" };
  return { text: "読めず" };
}

// ---- 建物名から Web で階数を探す（Claude、2026-11-05） ----
// 押したときだけ、建物名と所在地を Anthropic の API に送り、Web を検索する。答えは出典つきの候補で、人が「この値を使う」を押すまで使わない。
function factsBox() {
  const name = S.query && !/[都道府県市区町村]\S*[0-9０-９一二三四五六七八九十]/.test(S.query) ? S.query : "";
  let result = "";
  if (S.factsBusy) result = busyBox(BUSY_WEB);
  else if (S.facts?.found) {
    const f = S.facts.found;
    const floors = [f.floors_above ? `地上${f.floors_above}階` : "", f.floors_below === null ? "地下は書かれていない" : f.floors_below ? `地下${f.floors_below}階` : "地下なし", unitsBuiltWords(f)].filter(Boolean).join("・");
    result = `<div class="facts-found"><p><b>${esc(floors)}</b>${f.building ? `（${esc(f.building)}）` : ""}</p>
      <p class="hint">出典：<a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(f.source_title || f.source_url)}</a>${f.quote ? `「${esc(f.quote)}」` : ""}</p>
      <p class="hint">${esc(S.facts.message)}</p>
      ${S.floorsApplied?.source === "web" ? `<p class="hint">この値を使っています。<button type="button" class="option small" data-act="drop-floors">取り消す</button></p>` : S.floorsApplied ? `<p class="hint">建物名・戸数・築年はこの値を使っています。階数は図面の読み取り（地上${esc(S.own.floors || "?")}階）を優先しています。</p>` : `<button type="button" class="option" data-act="use-facts">この値を使う</button>`}</div>`;
  } else if (S.facts) result = `<p class="hint">${esc(S.facts.message)}</p>`;
  // 住所から建物が見つからなかったときは、建物名の欄を最初から開いておく（折りたたみに気づかれないため。2026-11-07・16回目）。
  const openNow = S.facts || S.factsBusy || (S.at && !S.at.busy && (!S.at.found || S.at.answer === "no"));
  return `<details class="facts"${openNow ? " open" : ""}><summary>建物名から階数を探す</summary>
    <label class="facts-name">建物名<input id="facts-name" type="text" autocomplete="off" value="${esc(name)}" placeholder="〇〇マンション"></label>
    <button type="button" class="option" data-act="facts"${S.factsBusy ? " disabled" : ""}>Web で階数を探す</button>
    <p class="hint">押すと、建物名と所在地から階数の公表情報を検索します（※検索には Anthropic API を使用します）。</p>
    ${result}
  </details>`;
}

async function findFacts(given) {
  const name = (given || document.getElementById("facts-name")?.value || "").trim();
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
    // 見つかったら、人に押させずに使う（2026-11-06 本人の指示・7回目）。出典は画面に出し、取り消せる。
    if (S.facts?.found) {
      applyFloors(S.facts.found.floors_above, S.facts.found.floors_below, "web");
      adoptUnits(S.facts.found);
      adoptHints(S.facts.found);
    }
  } catch (error) {
    S.facts = { found: null, message: error.message };
  } finally {
    S.factsBusy = false;
    S.query = name;
    render();
  }
  // 建物名で見つからなかったときは、住所からの「この建物ですか？」に回す（画面1に何も出ないままにしない。2026-11-07・16回目）。
  if (!S.facts?.found && S.place && !S.sampleId && !S.at) await findBuildingAt();
}

// 読み込み中の表示：何をしている最中か一目で分かる青枠の箱（回るアイコンつき。2026-11-07・21回目）。
function busyBox(text) {
  return `<div class="busy-box" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span><b>${esc(text)}</b></div>`;
}
const BUSY_WEB = "いまWebの公開情報から建物の階数・戸数・築年を探しています…";
const BUSY_PLAN = "図面・写真から設備の位置と階数を読み取っています…";
const BUSY_REPORT = "書類の文から設備の記載を読み取っています…";
const BUSY_PLACE = "この場所のハザードマップと地形を調べています…";
const BUSY_SEARCH = "住所と建物を調べています…";

// Web で読めた総戸数・築年と、設備の手がかり（表示だけ。判定には使わない）。
function unitsBuiltWords(f) {
  const parking = f?.parking ? `駐車場 ${f.parking}` : "";
  const basementParking = f?.basement_parking === true ? "地下駐車場あり" : f?.basement_parking === false ? "地下駐車場なし" : "";
  const water = f?.water_supply ? `給水 ${f.water_supply}` : "";
  return [f?.units ? `${f.units}戸` : "", f?.built_year ? `${f.built_year}年築` : "", parking, basementParking, water].filter(Boolean).join("・");
}

// 物件概要に「地下駐車場」などの明記があるときだけ、図面がない人の「地下スロープがあるか」の手がかりに入れる（見たことと同じ扱い。確定にはしない。取り消すで戻る）。
function adoptHints(f) {
  if (f?.basement_parking !== true || S.obs.slope) return;
  S.obs.slope = "yes";
  S.hintsFrom = "web";
}

// Web で読めた総戸数を、費用の1戸あたりに使う（手で入れた戸数は上書きしない。取り消すで戻る。2026-11-07・19回目）。
function adoptUnits(f) {
  if (!f?.units || S.unitsFrom === "user") return;
  S.units = f.units;
  S.unitsFrom = "web";
}

// 候補を使う：地上の階数を「何階建て」に、地下の階数を「地下は ある／ない」に入れる（地下が書かれていなければ変えない）。
// 階数と地下の有無を、建物の形（地下あり → 地下の機械室・高圧受電）と①②③の初期値に反映する（2026-11-06 本人の指示・7回目）。
// Web の検索結果でも、図面の読み取りでも同じ。人が選んだ答えは上書きしない。
function applyFloors(above, below, source) {
  if (above) S.own.floors = String(above);
  // 分かるのは階数と地下の有無だけ。機械室の階と受電の方式は、画面2で管理会社が図面で確かめる（決め打ちしない。2026-11-07）。
  if (below !== null && below !== undefined) S.own.basement = below > 0 ? "yes" : "no";
  S.floorsApplied = { source, set: [], extra: [], hv: false };
  if (S.building) loadBuilding().then(render);
}

function useFacts() {
  const f = S.facts?.found;
  if (!f) return;
  applyFloors(f.floors_above, f.floors_below, "web");
  adoptUnits(f);
  adoptHints(f);
  render();
}

function dropFloors() {
  const applied = S.floorsApplied || { set: [] };
  (applied.set || []).forEach((kind) => delete S.choices[kind]);
  if ((applied.set || []).includes("tr")) delete S.extra.tr;
  (applied.extra || []).forEach((key) => delete S.extra[key]);
  if (applied.hv) delete S.extra.hv;
  S.own = { floors: "", basement: "unknown" };
  S.facts = null;
  if (S.at) S.at.answer = "";
  if (S.unitsFrom === "web") {
    S.units = "";
    S.unitsFrom = "";
  }
  if (S.hintsFrom === "web") {
    delete S.obs.slope;
    S.hintsFrom = "";
  }
  S.floorsApplied = null;
  if (S.building) loadBuilding().then(render);
  else render();
}

// 検索欄の文字が住所ではなく建物名らしいか（丁目・番地の数字がない）。
function looksLikeName(q) {
  return Boolean(q) && !/[0-9０-９一二三四五六七八九十]+\s*(丁目|番|号|-|－)/.test(q) && !/^〒?\s*[0-9０-９]{3}/.test(q) && q.replace(/[都道府県市区町村]/g, "").length >= 3;
}

// 画面1：建物名で検索したとき、Web で見つけた階数を使っていることを1行で言う（取り消せる）。
function factsLine() {
  if (S.factsBusy) return busyBox(BUSY_WEB);
  const f = S.facts?.found;
  if (!f || S.floorsApplied?.source !== "web") return "";
  const floors = [f.floors_above ? `地上${f.floors_above}階` : "", f.floors_below ? `地下${f.floors_below}階` : f.floors_below === 0 ? "地下なし" : "", unitsBuiltWords(f)].filter(Boolean).join("・");
  return `<p class="hint facts-line"><b>${esc(floors)}</b>（<a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(f.source_title || "出典")}</a>）。${f.units && S.unitsFrom === "web" ? "戸数は費用の1戸あたりに使います（判定には使いません）。" : ""}機械室の階と受電の方式は、次の画面で確かめます。<button type="button" class="option small" data-act="drop-floors">取り消す</button></p>`;
}

// 自分の建物だけ、住民が外から答えられる2つを聞く（分からなくても進める）。
// withBasement：図面がないときだけ「地下はある／ない」を聞く（図面があれば①②③の答えと重複するため）。
function ownQuestions(withBasement = true) {
  const chips = [["yes", "ある"], ["no", "ない"], ["unknown", "分からない"]]
    .map(([key, word]) => `<button type="button" class="option${S.own.basement === key ? " chosen" : ""}" data-own="${key}" aria-pressed="${S.own.basement === key}">${word}</button>`)
    .join("");
  return `<div class="own">
    <p class="own-head">あなたの建物（分からなくても進めます）</p>
    <label class="floor">何階建て<input id="own-floors" type="number" inputmode="numeric" min="1" max="80" value="${esc(S.own.floors)}" placeholder="例 11">階建て</label>
    ${withBasement ? `<div class="own-row"><span>地下は</span><div class="options">${chips}</div></div>` : ""}
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
  // 場所が決まったら、見出し・検索窓・見本・保存の入口は消し、一番上に「選んだ場所と階数」と「別の場所を探す」だけを1行で出す（2026-11-07 本人の指示・14回目）。
  if (S.place) {
    const lines = placeLines();
    const representative = S.place.site.basis === "representative";
    return `<section class="s1">
      <div class="chosen-bar"><p class="place"><b>${esc(S.place.site.label)}</b>${foundBuildingLine() || chosenFloors()}</p><button type="button" class="option small" data-act="re-search">別の場所を探す</button></div>
      <div class="picked">
        ${riskHead(lines)}
        ${buildingAsk()}
        ${terrainFigure(lines)}
        <details class="more"><summary>根拠の数値（判定と出典）</summary>
          <table class="place"><thead><tr><th>項目</th><th>判定</th><th>理由</th></tr></thead><tbody>${lines.map((line) => `<tr class="${line.verdict}"><td>${esc(line.name)}</td><td><i>${line.word}</i></td><td>${line.html}</td></tr>`).join("")}</tbody></table>
          ${rainFactLine(lines)}
          <p class="hint">出典：ハザードマップポータルサイト、国土地理院（標高API・地形分類）を加工。${representative ? "町丁の代表点の値です。" : ""}高さと色は地図のデータの値で、敷地を測ったものではありません。国の地図そのものは <a href="https://disaportal.gsi.go.jp/" target="_blank" rel="noopener">ハザードマップポータルサイト</a> で。</p>
        </details>
        ${placeAid()}
        <label class="floor">住んでいる階<input id="floor" type="number" inputmode="numeric" min="1" max="80" value="${esc(S.floor)}" placeholder="8">階<small>（なくても進めます）</small></label>
        ${S.busy ? busyBox("建物の判定を計算しています…") : ""}
        <button type="button" class="primary" data-act="see"${S.busy ? " disabled" : ""}>この建物の浸水リスクを確認する</button>
      </div>
    </section>`;
  }
  return `<section class="s1">
    ${S.openId ? openBox() : ""}
    <h1 class="title">大雨のとき、<br>あなたのマンションで<br>何が止まるか</h1>
    <form class="find" id="find">
      <input id="q" name="q" type="search" autocomplete="off" placeholder="住所かマンション名" aria-label="住所・マンション名・郵便番号">
      <button type="submit">探す</button>
    </form>
    ${S.searching ? busyBox(BUSY_SEARCH) : S.busy ? busyBox(BUSY_PLACE) : ""}
    ${S.error ? `<p class="error" role="alert">${esc(S.error)}</p>` : ""}
    ${S.message ? `<p class="hint">${esc(S.message)}</p>` : ""}
    ${candidates ? `<div class="candidates">${candidates}</div>` : ""}
    <p class="or">または、見本（架空の建物）で試す</p>
    <div class="samples">${samples}</div>
    ${S.openId ? "" : openBox()}
  </section>`;
}

// 住所で選んだとき：その住所の建物名と階数を Web で探し、「この建物ですか？」と1行で聞く（2026-11-07 本人の指示・15回目）。
// 「はい」で階数と地下の有無を入れる（factsLine に出典つきで出る。取り消せる）。「違う」か見つからないときは、その場で建物名か階数を入れる欄を出す。
async function findBuildingAt() {
  if (!S.place || S.sampleId) return;
  S.at = { busy: true, found: null, message: "", answer: "" };
  render();
  try {
    const got = await postJSON("/api/building-at", { address: S.place.site.label });
    S.at = { busy: false, found: got.found || null, message: got.message || "", answer: "" };
    // 見つかっても勝手に使わず、「この建物ですか？」で「はい」を押してから反映する（2026-11-07・25回目。22回目の自動反映を本人の指示で戻した）。
  } catch (error) {
    S.at = { busy: false, found: null, message: error.message, answer: "" };
  }
  render();
}

function answerBuilding(answer) {
  if (!S.at) return;
  S.at.answer = answer;
  if (answer === "yes" && S.at.found) {
    S.facts = { found: S.at.found, message: S.at.message };
    S.query = S.at.found.building || S.query;
    applyFloors(S.at.found.floors_above, S.at.found.floors_below, "web");
    adoptUnits(S.at.found);
    adoptHints(S.at.found);
  }
  render();
}

// 建物の行の下：探している間の表示、見つからなかったときの案内と「建物名・階数を入力」、「修正」を押したときの入力欄。
function buildingAsk() {
  if (S.sampleId) return "";
  if (S.at?.busy) return busyBox("いまWebの公開情報から、この住所の建物名・階数・戸数を探しています…");
  const applied = S.floorsApplied?.source === "web" && S.facts?.found;
  const panel = S.fixOpen ? `<div class="ask-bldg none">${applied ? `<p class="hint">Web の候補が違うときは、下に入れ直すか<button type="button" class="option small" data-act="drop-floors">候補を取り消す</button></p>` : ""}${ownQuestions(true)}</div>` : "";
  if (applied) return panel;
  if (S.at?.found && S.at.answer !== "yes") {
    const f = S.at.found;
    const floors = [f.floors_above ? `地上${f.floors_above}階` : "", f.floors_below ? `地下${f.floors_below}階` : f.floors_below === 0 ? "地下なし" : "", unitsBuiltWords(f)].filter(Boolean).join("・");
    const question = `<p class="ask-q">この建物ですか？</p>
      <p class="ask-found"><b>${esc(f.building || "（名前なし）")}</b>${floors ? `　${esc(floors)}` : ""}　<a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(f.source_title || "出典")}</a></p>
      <div class="options big"><button type="button" class="option chosen" data-at="yes">はい、この建物です</button><button type="button" class="option" data-at="no">違う</button></div>`;
    if (S.at.answer === "no") return `<div class="ask-bldg"><p class="hint">候補は使いません。建物名と階数を入れてください。</p>${ownQuestions(true)}</div>`;
    // ページの一部ではなく、一番前の窓で聞く（2026-11-07・26回目）。Esc と「違う」で閉じて入力欄へ。
    return `<div class="modal-back" data-act="modal-no"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="ask-q">${question.replace('class="ask-q"', 'class="ask-q" id="ask-q"')}<p class="hint">「はい」で階数・戸数・築年をこの建物の値として使います。違うときは建物名と階数を自分で入れます。</p></div></div>`;
  }
  if (S.at && !S.at.found) {
    return `<div class="ask-bldg none"><p class="hint">${esc(S.at.message || "この住所の建物名と階数は見つかりませんでした。")}${S.fixOpen ? "" : `<button type="button" class="option small" data-act="fix-building">建物名・階数を入力</button>`}</p>${S.fixOpen ? ownQuestions(true) : ""}</div>`;
  }
  return panel;
}

// 上の1行に添える、Web で見つけた建物の名前・階数・戸数・築年・出典（自動で反映したもの。「修正」で入れ直せる）。
function foundBuildingLine() {
  const f = S.facts?.found;
  if (S.sampleId || !f || !S.floorsApplied) return "";
  // 階数は図面の読み取りが入ればそちら（S.own）を優先して見せる。戸数・築年は Web の値のまま。
  const fromDrawing = S.floorsApplied.source !== "web";
  const above = fromDrawing ? Number(S.own.floors) || f.floors_above : f.floors_above;
  const below = fromDrawing ? (S.own.basement === "yes" ? "地下あり" : S.own.basement === "no" ? "地下なし" : "") : f.floors_below ? `地下${f.floors_below}階` : f.floors_below === 0 ? "地下なし" : "";
  const floors = [above ? `地上${above}階${fromDrawing ? "（図面）" : ""}` : "", below, unitsBuiltWords(f)].filter(Boolean).join("・");
  return `<span class="found-bldg"><b>${esc(f.building || "")}</b>${floors ? `・${esc(floors)}` : ""}（<a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(f.source_title || "出典")}</a>）<button type="button" class="option small" data-act="fix-building">修正</button></span>`;
}

// 場所が決まったあと：検索で一緒に読めた階数・戸数があればそれを使い、なければ建物名から1回だけ探す。住所だけなら「この建物ですか？」。
function afterPlace(q) {
  if (!S.place || S.sampleId) return;
  if (S.searchFacts) {
    S.facts = { found: S.searchFacts, message: "Webの公表情報から見つかった候補です。出典を見て、違えば取り消してください。" };
    applyFloors(S.searchFacts.floors_above, S.searchFacts.floors_below, "web");
    adoptUnits(S.searchFacts);
    adoptHints(S.searchFacts);
    render();
    return;
  }
  if (looksLikeName(q)) findFacts(q);
  else findBuildingAt();
}

// 選んだ場所の行に添える、建物名と階数（見本はその見本の名前と階数、自分の建物は分かっている階数だけ）。
function chosenFloors() {
  if (S.sampleId) {
    const point = S.points.find((pt) => pt.sample === S.sampleId);
    if (!point) return "";
    const name = point.label.replace(/^見本/, "").split("／")[0].replace("（架空）", "").trim();
    return `<span>見本${esc(name)}${point.floors ? `・地上${esc(point.floors)}階` : ""}</span>`;
  }
  const above = Number(S.own.floors);
  if (!above) return "";
  const name = foundName() ? `${esc(foundName())}・` : "";
  return `<span>${name}地上${above}階${S.own.basement === "yes" ? "・地下あり" : S.own.basement === "no" ? "・地下なし" : ""}</span>`;
}

// 「別の場所を探す」：場所と、それに結びついた答え・図面・候補を全部戻して画面1の入力に戻る。
function resetPlace() {
  stopPlay(false);
  Object.assign(S, {
    place: null, building: null, sampleId: null, demoId: null, candidates: [], message: "", error: "",
    facts: null, factsBusy: false, at: null, query: "", floorsApplied: null, own: { floors: "", basement: "unknown" },
    choices: {}, extra: {}, read: null, drawingImages: [], obs: {}, drawing: null, exp: "", statements: [], hvSaid: "",
    reached: 1, screen: 1, measure: "none", play: 0, sendMsg: "", sendText: "",
  });
  render();
  window.scrollTo({ top: 0 });
}

// 折りたたみの中に置く、線状降水帯の事実の全文（カードには短い1行だけ）。
function rainFactLine(lines) {
  const rain = (lines || []).find((line) => line.key === "rainband");
  if (!rain?.accent) return "";
  return `<p class="hint rain-fact">台風・大雨（線状降水帯）の事実：${esc(rain.accent.fact)}（<a href="${esc(rain.accent.source_url)}" target="_blank" rel="noopener">${esc(rain.accent.source)}</a>）</p>`;
}

// 地図。地理院タイルとハザードマップの色を重ね、東西南北50mの標高を置く。高い方から建物へ水の矢印を引く。



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
    // 約2か月〜本復旧は、この建物の同じ設備の行の目安が出るか消えるか（目安なしのとき）を表面で見せる（what-019、what-020）。
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
  return `<ol class="timeline">${items}</ol>${notes[0] ? `<p class="hint">${esc(notes[0])}</p>` : ""}`;
}

// 目安の文があるマスか（「—」「止まる想定」「目安なし」は目安ではない）。
function hasGuide(cell) {
  return Boolean(cell) && cell !== "—" && cell !== "止まる想定" && !cell.startsWith("目安なし");
}

// 太字に読む行は、対策を変えても同じ行にする（what-020：変わるのは目安が出るか出ないかだけ。別の行の目安に入れ替えると「早く戻る」と読めるため）。
// 行は、止水板だけのときに目安が出ている、この建物の設備の行（高圧受変電設備、給水の盤の順）。ほかの建物の例は使わない。
function ownGuide(index) {
  const base = S.building?.scenarios?.["3:none"]?.table || [];
  const anchor = ["hv", "water"].find((key) => hasGuide(base.find((item) => item.key === key)?.cells?.[index]));
  if (!anchor) return "";
  const cell = (scenario(3)?.table || []).find((item) => item.key === anchor)?.cells?.[index];
  // 対策で目安が消えたら、この行の太字は出さない（目安なしの印は出さない。2026-11-06 本人の指示）。
  return hasGuide(cell) ? cell : "";
}

// 画面3の見出し：今の対策で、③まで水が来たときに何が止まるか（2026-11-06 本人の指示）。
function measureHeadline() {
  const name = (S.building?.model_measures || []).find((m) => m.key === S.measure)?.short || "対策なし";
  const stopped = TILES.filter((tile) => serviceState(3, SERVICE_OF_TILE[tile.key]) === "stopped").map((tile) => tile.label);
  if (!stopped.length) return `${name}：止まらない想定（稼働）`;
  return `${name}：${stopped.join("・")}が止まる想定`;
}

// 浸水の模式：操作（再生・水位・対策）＋図（平面図／断面図／あなたの図面のタブ）＋暮らしの3札を1画面に収める（2026-11-06 本人の指示・8回目）。
const SIM_LEVELS = { 1: "① 道路", 2: "② 一番低い床", 3: "③ 機械の部屋" };
// 水位ごとに何が起きるか（高さは一般的な目安。GAUGE と同じ文）。
const LEVEL_WHAT = { 1: "道路が冠水。壁の穴・スロープ・扉から水が入り始める", 2: "一番低い床に20〜30cm。床置きの盤・EVピットが浸かる", 3: "床から50cm。盤・高圧受変電設備・借室の下端まで。水も電気も止まる" };
const LEVEL_TINY = { 1: "道路が冠水", 2: "床に20〜30cm", 3: "床から50cm" };

// 水位のゲージ（2026-11-07・24回目：①②③のボタンを、左から右へ水が上がるゲージと ◀ ▶ に置き換え）。
function waterGauge(playing) {
  const lv = S.play;
  const segs = [1, 2, 3].map((n) => `<button type="button" class="seg s${n}${lv >= n ? " filled" : ""}${lv === n ? " now" : ""}" data-level="${n}" aria-pressed="${lv === n}"><span class="seg-no">${LEVEL_MARK[n]} ${SIM_LEVELS[n].slice(2)}</span><span class="seg-name">${LEVEL_TINY[n]}</span></button>`).join("");
  const stopped = S.measure !== "none" && lv > 0;
  const what = lv ? `<p class="level-what${stopped ? " stopped" : ""}"><b>水位${LEVEL_MARK[lv]}</b>${esc(LEVEL_WHAT[lv])}${stopped ? "　→ <b>止水板と穴埋めで、中には入らない想定</b>" : ""}</p>` : "";
  return `<div class="water-gauge" role="group" aria-label="水がどこまで来るか">
    <span class="sim-label">水がどこまで<br>来るか</span>
    <button type="button" class="arrow" data-act="level-down" aria-label="水位を下げる"${lv <= 1 ? " disabled" : ""}>◀</button>
    <div class="segs">${segs}</div>
    <button type="button" class="arrow" data-act="level-up" aria-label="水位を上げる"${lv >= 3 ? " disabled" : ""}>▶</button>
  </div>${what}`;
}

function simBox(playing, shown) {
  const figs = [["plan", "▦ 平面図（上から）"], ["section", "▤ 断面図（横から）"], ...(S.drawingImages?.length ? [["drawing", "🖼 アップロード図面"]] : [])];
  const fig = figs.some(([key]) => key === S.fig) ? S.fig : "plan";
  const tabs = figs.map(([key, word]) => `<button type="button" class="option${fig === key ? " chosen" : ""}" data-fig="${key}" aria-pressed="${fig === key}">${word}</button>`).join("");
  const figure = fig === "section" ? sectionFigure(S.play) : fig === "drawing" ? drawingFigure(true) : plan({ level: S.play });
  const allSafe = TILES.every((tile) => serviceState(3, SERVICE_OF_TILE[tile.key]) !== "stopped");
  const impactLine = allSafe
    ? `<p class="impact-banner safe">✓ 選択中の対策により、水位③でも機械室の浸水・長期停止を回避できる想定です</p>`
    : `<p class="impact-banner risk">⚠ ${esc(S.building?.damage_line || "")}</p>`;
  // 動線は 1 シミュレーションを始める → 2 対策を切り替えて比べる → 3 図を切り替える（2026-11-07・26回目：手が動く順に番号を振る）。
  const cue = S.play === 3 && !playing && S.measure === "none" ? `<p class="next-cue">次は <b>2 対策を切り替えて比べる</b> を押して、どこで水が止まるかを見てください ↑</p>` : "";
  return `<div class="sim">
    <div class="sim-step">
      <span class="step-no">1</span>
      <button type="button" class="sim-start${playing ? " playing" : ""}" data-act="play">${playing ? "❚❚ シミュレーションを止める" : "▶ 浸水シミュレーションを始める"}</button>
      <span class="step-note">道路 → 一番低い床 → 機械の部屋の順に水が上がります（速さの予測ではなく順番の模式）</span>
    </div>
    ${waterGauge(playing)}
    <div class="sim-step"><span class="step-no">2</span>${measureChips()}</div>
    <div class="sim-step"><span class="step-no">3</span><div class="fig-switch"><span class="sim-label">図を切り替える</span><div class="options big fig-options">${tabs}</div></div></div>
    <div class="plan sim-fig">${figure}</div>
    ${fig === "drawing" ? "" : `<p class="fig-legend"><span class="lg water">青の面＝水が入る範囲（②床に20〜30cm、③床から50cm）</span><span class="lg arrow">矢印＝水の入り道</span><span class="lg badge">赤い札＝止まる設備</span></p>`}
    ${stopList()}
    ${S.building?.sample?.custom && fig !== "drawing" ? `<p class="hint fig-note">${borrowedNote()}</p>` : ""}
    ${lifeChips(S.play)}
    ${impactLine}
    ${cue}
    ${allSafe ? "" : matsudoLine("hint case-line")}
  </div>`;
}

// 対策で水を止めた場所を、図の印と同じ言葉で1行に（2026-11-07・24回目：対策後にどこで防いでいるかが分からないという指摘）。
function stopList() {
  if (S.measure === "none" || !S.play) return "";
  const shape = planShape(S.building.sample);
  const spots = [];
  if (shape.slope) spots.push("地下スロープの入口に止水板");
  spots.push("出入口・通用口に止水板", "ケーブル・配管の壁の穴を埋める");
  if (S.measure === "full") spots.push("床置きの盤を高くする");
  return `<p class="stop-list"><b>✔ 止めた所：</b>${spots.map((s) => `<span>${esc(s)}</span>`).join("")}</p>`;
}

function screenTwo() {
  const b = S.building;
  const playing = Boolean(S.timer);
  const shown = S.play > 0;
  return `<section class="s2">
    <p class="kicker">${esc(kicker())}</p>
    <h1 class="title">${esc(measureHeadline())}</h1>
    <p class="lead-why">${esc(S.measure === "none" ? titleLine() : MEASURE_GAIN[S.measure] || "")}</p>
    ${simBox(playing, shown)}
    ${criticalBox()}
    <details class="more"><summary>浸水から復旧までの時系列（当日〜数か月）を見る</summary>${timeline()}</details>
    <button type="button" class="primary" data-act="to4">理事会提案資料（A4・1枚）を作成する</button>
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

// 判定の行の説明を1行に詰める（最初の文だけ、（ ）の中は落とす）。
function shortSummary(text) {
  const head = String(text || "").split("。")[0].replace(/（[^）]*）/g, "");
  return head.length > 26 ? `${head.slice(0, 25)}…` : head;
}

// 答えごとの一行（判定の色はサーバーのまま）。
// 答えた瞬間に出す一行（部屋ごと）。色と「止まるおそれ／未確認／問題なし」の語はサーバーの判定のまま（画面で判定を作らない）。
const CHOICE_RESULT = {
  pump: { basement: "浸水すると全戸で断水", ground: "浸水するかは給水ポンプ制御盤の下端の高さ次第", upper: "浸水の想定より上の階", absent: "図面にないと確認" },
  elec: { basement: "浸水すると共用部が停電し、給水ポンプも止まる", ground: "浸水するかは盤の下端の高さ次第", upper: "浸水の想定より上の階", absent: "図面にないと確認" },
  tr: { basement: "浸水すると各戸の電気が止まる", ground: "浸水するかは変圧器の高さ次第", upper: "各戸の電気は止まらない想定", absent: "各戸へ電気を送る設備の位置は東京電力に照会" },
};
CHOICE_RESULT.panel_room = CHOICE_RESULT.elec;

// 進み具合：残りの数と、3つの部屋の答え（答えるたび色が変わる）。
function progressLine(b, count) {
  const parts = QUESTIONS.map((q) => {
    const kind = q.kind(b);
    const chosen = S.choices[kind];
    return `<span class="prog ${chosen ? verdict(q.row) : "open"}">${q.no}${ROOM_ASK_SHORT[kind]}<b>${chosen ? OPTION_WORDS[chosen] : "未回答"}</b></span>`;
  }).join("");
  return `<div class="progress"><span class="count" id="count"><span>残り</span><b>${count}</b></span>${parts}</div>`;
}

function screenThree() {
  // 2026-11-07・13回目：一文 → 進み具合 → 図面を入れる箱 → 3つの問い（大きな押す面、答えた瞬間の一行）→ 図 → 最優先の対策の1行。
  const b = S.building;
  const count = openCount();
  const cards = QUESTIONS.map((q) => {
    const kind = q.kind(b);
    const item = row(q.row);
    const v = verdict(q.row);
    const chosen = S.choices[kind] || "none";
    // 高圧か低圧かの問い（保安会社のシール・高圧の表示）は、見出しの問いと混ぜず、別の札にする（2026-11-05 本人の指摘⑤）。
    const options = `<div class="options big">${[...q.options, "none"]
          .map((o) => `<button type="button" class="option${chosen === o ? " chosen" : ""}" data-kind="${kind}" data-choice="${o}" aria-pressed="${chosen === o}">${OPTION_WORDS[o]}</button>`)
          .join("")}</div>`;
    const engineer = q.row === "power" && S.extra.hv === "yes" ? `<p class="hint">高圧（保安会社の契約）：あり　<button type="button" class="option small" data-hv="none">取り消す</button></p>` : "";
    const before = q.row === "power" && b.sample.engineer_unsure ? `<div class="qcard engineer">${engineerQuestion()}</div>` : "";
    // 答えた瞬間に「→ 地下：浸水すると全戸で断水（止まるおそれ）」と出す。語と色はサーバーの判定のまま。
    const result = chosen !== "none"
      ? `<p class="qresult ${v} answered">→ ${OPTION_WORDS[chosen]}：${esc(CHOICE_RESULT[kind]?.[chosen] || "")}<b>（${LOOK[v].word}）</b></p>`
      : `<p class="qresult ${v}"><b>${LOOK[v].word}</b><small>${esc(item ? shortSummary(item.summary) : "")}</small></p>`;
    return `${before}<div class="qcard ${v}">
      <p class="qtitle"><span class="no">${q.no}</span>${esc(q.title)}</p>
      ${engineer}${options}
      ${result}
    </div>`;
  }).join("");
  // 自分の図面があれば見本の平面図は出さない。見本を出すときも貼りつけず（sticky なし）、高さを抑える。
  // 平面図を入れたときはその画像だけ。断面図・系統図・外観写真だけのときは、小さく出して見本の平面図も残す（部屋のイメージのため。2026-11-07・20回目）。
  const images = S.drawingImages || [];
  const own = images.length > 0;
  const hasPlanImage = images.some((img) => img.kind === "plan" || img.kind === "site_plan");
  const samplePlan = hasDrawing() ? `<div class="plan check-plan">${plan({ pins: pinsOf(steps()), small: true })}</div>${b.sample.custom ? `<p class="hint">${borrowedNote()}</p>` : ""}` : "";
  const figure = own ? (hasPlanImage ? drawingFigure() : drawingFigure(true) + samplePlan) : samplePlan;
  return `<section class="s3">
    <p class="kicker">${esc(kicker())}</p>
    <h1 class="title">${hasDrawing() ? CHECK_LEAD : CHECK_LEAD_NO_DRAWING}</h1>
    ${hasDrawing() ? progressLine(b, count) : ""}
    ${hasDrawing() && count ? `<p class="hint">「未確認」は危険という意味ではありません。竣工図で確認した内容を反映すると判定が更新されます。</p>` : ""}
    ${drawingQuestion()}
    ${hasDrawing() ? readCard() + reportBox() + cards : observeCards()}
    ${figure}
    ${S.sampleId ? "" : hasDrawing() ? `<details class="more"><summary>建物のこと（階数・この辺りの経験）</summary>${ownQuestions(!hasDrawing())}${S.sampleId ? "" : experienceQuestion()}</details>` : `<div class="own-open">${ownQuestions(true)}${experienceQuestion()}</div>`}
    ${criticalPreview()}
    <button type="button" class="primary" data-act="to3">浸水の経路と止まる設備を見る</button>
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

// 図面は「ない」と答えるまで「ある」扱い（最初から写真の読み取りと①②③を出す。2026-11-06 本人の指示）。
function hasDrawing() {
  return S.drawing !== "no";
}

function drawingQuestion() {
  const chosen = S.drawing || "yes";
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
  return `<p class="hint observe-note">竣工図がなくても進められます。外観から分かることを入力すると、管理会社への依頼メモに「住民が確認したこと」として載ります。色は、図面で確かめるまで変えません。</p>${cards}`;
}

// 住民が見たことを、サーバーの聞き取り（statements）の文にする。
function obsStatements() {
  const seen = OBSERVE.map((q) => q.says[S.obs[q.key]]).filter(Boolean);
  if (S.hvSaid === "no") seen.push("電気室の扉や盤に、保安会社の連絡先シールや高圧の表示が見当たらなかった");
  return seen.map((text) => `住民が見たこと：${text}`);
}

// ②の前に聞く、高圧か低圧か（2026-11-06 本人の指示：電気室に貼ってあるのは保安会社のシールと高圧の表示なので、それを聞く）。
// 「ない」では判定を変えない。受電設備なしと読むのは、書類に「受電設備なし」と「選任なし」の両方があるときだけ（hantei-030、how-017）。
function engineerQuestion() {
  const said = S.hvSaid || "";
  const chip = (key, word) => `<button type="button" class="option${said === key ? " chosen" : ""}" data-hv="${key}" aria-pressed="${said === key}">${word}</button>`;
  return `<p class="qtitle">電気室の扉や盤に、保安会社（電気保安協会など）の連絡先シールか「高圧」の表示はありますか？</p>
    <p class="qsub">年1回の停電点検がある建物も「ある」。高圧で受ける建物は保安会社が点検し、浸水の日の連絡先が変わります。</p>
    <div class="options">${chip("yes", "ある")}${chip("no", "ない")}${chip("none", "分からない")}</div>`;
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
const READ_NOTICE = "選んだ図面から部屋や設備の候補を読み取ります（※解析には Anthropic API を使用します。キーがないときは送らず、見本の答えを出します）。";

function readCard() {
  // 選ぶ前は説明を1行だけ。読んだあとは候補と「すべて入れる」（2026-11-07・13回目）。
  const before = !S.read && !S.busy;
  return `<div class="qcard read">
      <p class="qtitle">竣工図・写真からの自動読み取り</p>
      <div class="options big">
        <label class="option file">図面の写真・PDFを選ぶ<input type="file" id="plan-file" accept="image/*,application/pdf" multiple></label>
        ${S.sampleId ? `<button type="button" class="option" data-act="read-sample">見本の図面で試す</button>` : ""}
      </div>
      ${before ? `<p class="hint">平面図・断面図・配置図・設備図・外構図・外観写真。複数可。Cmd+V の貼り付けでも読めます。${READ_NOTICE}</p>` : ""}
      ${readResult()}
    </div>`;
}

// ---- 点検報告書・管理資料の文から読む（/api/report。2026-11-07・19回目で画面に戻した）----
// 読めた語→項目→効き方を見せ、人が「答えに入れる」を押したときだけ答え（S.extra）と書類の印（document_read）に入れる。
const REPORT_ANSWER_WORDS = { hv: { no: "受電設備なし（書類に明記）" }, feed: { underground: "引込み 地中", overhead: "引込み 架空" }, panel_foot: { floor: "給水ポンプ制御盤 床置き", raised: "給水ポンプ制御盤 壁掛け・架台" }, rooms_floor: { basement: "受電設備は地下（書類）" }, damp: { yes: "湿気・漏水の指摘あり", no: "指摘なし" }, tank: { yes: "貯留槽あり" }, sealed: { yes: "止水バルブあり" } };

async function readReport(text) {
  const body = String(text || "").trim();
  if (!body) {
    S.report = { message: "文を貼り付けてください。", findings: [], answers: {} };
    render();
    return;
  }
  S.reportBusy = true;
  render();
  try {
    S.report = await postJSON("/api/report", { text: body });
    S.reportText = body;
  } catch (error) {
    S.report = { message: error.message, findings: [], answers: {} };
  } finally {
    S.reportBusy = false;
    render();
  }
}

async function readSampleReport() {
  if (!S.sampleId) return;
  const text = await (await fetch(`/samples/report_${S.sampleId}.txt`)).text();
  await readReport(text);
}

async function applyReport() {
  const r = S.report;
  if (!r) return;
  const keys = Object.keys(r.answers || {});
  keys.forEach((key) => {
    S.extra[key] = r.answers[key];
  });
  S.reportApplied = keys;
  S.documentRead = Boolean(r.basement_power);
  await loadBuilding();
  render();
}

async function dropReport() {
  (S.reportApplied || []).forEach((key) => delete S.extra[key]);
  S.reportApplied = null;
  S.documentRead = false;
  await loadBuilding();
  render();
}

function reportBox() {
  const r = S.report;
  let result = "";
  if (S.reportBusy) result = busyBox(BUSY_REPORT);
  else if (r) {
    const findings = (r.findings || []).map((f) => `<li><b>${esc(f.word)}</b> → ${esc(f.item)}：${esc(f.effect)}</li>`).join("");
    const answerWords = Object.entries(r.answers || {}).map(([key, value]) => REPORT_ANSWER_WORDS[key]?.[String(value)]).filter(Boolean);
    const applyable = answerWords.length || r.basement_power;
    const action = S.reportApplied
      ? `<p class="auto-applied">書類の記載を反映しました。<button type="button" class="option small" data-act="report-drop">反映を取り消す</button></p>`
      : applyable ? `<div class="options big"><button type="button" class="option chosen" data-act="report-apply">反映する（${answerWords.length + (r.basement_power ? 1 : 0)}件）</button></div>` : "";
    result = `<p class="hint">${esc(r.message || "")}</p>${findings ? `<ul class="proposals">${findings}</ul>` : ""}${answerWords.length ? `<p class="hint">反映できる項目：${esc(answerWords.join("／"))}${r.basement_power ? "／受電設備は地下（書類で確認）" : ""}</p>` : ""}${action}`;
  }
  return `<details class="more report-fold"><summary>点検報告書・管理資料から読み取る</summary>
    <p class="hint">点検報告書や管理会社の資料の文を貼り付けると、受電設備の階、引込み、盤の置き方、指摘事項などの記載を拾います。反映するかは利用者が決めます。</p>
    <textarea id="report-text" class="copy-area" rows="5" placeholder="例：受電設備：地下1階 受変電室。引込み：地中（高圧）。給水ポンプ制御盤は壁掛け。">${esc(S.reportText || "")}</textarea>
    <div class="options">
      <button type="button" class="option" data-act="report-read"${S.reportBusy ? " disabled" : ""}>文面から読み取る（※Anthropic API を使用します）</button>
      ${S.sampleId ? `<button type="button" class="option" data-act="report-sample">見本の点検報告書で試す</button>` : ""}
    </div>
    ${result}
  </details>`;
}

// 図面から読めた、部屋の階以外の項目（引込み・受電・盤の置き方・放流先・逆止弁・雨水ます・スロープ・換気口・管路口）。
// name は画面の語、words は値の語、answer は答え（S.extra）に入れる組。null は答えには入れない（見せるだけ）。
const FACT_WORDS = {
  feed: { name: "引込み", words: { underground: "地中（ハンドホールから）", overhead: "架空（電柱から）" }, answer: (v) => ["feed", v] },
  hv: { name: "受電", words: { true: "高圧受電（キュービクル）", false: "低圧受電" }, answer: (v) => (v ? ["hv", "yes"] : null) },
  panel_mount: { name: "給水ポンプ制御盤", words: { floor: "床置き", wall: "壁掛け", stand: "架台の上" }, answer: (v) => ["panel_foot", v] },
  drain_outlet: { name: "排水の放流先", words: { sewer: "公共下水道", ditch: "側溝・水路" }, answer: (v) => ["drain", v] },
  check_valve: { name: "逆止弁", words: { true: "あり", false: "なし" }, answer: (v) => ["check_valve", v ? "yes" : "no"] },
  rain_basin: { name: "雨水ます", words: { true: "あり", false: "なし" }, answer: () => null },
  slope: { name: "地下へのスロープ", words: { true: "あり", false: "なし" }, answer: (v) => ["slope", v ? "yes" : "no"] },
  vent: { name: "足元の換気口", words: { true: "あり", false: "なし" }, answer: (v) => ["vent", v ? "yes" : "no"] },
  pipe_opening: { name: "管路口（壁の貫通穴）", words: { true: "あり", false: "なし" }, answer: (v) => ["pipe_opening", v ? "yes" : "no"] },
};
const DRAWING_NAMES = { plan: "平面図", site_plan: "配置図", section: "断面図", elevation: "立面図", electrical: "電気設備図・単線結線図", plumbing: "給排水設備図", exterior: "外構図", photo: "外観写真", other: "図面" };
const ROOM_MARKS = { pump: "①", elec: "②", panel_room: "②", tr: "③" };

// 読めた候補の一覧（部屋の階 → 階数 → そのほかの項目）。applied は、今の答えに入っているか。
function readProposals() {
  const read = S.read;
  if (!read) return [];
  const names = { pump: "給水ポンプ室", elec: "電気室", panel_room: "分電盤室", tr: "借室（東京電力の変圧器室）" };
  const seen = new Set();
  const list = [];
  // 同じ種類の部屋が複数読めたら、問いの名前と同じ語（給水ポンプ室など）を先にする（「受水槽室」が先に出ないように。2026-11-07・15回目）。
  const main = (read.rooms || []).filter((room) => ROOM_MARKS[room.kind]);
  main.sort((p, q) => (p.word === names[p.kind] ? 0 : 1) - (q.word === names[q.kind] ? 0 : 1));
  main.forEach((room) => {
    const choice = floorChoice(room.floor);
    const key = `${room.kind}:${choice || room.floor}`;
    if (seen.has(key)) return;
    seen.add(key);
    const word = room.word && room.word !== names[room.kind] ? `（図面では「${room.word}」）` : "";
    list.push({ id: `room:${room.kind}`, kind: room.kind, choice, name: `${ROOM_MARKS[room.kind]} ${names[room.kind]}`, text: `${room.floor || "階は読めず"}${word}`, applied: Boolean(choice) && S.choices[room.kind] === choice });
  });
  const d = read.drawing;
  if (d && d.floors_above) {
    list.push({ id: "floors", floors: d, name: "階数", text: `地上${d.floors_above}階${d.floors_below ? `・地下${d.floors_below}階` : ""}${d.pit ? "（基礎ピットあり）" : ""}`, applied: S.floorsApplied?.source === "drawing" });
  }
  Object.entries(read.facts || {}).forEach(([key, fact]) => {
    const spec = FACT_WORDS[key];
    if (!spec) return;
    const answer = fact.auto === false ? null : spec.answer(fact.value);
    list.push({ id: `fact:${key}`, key, value: fact.value, answer, name: spec.name, text: `${spec.words[String(fact.value)] || ""}（${DRAWING_NAMES[fact.kind] || "図面"}）`, applied: answer ? S.extra[answer[0]] === answer[1] : null });
  });
  return list;
}

function readResult() {
  if (S.busy && !S.read) return busyBox(BUSY_PLAN);
  if (!S.read) return "";
  const proposals = readProposals();
  const pending = proposals.filter((p) => p.applied === false && (p.choice || p.floors || p.answer));
  const line = (p) => {
    let action = "";
    if (p.applied === true) action = `<span class="applied">✓ 反映済み</span>`;
    else if (p.applied === null) action = `<span class="hint">（参考表示のみ）</span>`;
    else if (p.choice) action = `<button type="button" class="option small" data-kind="${p.kind}" data-choice="${p.choice}">${ROOM_MARKS[p.kind]}に「${OPTION_WORDS[p.choice]}」を反映</button>`;
    else if (p.floors) action = `<button type="button" class="option small" data-act="apply-floors">階数を反映</button>`;
    else if (p.answer) action = `<button type="button" class="option small" data-fact="${p.answer[0]}" data-value="${esc(p.answer[1])}">反映</button>`;
    if (p.choice === null && !p.floors && !p.key) action = `<span class="hint">階が読めません</span>`;
    return `<li><b>${esc(p.name)}</b>：${esc(p.text)}　${action}</li>`;
  };
  // 細かい設備（EPS・PS・MB・受水槽・階段など）は折りたたむ（表面に並べない。2026-11-07・13回目）。
  const others = (S.read.rooms || []).filter((room) => !ROOM_MARKS[room.kind]).map((room) => `<span>${esc(room.word || room.name)}${room.floor ? `（${esc(room.floor)}）` : ""}</span>`);
  const applied = proposals.filter((p) => p.applied === true).length;
  const buttons = pending.length
    ? `<div class="options big"><button type="button" class="option chosen" data-act="apply-all">すべて反映（${pending.length}件）</button></div>`
    : applied ? `<p class="auto-applied">図面から読み取った${applied}件を反映しました。違う項目は下の設問で修正できます。<button type="button" class="option small" data-act="drop-floors">反映を取り消す</button></p>` : "";
  // 自動で入れたときは、サーバーの「ボタンで答えに入れます」の文は出さない。
  const message = S.autoApplied ? String(S.read.message || "").replace(" 部屋は、合っていればボタンで反映します。", "") : S.read.message || "";
  const list = proposals.length ? `<ul class="proposals">${proposals.map(line).join("")}</ul>` : "";
  const othersFold = others.length ? `<details class="more read-more"><summary>ほかに読めた設備（${others.length}件）</summary><p class="read-others">${others.join("")}</p></details>` : "";
  // 全部入ったら、一覧は折りたたみ、緑の1行だけ表に残す（2026-11-07・24回目：文字量の指摘）。
  if (!pending.length && applied) return `${buttons}<details class="more read-more"><summary>読み取った内容を見る（${applied}件）</summary><p class="hint">${esc(message)}</p>${list}</details>${othersFold}`;
  return `<p class="hint">${esc(message)}</p>${list}${buttons}${othersFold}`;
}

// 読めた候補をまとめて答えに入れる（人が押したときだけ。2026-11-07・13回目）。取り消すで全部戻る。
async function applyAllRead() {
  const proposals = readProposals();
  const applied = S.floorsApplied && S.floorsApplied.source === "drawing" ? S.floorsApplied : { source: "drawing", set: [], extra: [], hv: false };
  applied.set = applied.set || [];
  applied.extra = applied.extra || [];
  proposals.forEach((p) => {
    if (p.choice) {
      assignRoom(p.kind, p.choice).forEach((k) => applied.set.push(k));
    } else if (p.floors) {
      if (p.floors.floors_above) S.own.floors = String(p.floors.floors_above);
      if (p.floors.floors_below !== null && p.floors.floors_below !== undefined) S.own.basement = p.floors.floors_below > 0 ? "yes" : "no";
    } else if (p.answer) {
      S.extra[p.answer[0]] = p.answer[1];
      if (p.answer[0] === "hv") applied.hv = true;
      else applied.extra.push(p.answer[0]);
    }
  });
  S.floorsApplied = applied;
  await loadBuilding();
  render();
}

async function setFact(key, value) {
  S.extra[key] = value;
  const applied = S.floorsApplied || { source: "drawing", set: [], extra: [], hv: false };
  applied.extra = applied.extra || [];
  if (key === "hv") applied.hv = true;
  else if (!applied.extra.includes(key)) applied.extra.push(key);
  S.floorsApplied = applied;
  await loadBuilding();
  render();
}

// 地図の下の凡例：数字の意味・矢印の意味・色の深さの帯（サーバーの hazard_legend のまま）。
// 地図に重ねる層（上の深さの札と同じ想定。洪水は想定最大を先に）。なければ色のある層。

// 画面1の①：結論1行＋国の地図2項目＋地形1行（判定表の行から。判定は変えない。2026-11-06 本人の指示・10回目：重複を1か所に）。
function riskWords(mapHit, mapClear, rainHit, rainClear) {
  if (mapHit && rainHit) return [["risk", "浸水リスクあり"], "国が公表する浸水の想定に入り、地形も台風・大雨で浸かりやすい場所です"];
  if (mapHit) return [["risk", "浸水リスクあり"], "国が公表する浸水の想定に入る場所です"];
  // 国の地図が「色なし」か「データなし」かで言い分ける（データなしを色なしと言わない。2026-11-07・15回目）。
  if (rainHit) return [["risk", "浸水リスクあり"], mapClear ? "国の浸水想定に色はありませんが、台風・大雨で浸かりやすい地形です" : "国の浸水想定は確かめられませんが、台風・大雨で浸かりやすい地形です"];
  if (mapClear && rainClear) return [["clear", "国の浸水想定にも、浸かりやすい地形にも該当しません"], "今の根拠では色のない場所（現地は見ていません）"];
  return [["unconfirmed", "浸水リスクは、まだ確かめられていない"], "データの取れていない項目があります"];
}

// A4 の立地は2行だけ（結論と、国の地図×地形の内訳。2026-11-07・24回目）。
function placeTwoLines(lines) {
  const by = Object.fromEntries(lines.map((line) => [line.key, line]));
  const mapRows = ["flood", "surge", "inland"].map((key) => by[key]).filter(Boolean);
  const mapHit = mapRows.some((line) => line.verdict === "risk");
  const mapClear = mapRows.length && mapRows.every((line) => line.verdict === "clear");
  const rain = by.rainband;
  const [head, sub] = riskWords(mapHit, mapClear, rain?.verdict === "risk", rain?.verdict === "clear");
  const word = (line) => !line ? "データなし" : line.verdict === "risk" ? (line.value || "色あり") : line.verdict === "clear" ? "色なし" : "データなし";
  const map = [["川の洪水", by.flood], ["高潮", by.surge], ["内水", by.inland]].map(([name, line]) => `${name}：${word(line)}`).join("／");
  const hits = (rain?.accent?.lines || []).filter((line) => line.hit === true).map((line) => line.name).join("・");
  return `<p class="a4-place-head ${head[0]}"><b>${esc(head[1])}</b>${esc(sub)}</p>
  <p class="a4-place-sub">国の浸水想定：${esc(map)}　×　台風・大雨で浸かりやすい地形：${hits ? `該当（${esc(hits)}）` : rain?.verdict === "clear" ? "該当なし" : "データなし"}</p>`;
}

function riskHead(lines, compact = false) {
  // 画面1の結論は「ハザードマップ（国の地図）× 線状降水帯で浸かる型」の掛け算（2026-11-07 本人の指示）。
  // どちらも事実（国の地図の色・国土地理院の数値・報道の実数）で、当たるかはサーバーの規則（rainband の行）。この画面では言葉を足さない。
  const by = Object.fromEntries(lines.map((line) => [line.key, line]));
  const mapRows = ["flood", "surge", "inland"].map((key) => by[key]).filter(Boolean);
  const mapHit = mapRows.some((line) => line.verdict === "risk");
  const mapClear = mapRows.length && mapRows.every((line) => line.verdict === "clear");
  const rain = by.rainband;
  const rainHit = rain?.verdict === "risk";
  const rainClear = rain?.verdict === "clear";
  const [head, sub] = riskWords(mapHit, mapClear, rainHit, rainClear);
  const mapWord = (line) => {
    if (!line) return "データなし";
    if (line.verdict === "risk") return line.value || line.conclusion || "色あり";
    if (line.verdict === "caution" && /色/.test(line.conclusion || "")) return line.conclusion;
    if (line.verdict === "clear") return "色なし";
    return "データなし";
  };
  const mark = (hit) => hit === true ? `<i class="hit">該当</i>` : hit === false ? `<i class="miss">該当なし</i>` : `<i class="none">データなし</i>`;
  // カードの中は1行ずつ短く（2026-11-07・14回目）。内水の理由・4方向の標高・記事の全文は、折りたたみの表に置く。
  const mapLines = [["川の洪水", by.flood], ["高潮", by.surge], ["内水", by.inland]]
    .map(([name, line]) => {
      const inlandNone = line?.key === "inland" && line.verdict !== "risk" && line.verdict !== "clear";
      return `<li>${name}：${inlandNone ? "国のデータなし" : esc(mapWord(line))}</li>`;
    }).join("");
  const rainLines = (rain?.accent?.lines || []).map((line) => `<li>${esc(line.name)}：${esc(shortRainText(line))} ${mark(line.hit)}</li>`).join("");
  const fact = rain?.accent ? `<p class="mul-fact">台風25号（2026年9月・千葉県）の浸水447件のうち、洪水の地図に色のない場所が足すと64%（<a href="${esc(rain.accent.source_url)}" target="_blank" rel="noopener">${esc(rain.accent.source)}</a>）</p>` : "";
  // 結論の下に「浸かると止まるもの」を添える（画面1の時点で何が止まるか分かるように。建物の階で変わるので、断定せず「浸かると」）。
  const consequence = !compact && head[0] === "risk" ? `<p class="rh-stop"><b>機械室（給水ポンプ室・電気室・借室）が浸かると、全戸で止まるもの：</b><span>水・トイレ</span><span>エレベーター</span><span>各戸の電気</span><small>何階にあるかで変わります。次の画面で竣工図から確かめます。</small></p>` : "";
  return `<div class="risk-head ${head[0]}"><p class="rh-title">${head[0] === "risk" ? "⚠ " : ""}${esc(head[1])}</p><p class="rh-sub">${esc(sub)}</p>${consequence}</div>
  <div class="mul">
    <div class="mul-card${mapHit ? " hit" : ""}"><p class="mul-head">国が公表する浸水の想定（ハザードマップ）${mark(mapHit ? true : mapClear ? false : null)}</p><ul>${mapLines}</ul></div>
    <div class="mul-x">×</div>
    <div class="mul-card${rainHit ? " hit" : ""}"><p class="mul-head">地形から見た浸かりやすさ（台風・大雨・線状降水帯）${mark(rainHit ? true : rainClear ? false : null)}</p><ul>${rainLines}</ul>${fact}</div>
  </div>`;
}

// 線状降水帯のカードの1行（サーバーの文の最初の句だけ。数値の内訳は折りたたみへ）。
function shortRainText(line) {
  const text = String(line.text || "");
  if (line.name === "内水の地図") return text.startsWith("国の") ? "国のデータなし" : text;
  return text.split("。")[0].replace("（くぼ地の型）", "（くぼ地）");
}



// 土地を横から見た図（2D）：東西の標高の断面に建物を置き、3つの水の深さを建物の高さと比べる（2026-11-06 本人の指示・9回目：ハザードマップをやめて視覚的に）。
// 標高は国土地理院の標高API（profile.ew：西−100m〜東+100m）。深さの帯は公的な凡例のまま。判定は変えない。
function terrainFigure(lines) {
  const reading = S.place?.location?.reading || {};
  const prof = reading.profile?.ew || [];
  const pts = prof.filter((pt) => typeof pt[1] === "number");
  if (pts.length < 3) return "";
  const by = Object.fromEntries((lines || []).map((line) => [line.key, line]));
  const basement = hasBasement();
  // 階数：本人の答え・Web・図面（S.own.floors）か、見本の建物の階数。どちらもなければ描かない。
  const known = Number(S.own.floors) || (S.sampleId ? Number(S.points.find((pt) => pt.sample === S.sampleId)?.floors) : 0) || 0;
  // 2階以上もまとめずに各階を描く（2026-11-07 本人の指摘・17回目）。15階以上は下の10階と上の2階を描き、間を切断線で省く。
  const brk = known > 14;
  const drawn = known ? (brk ? 12 : known) : 1;
  const center = (pts.find((pt) => pt[0] === 0) || pts[Math.floor(pts.length / 2)])[1];
  const relief = Math.max(0.6, ...pts.map((pt) => Math.abs(pt[1] - center)));
  // 縦の縮尺（m→px）：地形の起伏と、描く階数の両方で決める。帯と階は同じ縮尺。
  const vs = Math.min(22, 60 / relief, 300 / (2.9 * Math.max(drawn, 3)));
  const floorPx = 2.9 * vs, gap = brk ? 16 : 0;
  const W = 700, cx = 350;
  const y0 = Math.round(36 + floorPx * drawn + gap + floorPx * 0.45 + 12);
  const H = y0 + (basement ? Math.round(floorPx) : 0) + 110;
  const X = (d) => cx + d * 3;
  const Y = (e) => y0 - (e - center) * vs;
  const ground = pts.map((pt) => `${X(pt[0])},${Y(pt[1]).toFixed(1)}`).join(" ");
  const parts = [];
  parts.push(`<rect x="0" y="0" width="${W}" height="${H}" class="t-sky"/>`);
  // 水の帯（建物の地面を0として上へ）。名前は帯の左上・空の中に置き、地面と重ねない。
  const bands = [];
  const flood = by.flood?.verdict === "risk" ? parseBand(by.flood.value) : null;
  const surge = by.surge?.verdict === "risk" ? parseBand(by.surge.value) : null;
  const inland = by.inland?.verdict === "risk" ? parseBand(by.inland.value) : null;
  if (flood) bands.push({ ...flood, name: `川の洪水 ${by.flood.value}`, cls: "flood" });
  if (surge) bands.push({ ...surge, name: `高潮 ${by.surge.value}`, cls: "surge" });
  // 内水の帯は、国の内水の地図に色があるときだけ（固定の深さを描かない。2026-11-07）。
  if (inland) bands.push({ ...inland, name: `内水 ${by.inland.value}`, cls: "rain" });
  const used = [];
  bands.forEach((band) => {
    const top = Y(center + Math.min(band.high === null ? band.low + 2 : band.high, 6));
    const bottom = Y(center + band.low);
    parts.push(`<rect x="0" y="${top.toFixed(1)}" width="${W}" height="${(bottom - top).toFixed(1)}" class="t-band ${band.cls}"/>`);
    // 薄い帯（内水）は帯の上の空に、厚い帯は帯の中の左上に。重なるときは上へずらす。
    let ly = bottom - top < 20 ? top - 4 : top + 14;
    while (used.some((u) => Math.abs(u - ly) < 15)) ly -= 15;
    used.push(ly);
    parts.push(`<text x="8" y="${ly.toFixed(1)}" class="t-band-label ${band.cls}">${esc(band.name)}</text>`);
  });
  // 地面。
  parts.push(`<polygon points="${X(pts[0][0])},${H} ${ground} ${X(pts[pts.length - 1][0])},${H}" class="t-ground"/>`);
  parts.push(`<polyline points="${ground}" class="t-ground-line"/>`);
  // 建物：建築の断面として描く（2026-11-07・14回目、17回目で各階を描く形に）。各階のスラブ（太線）・黒塗りの柱・間仕切り・窓・バルコニーの手すり、
  // 地下があれば地下階と基礎ピット、下に黒塗りの基礎フーチング。1階の床の高さと帯を比べる絵は変えない。
  const bw = 110, floorH = floorPx, colW = 6, wall = 2.5;
  const L = cx - bw / 2, R = cx + bw / 2;
  // n階の床の y（15階以上は、10階より上を切断線のぶん上へずらす）。
  const floorY = (n) => y0 - floorH * (n - 1) - (brk && n > 10 ? gap : 0);
  const slab = (yy, x1 = L - 6, x2 = R + 6) => parts.push(`<path d="M${x1} ${yy.toFixed(1)} L${x2} ${yy.toFixed(1)}" class="t-slab"/>`);
  const columns = (yTop, yBottom) => {
    parts.push(`<rect x="${L + 3}" y="${yTop.toFixed(1)}" width="${colW}" height="${(yBottom - yTop).toFixed(1)}" class="t-col"/>`);
    parts.push(`<rect x="${R - 3 - colW}" y="${yTop.toFixed(1)}" width="${colW}" height="${(yBottom - yTop).toFixed(1)}" class="t-col"/>`);
    parts.push(`<rect x="${(L + bw * 0.36 - colW / 2).toFixed(1)}" y="${yTop.toFixed(1)}" width="${colW}" height="${(yBottom - yTop).toFixed(1)}" class="t-col"/>`);
  };
  const roofY = floorY(drawn + 1);
  const top = known ? roofY : y0 - floorH * 2;
  // 外形（1階の床から屋上まで）。
  parts.push(`<rect x="${L}" y="${roofY.toFixed(1)}" width="${bw}" height="${(y0 - roofY).toFixed(1)}" class="t-bldg"/>`);
  for (let n = 1; n <= drawn; n += 1) {
    const fy = floorY(n), ceil = floorY(n + 1);
    columns(ceil + wall, fy - wall);
    slab(fy, n === 1 ? L : L - 6, n === 1 ? R : R + 6);
    // 間仕切り（細線）と、窓（外壁の中の二重線）、バルコニーの手すり（右側）。
    parts.push(`<path d="M${(L + bw * 0.18).toFixed(1)} ${(ceil + wall).toFixed(1)} L${(L + bw * 0.18).toFixed(1)} ${(fy - wall).toFixed(1)}" class="t-part"/>`);
    parts.push(`<path d="M${L + 1} ${(fy - floorH * 0.72).toFixed(1)} L${L + 1} ${(fy - floorH * 0.3).toFixed(1)}" class="t-win"/>`);
    if (n >= 2 || !basement) {
      parts.push(`<path d="M${R + 6} ${(fy - floorH * 0.42).toFixed(1)} L${R + 6} ${fy.toFixed(1)} M${R - 2} ${(fy - floorH * 0.42).toFixed(1)} L${R + 6} ${(fy - floorH * 0.42).toFixed(1)}" class="t-rail"/>`);
    }
    // 階の名前：15階以上では上の2階は実際の階（例：37階・38階）。
    const label = brk && n > 10 ? `${known - (drawn - n)}階` : `${n}階`;
    if (floorH >= 14) parts.push(`<text x="${(L + bw * 0.66).toFixed(1)}" y="${(fy - floorH / 2 + 4).toFixed(1)}" class="t-floor-label" text-anchor="middle">${label}</text>`);
  }
  if (brk) {
    // 切断線（11〜N-2階は省く）。
    const by = floorY(10) - floorH - gap / 2;
    parts.push(`<rect x="${L - 8}" y="${(by - 5).toFixed(1)}" width="${bw + 16}" height="10" class="t-break-bg"/>`);
    parts.push(`<path d="M${L - 8} ${(by + 3).toFixed(1)} L${L + bw * 0.25} ${(by - 3).toFixed(1)} L${L + bw * 0.5} ${(by + 3).toFixed(1)} L${L + bw * 0.75} ${(by - 3).toFixed(1)} L${R + 8} ${(by + 3).toFixed(1)}" class="t-break"/>`);
    parts.push(`<text x="${R + 12}" y="${(by + 4).toFixed(1)}" class="t-floor-label muted">11〜${known - 2}階は省略</text>`);
  }
  // 屋上のパラペットと、階段室・EV機械室の塔屋。
  slab(roofY);
  parts.push(`<rect x="${(L + bw * 0.4).toFixed(1)}" y="${(roofY - floorH * 0.45).toFixed(1)}" width="${(bw * 0.3).toFixed(1)}" height="${(floorH * 0.45).toFixed(1)}" class="t-ph"/>`);
  if (!known) {
    parts.push(`<rect x="${L}" y="${top.toFixed(1)}" width="${bw}" height="${floorH.toFixed(1)}" class="t-bldg unknown"/>`);
    parts.push(`<text x="${cx}" y="${(top + floorH / 2 + 4).toFixed(1)}" class="t-floor-label muted" text-anchor="middle">階数 未確認</text>`);
  }
  // 地下階とピット、基礎。地下は土の中（地面の線の下）に描く。
  const pitH = Math.max(10, floorH * 0.3);
  let baseY = y0;
  if (basement) {
    const by1 = y0 + floorH;
    parts.push(`<rect x="${L}" y="${y0}" width="${bw}" height="${floorH.toFixed(1)}" class="t-bldg basement"/>`);
    columns(y0 + wall, by1 - wall);
    slab(by1, L, R);
    if (floorH >= 14) parts.push(`<text x="${(L + bw * 0.66).toFixed(1)}" y="${(y0 + floorH / 2 + 4).toFixed(1)}" class="t-floor-label" text-anchor="middle">地下1階</text>`);
    // 浅い水でも入口から地下へ流れ込むことを、矢印で見せる。
    parts.push(`<path d="M${R + 26} ${(y0 - 8).toFixed(1)} L${R + 8} ${(y0 - 8).toFixed(1)} L${R + 8} ${(by1 - 10).toFixed(1)}" class="t-flow thin" marker-end="url(#t-head)"/>`);
    baseY = by1;
  }
  // 基礎ピット（斜線）と、柱の下の黒塗りのフーチング。
  parts.push(`<rect x="${L}" y="${baseY.toFixed(1)}" width="${bw}" height="${pitH.toFixed(1)}" class="t-pit"/>`);
  [L + 3 + colW / 2, L + bw * 0.36, R - 3 - colW / 2].forEach((x) => parts.push(`<rect x="${(x - 9).toFixed(1)}" y="${(baseY + pitH - 5).toFixed(1)}" width="18" height="7" class="t-footing"/>`));
  parts.push(`<text x="${L - 4}" y="${(baseY + pitH / 2 + 3).toFixed(1)}" class="t-pit-label" text-anchor="end">ピット</text>`);
  // 建物の位置の標高（国土地理院の値）。建物の高さではない。
  parts.push(`<text x="${cx}" y="${(baseY + pitH + 16).toFixed(1)}" class="t-elev" text-anchor="middle">標高 ${center}m</text>`);
  // 標高の札と、高い側からの矢印（建物の枠の手前で止める）。
  pts.forEach((pt) => {
    if (pt[0] === 0) return;
    // 標高の数字は地面の中（帯の文字と重ねない）。
    parts.push(`<text x="${X(pt[0])}" y="${(Y(pt[1]) + 16).toFixed(1)}" class="t-elev" text-anchor="middle">${pt[1]}m</text>`);
  });
  parts.push(`<text x="${X(pts[0][0]) + 4}" y="${H - 8}" class="t-dir">西 ${Math.abs(pts[0][0])}m</text><text x="${X(pts[pts.length - 1][0]) - 4}" y="${H - 8}" class="t-dir" text-anchor="end">東 ${pts[pts.length - 1][0]}m</text>`);
  [["west", -1], ["east", 1]].forEach(([key, sign]) => {
    const side = reading.elevation?.points?.find((pt) => pt.key === key);
    if (!side || typeof side.elevation_m !== "number" || side.elevation_m <= center) return;
    const x1 = X(sign * 50), x2 = cx + sign * (bw / 2 + 14);
    parts.push(`<path d="M${x1} ${(Y(side.elevation_m) - 14).toFixed(1)} L${x2} ${(y0 - 14).toFixed(1)}" class="t-flow" marker-end="url(#t-head)"/>`);
  });
  return `<figure class="terrain"><svg class="terrain-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="土地を横から見た図">
    <defs><marker id="t-head" markerWidth="5" markerHeight="5" refX="2.6" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 z" class="p-head"/></marker><pattern id="t-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><path d="M0 0 L0 6" stroke="#6b5a3e" stroke-width="1"/></pattern></defs>
    ${parts.join("")}
  </svg><figcaption>東西200mの断面（国土地理院の標高）。帯＝国の地図の深さ。建物は階数以外は模式です。</figcaption></figure>`;
}

// 地下があるか（画面1の図のため）：見本の形か、Web・図面で分かった地下か、本人の答え。
function hasBasement() {
  if (S.sampleId) return ["a", "c"].includes(S.sampleId);
  if (S.own.basement === "yes") return true;
  const below = S.facts?.found?.floors_below;
  return typeof below === "number" && below > 0;
}

function floorChoice(floor) {
  const text = String(floor || "");
  if (/地下/.test(text)) return "basement";
  if (/^1階/.test(text)) return "ground";
  const m = text.match(/(\d+)階/);
  if (m && Number(m[1]) >= 2) return "upper";
  return null;
}


// アップロードした図面の画像に、読めた部屋の位置のピンを立てて出す（画面2・3・A4）。PDF は画像にできないので出さない。
function drawingFigure(small = false) {
  const images = S.drawingImages || [];
  if (!images.length) return "";
  const marks = ROOM_MARKS;
  const names = DRAWING_NAMES;
  const one = (image) => {
    // ピンは①②③の部屋だけ（EPS・PS・MB などの細かい設備は立てない。図が読めなくなるため。2026-11-07・14回目）。
    const pins = (image.rooms || [])
      .filter((room) => marks[room.kind] && typeof room.x === "number" && typeof room.y === "number")
      .map((room) => `<span class="d-pin${marks[room.kind] ? " main" : ""}" style="left:${(room.x * 100).toFixed(1)}%;top:${(room.y * 100).toFixed(1)}%" title="${esc(room.word || room.name || "")}">${marks[room.kind] || esc((room.word || "").slice(0, 3))}</span>`)
      .join("");
    // ピンがない画像（外観写真・系統図など）は「あなたの外観写真」のように名前だけ（2026-11-07・20回目）。
    return `<figure class="drawing${small ? " small" : ""}"><div class="d-box"><img src="${image.dataUrl}" alt="あなたの${esc(names[image.kind] || "図面")}"><div class="d-pins">${pins}</div></div><figcaption>あなたの${names[image.kind] || "図面"}${pins ? "（読めた部屋の位置にピン）" : ""}</figcaption></figure>`;
  };
  const figs = images.map(one).join("");
  // 2枚以上は横に並べて縦の長さを抑える（2026-11-07・24回目）。
  return images.length > 1 ? `<div class="drawings-row n${Math.min(images.length, 3)}">${figs}</div>` : figs;
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
function yen(value) {
  return `${Math.round(value).toLocaleString("ja-JP")}円`;
}

function man(value) {
  const n = Math.round(value / 10000);
  return `${n.toLocaleString("ja-JP")}万円`;
}

// 費用（2026-11-06 本人の指示）：場所・サイズ別の単価×個数の表1つ。単価はサーバーの unit_prices（一般的な目安）のまま。
function counts() {
  if (!S.cnt) S.cnt = Object.fromEntries((S.building?.unit_prices || []).map((item) => [item.key, item.count]));
  return S.cnt;
}

function costTotals() {
  const cnt = counts();
  const items = (S.building?.unit_prices || []).map((item) => ({ ...item, n: Number(cnt[item.key] || 0), sub: item.yen * Number(cnt[item.key] || 0) }));
  const total = items.reduce((sum, item) => sum + item.sub, 0);
  const plates = items.filter((item) => item.kind === "plate").reduce((sum, item) => sum + item.sub, 0);
  const withPlates = items.filter((item) => ["plate", "hole", "vent"].includes(item.kind)).reduce((sum, item) => sum + item.sub, 0);
  return { items, total, plates, withPlates };
}

// 補助の自動計算。率・上限・切り捨ては、その制度の文のまま。対象は止水板（都は、止水板と併せる穴・換気口も）。計算例で、交付を約束しない。
function subsidyGrant(totals) {
  const aid = subsidy();
  let calc = null;
  let base = 0;
  if (aid.covers) {
    calc = aid.covers.pillar || aid.covers.plate || null;
    base = totals.plates;
  } else if (aid.calc) {
    calc = aid.calc;
    base = aid.region === "tokyo" ? (totals.plates > 0 ? totals.withPlates : 0) : totals.plates;
  }
  if (!calc || base <= 0) return { grant: 0, label: aid.label || "", known: Boolean(calc) };
  // 市川市のように「10万円×戸数」の上限がある制度は、戸数を入れたときだけその上限も見る。
  const units = Number(S.units);
  const cap = calc.per_unit && units >= 1 ? Math.min(calc.cap, calc.per_unit * units) : calc.cap;
  const grant = Math.floor(Math.min(base * calc.rate, cap) / calc.unit) * calc.unit;
  return { grant, label: aid.label, known: true };
}

function costTable(print = false) {
  const totals = costTotals();
  const aid = subsidyGrant(totals);
  const own = totals.total - aid.grant;
  const units = Number(S.units);
  const rows = (print ? totals.items.filter((i) => i.n > 0) : totals.items).map((item) => `<tr>
      <td>${esc(item.label)}</td>
      <td class="num">${man(item.yen)}</td>
      <td class="num cnt">${print ? item.n : `<button type="button" data-cnt="${item.key}" data-d="-1" aria-label="減らす">−</button><b>${item.n}</b><button type="button" data-cnt="${item.key}" data-d="1" aria-label="増やす">＋</button>`}</td>
      <td class="num">${item.n ? man(item.sub) : "—"}</td>
    </tr>`).join("");
  const unitsCell = print ? `${units || "—"}戸` : `<input type="number" inmode="numeric" min="1" step="1" data-units="1" value="${esc(S.units || "")}" placeholder="50">戸`;
  return `<table class="cost">
    <thead><tr><th>場所・工事</th><th>単価</th><th>個数</th><th>小計</th></tr></thead>
    <tbody>${rows}</tbody>
    <tfoot><tr><th colspan="3">工事の目安の合計</th><td class="num">${man(totals.total)}</td></tr>
    <tr><th colspan="3">補助：${esc(aid.label.replace(/（.*$/, "") || "未調査")}${aidRule(subsidy()) ? `　${esc(aidRule(subsidy()))}` : ""} → 計算例</th><td class="num">− ${man(aid.grant)}</td></tr>
    ${print ? "" : `<tr><th colspan="3">戸数</th><td class="num">${unitsCell}</td></tr>`}</tfoot>
  </table>
  <div class="cost-sum${aid.grant > 0 ? " win" : ""}">
    ${aid.grant > 0 ? `<p class="cost-before"><span>補助なし</span><b>${man(totals.total)}</b><small>${units >= 1 ? `（1戸あたり約${yen(totals.total / units)}）` : ""}</small></p>` : ""}
    <p class="cost-after"><span>${aid.grant > 0 ? "補助を使うと、組合の実質負担" : "組合の実質負担"}</span><b>${man(own)}</b><small>${units >= 1 ? `（${print ? `${units}戸で` : ""}1戸あたり約${yen(own / units)}）` : "（戸数を入れると1戸あたりを出します）"}</small></p>
    ${aid.grant > 0 ? `<p class="win-line">${esc(aid.label.replace(/（.*$/, ""))}が ${man(aid.grant)} を負担する計算例。市は被害と災害対応の費用を減らせ、組合は負担を減らせます。</p>` : ""}
  </div>
  <p class="cost-risk">${esc(S.building?.recovery_cost_line || "")}</p>
  ${matsudoLine("hint case-line")}
  <p class="hint">単価と復旧費は一般的な目安です（実際の工事では現地調査・見積りの値に置き換えます）。${aid.known ? "補助は制度の率と上限で計算した例で、交付を約束するものではありません。" : "この市区町村の補助は未調査のため、0円で計算しています。"}</p>`;
}

// 補助の出典の1行（表の中に補助の額が入っているので、説明の箱は出さない。2026-11-06 本人の指示）。
function aidSource() {
  const aid = subsidy();
  if (!aid.url) return `<p class="hint">${esc(aid.label || "")}。${esc(aid.rate_label || "")}</p>${prefNote(aid)}`;
  const cautions = (aid.cautions || []).slice(0, 2).map((line) => `<li>${esc(line)}</li>`).join("");
  return `<p class="hint">使える条件は市に確かめます${cautions ? `：<ul class="aid-cautions">${cautions}</ul>` : "。"}出典：<a href="${esc(aid.url)}" target="_blank" rel="noopener">${esc(aid.label.replace(/（.*$/, ""))}の公式の案内</a>（${esc(aid.checked || "")} 確認）。計算例で、交付を約束するものではありません。</p>`;
}

// 県の動き（千葉県内で補助が見つかっていない市町村に添える。サーバーの文と出典のまま）。
function prefNote(aid) {
  const note = aid?.pref_note;
  if (!note) return "";
  const links = (note.urls || []).map((u) => `<a href="${esc(u.url)}" target="_blank" rel="noopener">${esc(u.title)}</a>`).join("／");
  return `<small class="pref-note">${esc(note.text)}${links ? `（${links}）` : ""}</small>`;
}

// 画面1：場所を選んだらすぐ、この市区町村の補助を出す（2026-11-06 本人の指摘「マンション名から即座に」）。
// 補助の規則を言葉で（率・上限・戸数の上限）。計算の中身が見えるように（2026-11-06 本人の指摘）。
function aidRule(aid) {
  const calc = aid?.covers?.plate || aid?.covers?.pillar || aid?.calc;
  if (!calc) return "";
  const twelfths = Math.round(calc.rate * 12);
  const rate = { 6: "1/2", 4: "1/3", 8: "2/3", 9: "3/4", 10: "4/5", 12: "全額" }[twelfths] || `${Math.round(calc.rate * 100)}%`;
  const cap = calc.cap ? `上限${man(calc.cap)}` : "";
  const per = calc.per_unit ? `・${man(calc.per_unit)}×戸数まで` : "";
  return `工事費の${rate}（${cap}${per}）`;
}

// 補助は「組合の得」として見せる（2026-11-06 本人の指摘：行政目線ではなく、お互いに得があること）。
// 市は床上浸水の被害と災害対応の費用を減らしたい、組合は負担を減らしたい。計算例は制度の率と上限で、交付の約束ではない。
function aidExample(aid, cost) {
  const calc = aid?.covers?.plate || aid?.covers?.pillar || aid?.calc;
  if (!calc) return 0;
  return Math.floor(Math.min(cost * calc.rate, calc.cap) / (calc.unit || 1)) * (calc.unit || 1);
}

function placeAid() {
  const aid = S.place?.subsidy;
  if (!aid) return "";
  const town = (aid.label || "").replace(/（.*$/, "");
  const rule = aidRule(aid);
  if (!rule) return `<div class="place-aid"><p><b>補助</b>${esc(aid.label)}</p><small>${esc(aid.rate_label)}</small>${prefNote(aid)}</div>`;
  const example = aidExample(aid, 3000000);
  // 「300万円の1/2なのに225万円？」とならないよう、上限額を率のすぐ後ろに入れる（2026-11-06 本人の指示）。
  return `<div class="place-aid win"><p class="win-head">対策するなら</p>
    <p class="win-num"><b>${esc(town)}の補助：${esc(rule)}</b></p>
    ${example ? `<p class="win-num">例：300万円の工事 → 組合は <em class="win-yen">${man(3000000 - example)}</em>（−${man(example)}）</p>` : ""}
    <small>${esc((aid.cautions || [])[0] || "")}計算例で、交付の約束ではありません。</small></div>`;
}

// 理事会で決めること（2026-11-06 本人の指示）：今日0円で決められる3つ。チェックは画面の中だけ（保存には入る）。
const BOARD_ITEMS = [
  "対象箇所の無料の現地調査と、2〜3社の相見積もりを頼む",
  "自治体の補助金の窓口へ事前に相談する担当を決める",
  "次回の電気点検で、盤の下端の高さとケーブルの余長の確認を頼む",
];

// 理事会で決めること：この建物のクリティカル対策を順に（提案がないときは共通の3つ）。
function boardItems() {
  const c = S.building?.critical;
  if (!c) return BOARD_ITEMS;
  return [...c.items.map((item) => `${item.title}（${item.cost}）`), BOARD_ITEMS[0]].slice(0, 4);
}

function boardDecisions(print = false) {
  const items = boardItems().map((text, i) => `<li><input type="checkbox" data-chk="${i}"${S.chk?.[i] ? " checked" : ""}${print ? " disabled" : ""}><span>${esc(text)}</span></li>`).join("");
  return `<ol class="decide">${items}</ol>`;
}

function a4Front(date) {
  // 理事会に出すA4縦1枚。2026-11-07・24回目：やる気のない理事でも「何を判断するか」が一目で分かるように、
  // 上に3つの数字（今のまま／事前対策／決めること）、左に図と止まる3札、右に「本日決めること」と費用の3行、立地は2行。対策の表と単価の表は画面3・費用タブに置く。
  const b = S.building;
  const units = Number(S.units) || 50;
  const fixed = [disclaimer() || "", ...SHEET_FIXED, ...(b.sample.custom ? [borrowedNote()] : [])];
  return `<div class="sheet a4-onepage">
    <header class="a4-header">
      <div>
        <p class="a4-doc-type">管理組合理事会　浸水対策の提案資料</p>
        <h1 class="a4-main-title">${esc(where())}｜${esc(titleLine())}</h1>
      </div>
      <div class="a4-meta">作成日：${esc(date)}<br>戸数：${esc(units)}戸</div>
    </header>
    ${a4Strip(units)}
    <div class="a4-grid">
      <div class="a4-col">
        <div class="a4-box">
          <h2>どこから水が入り、何が止まるか（水位③：機械の部屋）</h2>
          <div class="a4-figs">
            <div class="sheet-plan">${plan({ level: 3, small: true })}</div>
            <div class="sheet-plan">${sectionFigure(3, true)}</div>
          </div>
          ${lifeChips(3)}
        </div>
      </div>
      <div class="a4-col">
        <div class="a4-box a4-decide-box">
          <h2>本日の理事会で決めること</h2>
          ${boardDecisions(true)}
        </div>
        <div class="a4-box">
          <h2>費用と補助（組合の実質負担）</h2>
          ${costSummary(units)}
        </div>
        <div class="a4-box a4-place-box">
          <h2>立地（国の地図 × 地形）</h2>
          ${placeTwoLines(placeLines())}
        </div>
      </div>
    </div>
    <footer class="print-fixed">${fixed.map((line) => `<p>${esc(line)}</p>`).join("")}</footer>
  </div>`;
}

// 2026年8月の千葉豪雨の松戸市のマンションの例（復旧費・断水の期間）。出典を原文で確かめられるまで null（数字は裏取りのあるものだけ）。
const MATSUDO_CASE = {
  text: "2026年8月の千葉豪雨で地下の電気室・受水槽が浸水した松戸市の10階建て・90戸のマンション（2003年分譲）では、修繕の見積もりが1億5000万〜2億円、共用部の電気の復旧に約2か月、断水とエレベーターの停止は10月下旬時点でも続いていました",
  short: "2026年8月の千葉豪雨で地下の電気室・受水槽が浸水した松戸市の10階建て・90戸のマンションは、修繕の見積もり1億5000万〜2億円、断水とエレベーターの停止が10月下旬時点でも継続",
  source: "朝日れすかPLUS 2026/10/26・管理組合の発表 2026/10/13",
  url: "https://resuka.co.jp/townnews/2026/10/8491/",
};

// 松戸市の例を1行で（画面3の目安の下と、費用の欄に添える）。
function matsudoLine(cls = "hint") {
  if (!MATSUDO_CASE) return "";
  return `<p class="${cls}">${esc(MATSUDO_CASE.short)}（<a href="${esc(MATSUDO_CASE.url)}" target="_blank" rel="noopener">${esc(MATSUDO_CASE.source)}</a>）。</p>`;
}

// A4 の主役：今のまま浸水したときの復旧費／事前対策の費用（1戸あたり）／本日決める件数の3つの数字。数字はサーバーの目安と費用の表のまま。
function a4Strip(units) {
  const b = S.building;
  const [lo, hi] = b.recovery_cost_yen || [];
  const totals = costTotals();
  const aid = subsidyGrant(totals);
  const net = Math.max(0, totals.total - (aid.grant || 0));
  const per = units ? man(net / units) : "";
  const items = boardItems();
  const example = MATSUDO_CASE ? `<p class="a4-case">例：${esc(MATSUDO_CASE.short)}（<a href="${esc(MATSUDO_CASE.url)}" target="_blank" rel="noopener">${esc(MATSUDO_CASE.source)}</a>）</p>` : "";
  return `<div class="a4-strip">
    <div class="cmp no"><p class="cmp-head">今のまま浸水したら</p><p class="cmp-big">${lo && hi ? `約${man(lo)}〜${man(hi)}` : "—"}</p><p class="cmp-sub">設備全損時の復旧費の目安。断水8日・トイレ11日の例（2019年・川崎市）</p></div>
    <div class="cmp yes"><p class="cmp-head">事前に対策したら</p><p class="cmp-big">${man(net)}<small>${per ? `1戸あたり約${per}` : ""}${aid.grant ? "（補助後）" : ""}</small></p><p class="cmp-sub">止水板と穴埋め。単価×個数の目安で、見積りに置き換えます</p></div>
    <div class="cmp act"><p class="cmp-head">本日決めること</p><p class="cmp-big">${items.length}件<small>右の欄にチェック</small></p><p class="cmp-sub">理事会で決められる範囲の対策から</p></div>
  </div>${example}`;
}

// A4 の費用は3行だけ（単価×個数の表は費用タブ）。
function costSummary(units) {
  const totals = costTotals();
  const aid = subsidyGrant(totals);
  const own = totals.total - aid.grant;
  const label = aid.label ? aid.label.replace(/（.*$/, "") : "未調査";
  return `<table class="a4-cost">
    <tr><th>工事の目安（止水板・穴埋めなど ${totals.items.filter((i) => i.n > 0).length}項目、単価×個数）</th><td>${man(totals.total)}</td></tr>
    <tr><th>補助：${esc(label)}${aid.known ? "（計算例）" : "（0円で計算）"}</th><td>− ${man(aid.grant)}</td></tr>
    <tr class="sum"><th>組合の実質負担</th><td><b>${man(own)}</b>${units ? `<small>${units}戸で1戸あたり約${yen(own / units)}</small>` : ""}</td></tr>
  </table>`;
}

function screenFour() {
  const list = steps();
  const tabs = TABS.map(([key, word]) => `<button type="button" role="tab" class="tab${S.tab === key ? " current" : ""}" data-tab="${key}" aria-selected="${S.tab === key}">${word}</button>`).join("");
  let body = "";
  if (S.tab === "memo") {
    body = `<h1 class="title">${list.length ? `管理会社への確認依頼（残り${list.length}件）` : "主要な図面確認は完了しています"}</h1>
      <div class="plan">${plan({ pins: pinsOf(list) })}</div>
      ${list.length ? `<ol class="asks">${asksList(list)}</ol>` : ""}
      ${heardItems().length || experienceLine() ? `<div class="heard"><p class="hint"><b>住民の話・見たこと（依頼メモに載ります）</b></p><ul>${experienceLine() ? `<li>${esc(experienceLine())}</li>` : ""}${heardItems().map((text) => `<li>${esc(text)}</li>`).join("")}</ul></div>` : ""}`;
  } else if (S.tab === "a4") {
    body = `<div class="a4-head-bar">
        <div>
          <h1 class="title">理事会提出用 A4・1枚資料</h1>
          <p class="hint">このままA4縦1枚で印刷・PDF保存して理事会に提出できます。</p>
        </div>
      </div>
      <div class="paper a4-single">${a4Front(today())}</div>`;
  } else {
    body = `<h1 class="title">対策の費用と補助金の試算</h1>
      ${costTable()}
      ${aidSource()}
      <h2 class="part"><span>✓</span>本日の理事会で決めること</h2>
      ${boardDecisions()}
      ${consultBox()}`;
  }
  const print = TABS.find(([key]) => key === S.tab)[2];
  return `<section class="s4">
    <div class="tabs" role="tablist">${tabs}</div>
    ${body}
    <button type="button" class="primary" data-act="print">${print}</button>
    <button type="button" class="secondary" data-act="send">文面をコピーする（メール・LINE共有用）</button>
    ${S.sendMsg ? `<p class="hint" role="status">${esc(S.sendMsg)}</p>` : ""}
    ${S.sendText ? `<textarea class="copy-area" rows="6" readonly>${esc(S.sendText)}</textarea>` : ""}
    <h2 class="part save-head"><span>🔒</span>入力した内容を保存・共有する</h2>
    ${saveBox()}
  </section>`;
}

// ---- 現地調査・見積もり仕様カルテと依頼文（/api/consult。2026-11-07・19回目で画面に戻した）----
// 送信はせず手元で使う下書き（what-062）。文面はサーバーの定型を Claude が整え、検査に落ちれば定型のまま。
const CONSULT_PARTS = [["karte", "① 現地調査・見積もり仕様カルテ"], ["letter", "② 管理会社・工事業者への依頼文"], ["schedule", "③ 補助金と手続きの順番"]];

async function askConsult() {
  if (!S.building || S.consultBusy) return;
  S.consultBusy = true;
  render();
  try {
    const checked = Object.entries(S.chk || {}).filter(([, on]) => on).map(([key]) => key);
    S.consult = await postJSON("/api/consult", {
      sample_id: S.sampleId,
      answers: answers(),
      label: S.place?.site?.label || "",
      location_rows: S.place?.location?.rows || [],
      confirmed: confirmedTokens(),
      document_read: Boolean(S.documentRead),
      checked: checked.length ? checked : ["plate", "hole"],
      subsidy: subsidy().region,
    });
  } catch (error) {
    S.consult = { error: error.message };
  } finally {
    S.consultBusy = false;
    render();
  }
}

function consultBox() {
  const c = S.consult;
  const parts = c && !c.error ? CONSULT_PARTS.map(([key, title]) => `<div class="consult-part"><p class="own-head">${title}</p><textarea class="copy-area" rows="6" readonly>${esc(c[key] || "")}</textarea><button type="button" class="option small" data-copy="${key}">コピーする</button></div>`).join("") : "";
  const note = c ? `<p class="hint">${esc(c.error || [c.source === "claude" ? "文面を自動で整えました（数字・留保・主語は検査済み）。" : "プログラムの定型の文面です。", c.notice].filter(Boolean).join("　"))}</p>` : "";
  return `<details class="more consult-fold"><summary>現地調査・見積もり仕様カルテと依頼文を作る</summary>
    <p class="hint">管理会社や工事業者に見積りを頼むときの下書きです。この画面からは送らず、コピーして手元で使います。</p>
    <button type="button" class="option" data-act="consult"${S.consultBusy ? " disabled" : ""}>カルテと依頼文を整える（※Anthropic API を使用します）</button>
    ${S.consultBusy ? busyBox("現地調査カルテと依頼文を整えています…") : ""}
    ${note}${parts}
  </details>`;
}

// ---- 文で送る（2026-11-05） ----
// 理事会の仲間に、要点を文で送る。スマホでは共有の画面（LINE・メールなど）を開き、パソコンでは文をコピーする。
// 住所は町丁まで。固定の免責は言い換えずに付ける。サーバーには何も送らない。
function summaryText() {
  const b = S.building;
  const lines = [`【マンション浸水チェック】${where()}`, `・${titleLine()}`];
  // 立地は札の値のまま（地図の想定）。深さを主役にしない。避難の判断は自治体の警戒レベルで。
  const rows = (S.place?.location?.rows || []).map((item) => `${PLACE_SHORT[item.key] || item.label} ${item.value || ""}`.trim());
  if (rows.length) lines.push(`・立地（地図の想定）：${rows.join("／")}`);
  lines.push(`・${EVAC_LINE}`);
  if (b.rain?.third) lines.push(`・大雨が近づいたら：${b.rain.third}`);
  const exp = experienceLine();
  if (exp) lines.push(`・この辺りの経験（住民の話）：${exp}`);
  const list = steps();
  if (list.length) {
    lines.push(`・管理会社に頼む確認（${list.length}つ）`);
    list.forEach((step, i) => lines.push(`  ${i + 1}. ${PLAIN_ASK[step.key] || step.what}`));
  }
  const totals = costTotals();
  if (totals.total > 0) lines.push(`・対策の費用の目安：合計${man(totals.total)}（単価×個数。${COST_FIXED}）`);
  // 文には図がないので、「図は」ではなく、建物の形を確かめていないことを言う。
  if (b.sample.custom) lines.push("・建物の形（階数・機械室の位置）は未確認で、模式図は入力をもとにした仮のものです");
  lines.push(`※${disclaimer() || ""}`);
  return lines.join("\n");
}

async function sendSummary() {
  const text = summaryText();
  S.sendText = "";
  if (navigator.share) {
    try {
      await navigator.share({ title: "マンション浸水チェック", text });
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
      <p>答えが分かったら、マンション浸水チェックの「2 確かめる」に入れると、図の色が変わります。</p>
      ${fixed}
    </div>`;
  } else if (S.tab === "a4") {
    html = a4Front(date);
  } else {
    html = `<div class="sheet"><h1>対策の費用・補助の目安</h1><p>${esc(where())}　${date}</p>${costTable(true)}${aidSource()}<p class="sheet-line">${COST_FIXED}</p>${boardDecisions(true)}${fixed}</div>`;
  }
  const box = document.getElementById("print-memo");
  box.innerHTML = html;
  box.dataset.kind = S.tab;
  // 理事会A4：画面の紙で中身を縮めていれば、印刷でも同じ倍率にして1枚に収める（紙の幅は画面と同じ 718px＝190mm）。
  const shownZoom = document.querySelector(".paper.a4-single > .sheet")?.style.zoom;
  if (S.tab === "a4" && shownZoom && box.firstElementChild) box.firstElementChild.style.zoom = shownZoom;
  window.print();
}

// ---- 描く ----

function render() {
  // 2026-11-06 本人の指示：先に建物の階と図面を確かめ（画面2 = screenThree）、そのあと水が入る順と対策を見る（画面3 = screenTwo）。
  const views = { 1: screenOne, 2: screenThree, 3: screenTwo, 4: screenFour };
  // 開いている折りたたみは、描き直しても開いたままにする（中のボタンを押しても閉じない。2026-11-06）。
  const opened = [...screen.querySelectorAll("details[open] > summary")].map((s) => s.textContent);
  screen.innerHTML = views[S.screen]();
  screen.querySelectorAll("details").forEach((d) => {
    if (opened.includes(d.querySelector("summary")?.textContent)) d.open = true;
  });
  document.querySelectorAll("#steps [data-go]").forEach((button) => {
    const n = Number(button.dataset.go);
    button.disabled = n > S.reached;
    button.classList.toggle("current", n === S.screen);
    button.classList.toggle("done", n < S.screen);
    button.classList.toggle("next", n === S.screen + 1);
    button.setAttribute("aria-current", n === S.screen ? "step" : "false");
  });
  const text = disclaimer();
  if (text) document.getElementById("fixed-disclaimer").textContent = text;
  S.flash = [];
  fitPapers();
}

// 画面のA4は本当のA4の比率。中身が収まらないときは、紙の中だけ縮めて1枚に収める（印刷は @page の A4 で別に組む）。
function fitPapers() {
  // 紙は 794px 幅で組んである。画面ではその幅に合わせて zoom する（スマホは縮む、PC では少し大きくなる）。印刷は CSS で等倍。
  document.querySelectorAll(".paper.a4-single").forEach((paper) => {
    const room = paper.parentElement?.clientWidth || 0;
    paper.style.zoom = room > 0 ? String(Math.min(1.2, room / 794)) : "";
    // 中身が紙より長いときだけ（戸数や対策の行が多い建物）、中身を縮めて1枚に収める。印刷は printSheet() が同じ倍率を写す。
    const sheet = paper.firstElementChild;
    if (!sheet) return;
    sheet.style.zoom = "";
    if (sheet.scrollHeight > sheet.clientHeight) sheet.style.zoom = String(Math.max(0.7, (sheet.clientHeight / sheet.scrollHeight) * 0.995));
  });
}

function go(n) {
  stopPlay(false);
  // 画面3は最初から水位③（機械の部屋に水）で開き、対策の切り替えで赤→緑が変わるのを見せる（2026-11-07・22回目）。
  if (n === 3 && !S.play) S.play = 3;
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
    S.cnt = null;
    S.chk = {};
    S.units = "";
    S.exp = "";
    S.facts = null;
    S.at = null;
    S.fixOpen = false;
    S.floorsApplied = null;
    S.extra = {};
    S.read = null;
    S.autoApplied = false;
    S.report = null;
    S.reportText = "";
    S.reportApplied = null;
    S.documentRead = false;
    S.consult = null;
    S.unitsFrom = "";
    S.hintsFrom = "";
    S.drawingImages = [];
    S.fig = "plan";
    S.reached = 1;
  } catch (error) {
    S.error = error.message;
  } finally {
    S.busy = false;
    render();
  }
}

// 判定に送る答え。見本は見本の答えのまま。自分の建物は、画面2（確かめる）で図面の階が分かったときだけ部屋の階を送る。
function answers() {
  if (S.sampleId) return { ...S.extra };
  const floors = Object.values(S.choices);
  let roomsFloor = ["basement", "ground", "upper"].find((f) => floors.includes(f)) || "unknown";
  // 地下の有無は、画面1の答えを先に。画面2（確かめる）で部屋が地下と分かれば「ある」。
  let basement = roomsFloor === "basement" ? "yes" : S.own.basement;
  const built = Number(S.own.floors);
  // 部屋ごとの階（地下／1階）。判定は部屋ごとに階を見る（2026-11-06）。
  const roomFloors = Object.fromEntries(Object.entries(S.choices).filter(([, c]) => c === "basement" || c === "ground"));
  // 図面がない人の3問（見たこと）は、図面の答えがないときだけ建物の形（借りる見本・対策の切り替え）に使う。
  // 判定の色は図面で確かめるまで変えない（confirmed には入れない。2026-11-07 本人の指示・15回目）。
  const seen = {};
  if (S.drawing === "no" && !floors.length) {
    if (S.obs.door === "basement" || S.obs.slope === "yes") {
      roomsFloor = "basement";
      basement = "yes";
    } else if (S.obs.door === "ground" || (S.obs.slope === "no" && basement !== "yes")) {
      roomsFloor = "ground";
    }
    if (S.obs.slope === "yes" || S.obs.slope === "no") seen.slope = S.obs.slope;
  }
  return { rooms_floor: roomsFloor, basement, room_floors: roomFloors, ...(built >= 1 ? { floors: built } : {}), ...seen, ...S.extra };
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
    document_read: Boolean(S.documentRead),
    directions: {},
    low_directions: reading.low_directions || [],
    high_directions: reading.high_directions || [],
    basin: Boolean(reading.basin),
    statements: [...S.statements, ...obsStatements()],
    location_rows: location.rows,
  });
  // 建物の形が変わったら、費用の個数は初期値に戻す。同じ建物なら人が変えた個数を残す。
  if (!before || S.building.sample.id !== S.cntSample) {
    S.cnt = null;
    S.cntSample = S.building.sample.id;
  }
  // 戸数は最初から入れておく（見本はその見本の戸数、ほかは50）。開いた瞬間に1戸あたりが出る（2026-11-06）。
  if (!S.units) S.units = S.building.sample.units || 50;
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

// 部屋の答えを入れる（描き直さない）。入れた kind の一覧を返す。
function assignRoom(kind, choice) {
  // 電気室と分電盤室は同じ問い②。借りる見本が変わると kind が入れ替わるので、両方に同じ答えを入れる（答えが消えないように。2026-11-06 本人の指摘）。
  const kinds = kind === "elec" || kind === "panel_room" ? ["elec", "panel_room"] : [kind];
  kinds.forEach((k) => {
    if (choice === "none") delete S.choices[k];
    else S.choices[k] = choice;
  });
  // 東京電力の部屋は、図面で階が分かれば「ある」、図面になければ「ない」と答えたことにもなる。
  if (kind === "tr") {
    if (choice === "none") delete S.extra.tr;
    else S.extra.tr = choice === "absent" ? "no" : "yes";
  }
  return kinds;
}

async function setRoom(kind, choice) {
  const before = openCount();
  assignRoom(kind, choice);
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
// 2026-11-07・20回目：古い紙の図面やスマホ写真の小さい字が潰れないよう、長辺 2,560px・3.5MB まで、品質も高めに。
const SHRINK_EDGE = 2560;
const SHRINK_QUALITIES = [0.92, 0.85, 0.78];
const SHRINK_TARGET_BYTES = Math.round(3.5 * 1024 * 1024);

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

// 図面を読む。複数枚（配置図＋平面図＋断面図）を順に読んで合算する（2026-11-06 本人の指示・8回目）。null は見本の図面。
async function readPlan(files) {
  const list = files ? [].concat(files) : [null];
  for (const file of list) {
    const problem = file ? fileProblem(file) : "";
    if (problem) {
      S.read = { message: problem, rooms: [] };
      render();
      return;
    }
  }
  S.busy = true;
  S.read = null;
  S.drawingImages = [];
  render();
  const merged = { mode: "", rooms: [], unreadable: [], drawing: null, message: "", pins: [], facts: {} };
  const seen = new Set();
  try {
    // 何枚か入れたときは同時に送り、返ってきた順ではなく入れた順に合算する（2026-11-07・21回目）。
    const results = await Promise.all(list.map(async (file) => {
      const body = { sample_id: S.sampleId };
      let dataUrl = "";
      if (file) {
        // 写真は、送る前にブラウザの中で縮めて JPEG にする（スマホの写真は1枚5〜10MB以上あり、API の画像の上限を超えるため）。
        const shrunk = file.type.startsWith("image/") ? await shrinkImage(file) : null;
        const source = shrunk || file;
        dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(new Error("ファイルを読めませんでした。"));
          reader.readAsDataURL(source);
        });
        body.data = dataUrl.split(",")[1] || "";
        body.media_type = shrunk ? "image/jpeg" : file.type;
      }
      return { file, dataUrl, got: await postJSON("/api/plan", body) };
    }));
    for (const { file, dataUrl, got } of results) {
      merged.mode = got.mode || merged.mode;
      merged.pins = got.pins?.length ? got.pins : merged.pins;
      const isPhoto = got.drawing?.kind === "photo";
      (isPhoto ? [] : got.rooms || []).forEach((room) => {
        const key = `${room.kind}:${room.floor}:${room.word}`;
        if (!seen.has(key)) {
          seen.add(key);
          merged.rooms.push(room);
        }
      });
      merged.unreadable.push(...(got.unreadable || []));
      // 階数は断面図・立面図から読めた1枚を採る（平面図からは読めない）。
      // 外観写真の階数は、図面から読めていないときだけ使う（地下の階数は外からは分からないので使わない）。
      if (isPhoto && got.drawing?.floors_above && !merged.drawing?.floors_above) merged.drawing = { ...got.drawing, floors_below: null, pit: null };
      else if (!isPhoto && got.drawing?.floors_above && !merged.drawing?.floors_above) merged.drawing = got.drawing;
      else if (!merged.drawing) merged.drawing = got.drawing || null;
      // 引込み・受電・盤・放流先などは、図面に明記があった最初の1枚の値を採る（どの図面から読めたかを添える）。
      // 外観写真からは、スロープ（図面がないときだけ）と換気口・階段の段数を見せるが、自動で答えに入れるのはスロープだけ。
      Object.keys(FACT_WORDS).forEach((key) => {
        const value = got.drawing?.[key];
        if (value === null || value === undefined || key in merged.facts) return;
        if (isPhoto && !["slope", "vent"].includes(key)) return;
        merged.facts[key] = { value, kind: got.drawing.kind, auto: !isPhoto || (key === "slope" && S.drawing === "no") };
      });
      // 写真はブラウザの中にだけ残し、画面2・3とA4に「あなたの図面」として出す（サーバーには保存しない）。
      if (file && file.type.startsWith("image/")) S.drawingImages.push({ dataUrl, kind: got.drawing?.kind || "other", rooms: got.rooms || [] });
      merged.message = list.length > 1 ? `${list.length}枚を読んで合算しました。` + (got.message || "") : got.message || "";
    }
    S.read = merged;
    const d = merged.drawing;
    if (d && d.floors_above) applyFloors(d.floors_above, d.floors_below, "drawing");
    // 本当に読み取った（Claude か PDF の文字）ときは、人に「すべて入れる」を押させず、読めた値をそのまま答えに入れる（2026-11-07 本人の指示・16回目）。
    // 見本の答え（読み取りではない）は自動で入れない。入れたあとは各行の「取り消す」と問いのボタンで直せる。
    if (merged.mode === "claude" || merged.mode === "text") {
      S.autoApplied = true;
      await applyAllRead();
      return;
    }
    S.autoApplied = false;
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

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && S.at?.found && !S.at.answer) answerBuilding("no");

});

screen.addEventListener("submit", async (event) => {
  if (event.target.id !== "find") return;
  event.preventDefault();
  const q = document.getElementById("q").value.trim();
  S.query = q;
  S.error = "";
  S.message = "";
  S.searchFacts = null;
  S.searching = true;
  render();
  try {
    const body = await getJSON(`/api/search?${new URLSearchParams({ q })}`);
    S.candidates = body.candidates || [];
    S.message = body.message || (S.candidates.length ? "" : "場所が見つかりませんでした。");
    // 所在地と一緒に階数・戸数などが読めていれば持っておき、2回目の Web 検索をしない（2026-11-07・21回目）。
    S.searchFacts = body.facts || null;
    S.searching = false;
    // 住所で探したときだけ、候補が1件なら押させずに選ぶ。建物名で探したときは住所の候補を見せて、押してから進む（2026-11-06 本人の指摘）。
    if (S.candidates.length === 1 && !looksLikeName(q)) {
      const c = S.candidates[0];
      await choosePlace({ address: c.label, longitude: c.longitude, latitude: c.latitude, pin: "1" }, null, null);
      afterPlace(q);
      return;
    }
  } catch (error) {
    S.candidates = [];
    S.error = error.message;
  }
  S.searching = false;
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
    // 選んだ時点で建物の位置として読む（地図をもう一度押させない）。地図は位置を直したいときだけ押す。
    if (c) choosePlace({ address: c.label, longitude: c.longitude, latitude: c.latitude, pin: "1" }, null, null).then(() => afterPlace(S.query));
  } else if (target.dataset.cnt) {
    const cnt = counts();
    cnt[target.dataset.cnt] = Math.max(0, Number(cnt[target.dataset.cnt] || 0) + Number(target.dataset.d));
    render();
  } else if (target.dataset.level) {
    // 水位を手で選ぶ（再生は止める）。
    clearInterval(S.timer);
    S.timer = 0;
    S.play = Number(target.dataset.level);
    render();
  } else if (target.dataset.fig) {
    S.fig = target.dataset.fig;
    render();
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
  } else if (target.dataset.act === "drop-floors") {
    dropFloors();
  } else if (target.dataset.fact) {
    setFact(target.dataset.fact, target.dataset.value);
  } else if (target.dataset.act === "apply-all") {
    applyAllRead();
  } else if (target.dataset.act === "re-search") {
    resetPlace();
  } else if (target.dataset.at) {
    answerBuilding(target.dataset.at);
  } else if (target.dataset.act === "fix-building") {
    S.fixOpen = !S.fixOpen;
    render();
  } else if (target.dataset.act === "consult") {
    askConsult();
  } else if (target.dataset.copy) {
    copyText(S.consult?.[target.dataset.copy] || "", "コピーしました。");
  } else if (target.dataset.act === "report-read") {
    readReport(document.getElementById("report-text")?.value || "");
  } else if (target.dataset.act === "report-sample") {
    readSampleReport();
  } else if (target.dataset.act === "report-apply") {
    applyReport();
  } else if (target.dataset.act === "report-drop") {
    dropReport();
  } else if (target.dataset.act === "apply-floors") {
    const d = S.read?.drawing;
    if (d) applyFloors(d.floors_above, d.floors_below, "drawing");

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
    if (S.building) loadBuilding().then(render);
  } else if (target.dataset.tab) {
    S.tab = target.dataset.tab;
    render();
  } else {
    const act = target.dataset.act;
    if (act === "see") seeBuilding();
    if (act === "play") (S.timer ? stopPlay() : startPlay());
    if (act === "modal-no" && target.classList.contains("modal-back")) answerBuilding("no");

    if (act === "level-up" || act === "level-down") {
      clearInterval(S.timer);
      S.timer = 0;
      S.play = Math.min(3, Math.max(1, (S.play || 0) + (act === "level-up" ? 1 : -1)));
      render();
    }
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
  if (event.target.id === "plan-file" && event.target.files.length) readPlan([...event.target.files]);
  if (event.target.id === "own-floors" && S.building) loadBuilding().then(render);
  if (event.target.id === "open-file" && event.target.files[0]) {
    S.openFile = event.target.files[0];
    S.openMsg = "";
    render();
  }
  // 見積り額と戸数（この画面の中だけで計算する。サーバーには送らない）。
  if (event.target.dataset.chk) {
    S.chk = { ...(S.chk || {}), [event.target.dataset.chk]: event.target.checked };
  }
  if (event.target.dataset.units) {
    S.units = event.target.value;
    S.unitsFrom = "user";
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
const SAVE_FIELDS = ["place", "demoId", "sampleId", "choices", "extra", "floor", "measure", "obs", "exp", "own", "statements", "hvSaid", "cnt", "chk", "units", "drawing", "screen", "reached"];
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
  // パスワードは最初から入れておく（「発行」の操作をなくす。2026-11-07・26回目）。自分の文字に打ち替えてもよい。
  if (!S.savePass && typeof crypto !== "undefined") S.savePass = randomPassword();
  const chips = SAVE_DAYS.map(([d, word]) => `<button type="button" class="option${days === d ? " chosen" : ""}" data-save-days="${d}" aria-pressed="${days === d}">${word}</button>`).join("");
  return `<div class="save-box">
    <label class="save-pass">パスワード<input id="save-pass" type="text" autocomplete="off" spellcheck="false" value="${esc(S.savePass || "")}" placeholder="8文字以上"><button type="button" class="option small" data-act="pass-copy">コピー</button><button type="button" class="option small" data-act="pass-random">別のにする</button></label>
    <div class="own-row"><span>期限</span><div class="options">${chips}</div></div>
    <div class="options"><button type="button" class="option" data-act="save-link">期限つきのリンクを作る</button><button type="button" class="option" data-act="save-file">暗号にしたファイルを保存する</button></div>
    ${S.saveLink ? `<p class="save-link"><input readonly value="${esc(S.saveLink)}"><button type="button" class="option small" data-act="link-copy">リンクをコピー</button></p>` : ""}
    ${S.saveMsg ? `<p class="hint" role="status">${esc(S.saveMsg)}</p>` : ""}
    <p class="hint">場所・答え・対策・費用の個数を、ブラウザの中で暗号にして保存します（図面・チャット・APIキーは入れません）。パスワードを忘れると戻せません。</p>
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
      S.saveMsg = `ファイルを保存しました。${untilWord} まで、このツールの「保存したものを開く」で開けます。`;
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
      if (stored.kind !== "shinsui-roadmap-save") throw new Error("このツールで保存したファイルではありません。");
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
  claude: "※この画面の建物の状況と裏取り済みの事実をもとに答えます（送った質問と住所・答え・判定は Anthropic API を通ります。図面と書類の中身は送りません）。",
  none: "AI を通さず、解説カードで答えます",
};
const SOURCE_NAMES = { claude: "自動応答（Claude）", fixed: "安全基準に基づく案内（即時回答）", fallback: "解説カードの案内" };
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
    go(3);
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

// 画面2では、図面や写真を Cmd+V で貼り付けても読める（2026-11-07・20回目）。文字の貼り付け（報告書の欄・入力欄）は邪魔しない。
document.addEventListener("paste", (event) => {
  if (S.screen !== 2 || !S.building || !hasDrawing()) return;
  const target = event.target;
  if (target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || target.isContentEditable)) return;
  const files = [...(event.clipboardData?.files || [])].filter((file) => file.type.startsWith("image/"));
  if (!files.length) return;
  event.preventDefault();
  readPlan(files);
});

// ワンクリックの質問（2026-11-07・19回目）。押すと入力欄に入れて、そのまま送る。3つ目は AI を通さず安全基準の案内になる。
document.getElementById("chat-chips").addEventListener("click", (event) => {
  const chip = event.target.closest("[data-chip]");
  if (!chip || chatWaiting) return;
  const input = document.getElementById("chat-input");
  input.value = chip.dataset.chip;
  document.getElementById("chat-form").requestSubmit();
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
