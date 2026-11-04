"use strict";

// ②の一番上「理事会で最初に見る1枚」（2026-11-04 作り直し）。
// 動かない理事会を動かすために、目をやる所を3つだけにする：
//   1. 何が起きるか（大きな一言と、重なりのない断面の絵）
//   2. 自分の暮らしでは（住んでいる階を入れると自分の話になる）
//   3. 次の理事会で決めること（管理会社に3つの確認を頼む・最初の手は理事会で決められることもある）
// 専門用語（受電設備・借室・盤など）は使わず、「電気の機械」「水を送るポンプ」と言う。
// 止まるかどうかはサーバーの scenario（水の位置③のときの services）のまま、日数と費用の文はサーバーの表のままで、新しい数字は作らない。
const Glance = (() => {
  const box = document.getElementById("glance");
  let step = 3;
  let timer = 0;
  let floor = "";

  const CAPTIONS = {
    1: "大雨で、道路に水がたまる",
    2: "水が、地下の機械の部屋に流れ込む",
    3: "機械が水につかって、止まる",
  };

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

  function scenarioTop() {
    return App.building?.scenarios?.[`3:${App.measure}`] || null;
  }

  function stateOf(pattern) {
    const found = (scenarioTop()?.services || []).find((service) => pattern.test(service.label));
    return found ? found.state : "unknown";
  }

  // 断面の絵。形は説明用の模式で、文字と図形が重ならないように置き場所を決めてある。
  function picture(current, basement) {
    const flooded = current >= 2;
    const broken = current >= 3;
    const pumpOff = broken && stateOf(/給水/) === "stopped";
    const powerOff = broken && stateOf(/廊下/) === "stopped";
    const evOff = flooded && stateOf(/エレベーター/) === "stopped";
    const ground = 170;
    const roomTop = basement ? 180 : 112;
    const roomBottom = basement ? 258 : 166;
    const machineY = roomBottom - 44;
    const height = basement ? 280 : 200;
    const water = current === 2 ? roomBottom - 16 : broken ? roomTop + 26 : null;
    const badge = (x, y) => `<g><rect x="${x - 32}" y="${y - 13}" width="64" height="26" rx="13" fill="#c62828"/><text x="${x}" y="${y + 6}" font-size="15" font-weight="800" text-anchor="middle" fill="#fff">止まる</text></g>`;
    const home = (x, label, pattern) => {
      const raw = stateOf(pattern);
      const state = raw === "unknown" ? "unknown" : broken && raw === "stopped" ? "off" : "on";
      const look = { off: ["#fdecea", "#c62828", "#b42318", label], on: ["#eef6e9", "#5a8f2e", "#3b6d11", label], unknown: ["#f1f1f4", "#9a9aa2", "#5a5a60", `${label}？`] }[state];
      return `<rect x="${x - 58}" y="76" width="116" height="38" rx="8" fill="${look[0]}" stroke="${look[1]}" stroke-width="2"/><text x="${x}" y="101" font-size="17" font-weight="700" text-anchor="middle" fill="${look[2]}">${look[3]}</text>`;
    };
    const bottom = basement ? roomBottom + 6 : ground;
    return `<svg viewBox="0 0 900 ${height}" role="img" aria-label="うちのマンションの断面の模式。${CAPTIONS[current]}">
      <defs><marker id="glance-arrow" markerWidth="8" markerHeight="8" refX="5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#1d5fa8"/></marker></defs>
      <rect x="0" y="0" width="900" height="${height}" fill="#f7f9fc"/>
      ${basement ? `<rect x="0" y="${ground}" width="900" height="${height - ground}" fill="#ece3d1"/>` : ""}
      <line x1="0" y1="${ground}" x2="900" y2="${ground}" stroke="#8a7a5c" stroke-width="3"/>
      <text x="14" y="${ground - 26}" font-size="16" fill="#5a5a60">道路</text>
      <rect x="0" y="${ground - 16}" width="226" height="16" fill="#2f7fd0" opacity=".55"/>
      <rect x="240" y="20" width="420" height="${bottom - 20}" fill="#fff" stroke="#44474f" stroke-width="3"/>
      <line x1="240" y1="66" x2="660" y2="66" stroke="#d3d7dd" stroke-width="2"/>
      <line x1="240" y1="124" x2="660" y2="124" stroke="#d3d7dd" stroke-width="2"/>
      <text x="252" y="50" font-size="15" fill="#5a5a60">住まい（全部の家）</text>
      ${home(320, "水・トイレ", /給水/)}
      ${home(450, "家の電気", /各戸の電気/)}
      ${home(580, "廊下の照明", /廊下/)}
      <rect x="250" y="${roomTop}" width="400" height="${roomBottom - roomTop}" fill="#fbf3e6" stroke="#c98a2b" stroke-width="2"/>
      <text x="262" y="${roomTop + 20}" font-size="15" font-weight="700" fill="#8a5a12">${basement ? "地下" : "1階"}の機械の部屋</text>
      ${water !== null ? `<rect x="252" y="${water}" width="396" height="${roomBottom - water - 2}" fill="#2f7fd0" opacity=".45"/>` : ""}
      ${flooded ? `<path d="M226 ${ground - 6} C 236 ${ground - 6}, 236 ${roomBottom - 12}, 252 ${roomBottom - 12}" fill="none" stroke="#1d5fa8" stroke-width="5" marker-end="url(#glance-arrow)"/>` : ""}
      <rect x="300" y="${machineY}" width="130" height="36" rx="6" fill="#f2b97a" stroke="#8a5a12" stroke-width="2"/>
      <text x="365" y="${machineY + 24}" font-size="16" font-weight="700" text-anchor="middle" fill="#5c3a06">電気の機械</text>
      <rect x="470" y="${machineY}" width="150" height="36" rx="6" fill="#8fc2ea" stroke="#1d5fa8" stroke-width="2"/>
      <text x="545" y="${machineY + 24}" font-size="16" font-weight="700" text-anchor="middle" fill="#0c3c73">水を送るポンプ</text>
      ${powerOff ? badge(442, machineY - 16) : ""}
      ${pumpOff ? badge(604, machineY - 16) : ""}
      <rect x="690" y="20" width="56" height="${bottom - 20}" fill="${evOff ? "#fdecea" : "#eef1f5"}" stroke="#44474f" stroke-width="3"/>
      <rect x="700" y="${evOff ? bottom - 34 : 70}" width="36" height="28" fill="${evOff ? "#c62828" : "#5b6b80"}"/>
      <text x="760" y="50" font-size="16" font-weight="700" fill="${evOff ? "#b42318" : "#44474f"}">エレベーター</text>
      ${evOff ? badge(800, 80) : ""}
    </svg>`;
  }

  // 自分の暮らしで困ること。サーバーの判定のまま、住んでいる階は本人の数をそのまま使う。
  function lifeLines() {
    const lines = [];
    if (stateOf(/給水/) === "stopped") lines.push(["水が出ない", "トイレも風呂も使えない"]);
    if (stateOf(/エレベーター/) === "stopped") {
      const n = Number(floor);
      lines.push(["エレベーターが止まる", n >= 2 ? `${n}階まで毎日階段` : "高い階は毎日階段"]);
    }
    if (stateOf(/各戸の電気/) === "stopped") lines.push(["家の電気が止まる", "冷蔵庫・冷房が使えない"]);
    return lines;
  }

  // 戻るまでの目安。サーバーの五段の表の「ほかの建物の例」の文のまま。
  function example() {
    const row = (scenarioTop()?.table || []).find((item) => /ほかの建物の例/.test(item.label));
    const cell = row?.cells?.[3];
    return cell && cell !== "—" ? cell : "";
  }

  // 最初の手の桁（③の「今すぐ」の段と同じ手の表）。
  function firstStep() {
    const measures = (App.building?.measures || []).filter((m) => m.tier === "今すぐ" && m.key !== "power");
    return measures.length && typeof tierSpan === "function" ? tierSpan(measures) : "";
  }

  function render() {
    if (!box || !App.building) return;
    const basement = App.building.sample.archetype !== "ground";
    const lines = lifeLines();

    // 1. 何が起きるか
    const what = element("div", undefined, "glance-what");
    what.append(
      element("p", "理事会で、最初に見る1枚", "glance-kicker"),
      element("p", lines.length ? `大雨で${basement ? "地下" : "1階"}の機械が水につかると、全部の家で水とエレベーターが止まります` : "今の答えでは、止まるものは見つかっていません（安全という意味ではありません）", "glance-title"),
    );
    const sample = example();
    if (sample) what.append(element("p", `戻るまで長引くことがあります（${sample}）`, "glance-sub"));
    const art = element("div", undefined, "glance-art");
    art.innerHTML = picture(step, basement);
    const caption = element("div", undefined, "glance-caption");
    const play = element("button", timer ? "❚❚ 止める" : "▶ 水が入る様子を見る", "glance-play");
    play.type = "button";
    play.addEventListener("click", () => (timer ? stop() : start()));
    caption.append(element("b", `${step}. ${CAPTIONS[step]}`), play);

    // 2. あなたの暮らしでは
    const life = element("div", undefined, "glance-life");
    const floorLabel = element("label", "あなたの暮らしでは（住んでいる階：", "glance-floor");
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.max = "80";
    input.value = floor;
    input.placeholder = "8";
    input.addEventListener("change", () => {
      floor = input.value;
      render();
    });
    floorLabel.append(input, "階）");
    const list = element("ul", undefined, "glance-life-list");
    lines.forEach(([big, small]) => {
      const item = element("li");
      item.append(element("b", big), element("span", small));
      list.append(item);
    });
    life.append(floorLabel, list);

    // 3. 次の理事会で決めること
    const act = element("div", undefined, "glance-act");
    act.append(element("p", "次の理事会で決めること", "glance-act-kicker"), element("p", "管理会社に、3つの確認を頼む", "glance-act-title"));
    const asks = element("ol", undefined, "glance-asks");
    (App.building.top_line.steps || []).forEach((item) => asks.append(withTerms(PLAIN_ASK[item.key] || item.what, "li")));
    if (asks.childElementCount) act.append(asks);
    const cost = firstStep();
    if (cost) act.append(element("p", `そのあとの最初の手は ${cost}。理事会と管理費で決められることもあります。`, "glance-cost"));
    const buttons = element("div", undefined, "glance-buttons");
    const memo = element("button", "管理会社への依頼メモを印刷", "primary");
    memo.type = "button";
    memo.addEventListener("click", () => openSheet("memo"));
    const board = element("button", "理事会用の表裏1枚を見る");
    board.type = "button";
    board.addEventListener("click", () => openSheet("board"));
    buttons.append(memo, board);
    act.append(buttons);

    const body = element("div", undefined, "glance-body");
    const left = element("div", undefined, "glance-left");
    left.append(art, caption, life);
    body.append(left, act);
    box.replaceChildren(what, body);
    box.hidden = !App.shapeChosen;
  }

  // ③の紙のタブを選んで、紙の所へ移る（③の「このあと、あなたがすること」と同じ動き）。
  function openSheet(kind) {
    App.showStage("3");
    document.querySelector(`#next-steps [data-step="${kind}"]`)?.click();
  }

  function stop() {
    clearInterval(timer);
    timer = 0;
    render();
  }

  function start() {
    clearInterval(timer);
    step = 1;
    timer = setInterval(() => {
      if (step >= 3) {
        clearInterval(timer);
        timer = 0;
        render();
        return;
      }
      step += 1;
      render();
    }, 1800);
    render();
  }

  return { render, picture, lifeLines, get step() { return step; } };
})();
window.Glance = Glance;
