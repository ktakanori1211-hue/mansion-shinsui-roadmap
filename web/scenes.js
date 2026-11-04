"use strict";

// 天気の場面のカード。浸水の8つのパターンを、どの場面で重なるかで束ねる。
// 当てはまるかは地図の色の有無だけで見て、新しい数字は作らない。
const Scenes = (() => {
  const PATTERNS = {
    1: "大きな川の氾濫",
    2: "中小の川・水路のあふれ",
    3: "下水があふれる内水",
    4: "高潮",
    5: "川や海の水位で雨水を流せない",
    6: "津波",
    7: "道路の水がスロープや出入口から地下へ",
    8: "下水管から建物への逆流",
  };
  const BUILDING_PATTERNS = [7, 8];

  const SCENES = [
    {
      key: "typhoon",
      name: "台風",
      line: "高潮と大雨が重なる",
      patterns: [4, 3, 5, 7, 8],
      layers: ["03_hightide_l2_shinsuishin_data", "02_naisui_data"],
      useDem: true,
      note: "海の水位が上がり、同時に大雨が降ります。",
    },
    {
      key: "rainband",
      name: "線状降水帯",
      line: "地図の色の外でも浸水",
      patterns: [3, 2, 7, 8],
      layers: ["02_naisui_data", "01_flood_l1_shinsuishin_newlegend_data"],
      useDem: true,
      note:
        "被害報告の55.7%が、想定区域や低い土地の外でした（2026年8月の千葉豪雨）。2026年9月の台風25号では、浸水・道路冠水447件の64%が洪水マップの色の外でした（どちらもウェザーニューズ）。千葉県で内水の地図の公表義務がある38自治体のうち19が公表していませんでした（FNNの調べ、2026年10月28日。調査の時点は記事に書かれていません）。線状降水帯は、線状に伸びる強い降水をともなう雨域です（気象庁）。洪水の地図が作られていない小さな川もあります。",
    },
    {
      key: "upstream",
      name: "上流の大雨",
      line: "その場の雨が弱くても川があふれる",
      patterns: [1, 2, 7],
      layers: ["01_flood_l2_shinsuishin_data"],
      useDem: false,
      note: "地図は想定最大規模の洪水です。",
    },
    {
      key: "tide",
      name: "満潮",
      line: "雨水を川や海へ流せない",
      patterns: [5, 3, 8],
      layers: ["02_naisui_data"],
      useDem: true,
      note:
        "川や海の水位が高いと、下水や水路から雨水を流せなくなって浸水します（神戸市）。満潮もその一つと考えられますが、大雨と満潮の重なりをはっきり書いた公的なページは、まだ見つけていません。",
    },
    {
      key: "tsunami",
      name: "地震（津波）",
      line: "海から水が来る",
      patterns: [6, 7],
      layers: ["04_tsunami_newlegend_data"],
      useDem: false,
      note: "地図は津波浸水想定です。",
    },
  ];

  let active = null;
  let activeCard = null;

  // 見方の切り替えは、地図の上に並べず「表示の設定と、地図で詳しく調べる」の折りたたみの先頭に置く（地図の上の文字を減らす）。
  function settingsBox() {
    let box = document.querySelector(".map-more .map-settings");
    if (!box) {
      box = document.createElement("div");
      box.className = "map-settings";
      document.querySelector(".map-more summary").after(box);
    }
    return box;
  }

  // 「凹みの模式を出さない」の切り替え（F-045）。既定は出す（2026-11-03 の決定）。
  // 入れると、色のない所の水色（標高から凹みにたまる模式）を塗らず、公的な地図の色の所だけを広げる
  // （2026-11-02 の「ツールが計算した範囲や深さを塗らない」に合わせた見方）。カードの当てはまり（凹みを含む）は変えない。
  const demToggle = (() => {
    // app.js（element の定義）より前に読まれるので、ここでは document.createElement で作る。
    const label = document.createElement("label");
    label.className = "control-inline scene-dem-toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = "scene-hide-dem";
    input.checked = false;
    label.append(input, " 場面の再生で、凹みの模式（水色）を出さない（公的な地図の色の所だけ広げる）");
    settingsBox().append(label);
    input.addEventListener("change", () => {
      // 再生中の場面があれば、切り替えた見方で再生し直す。
      const scene = SCENES.find((item) => item.key === active);
      if (scene && activeCard) play(scene, activeCard);
    });
    return input;
  })();

  // 「地図の横に断面図を並べる」の切り替え（F-044）。既定は並べない（2026-11-03 の決定：図面は②のタブ）。
  // 入れると、周りの低い向き（地図）から建物への水の入り方（断面図）までを一続きで見られる（11/2 以前のノートの見せ方）。
  (() => {
    const label = document.createElement("label");
    label.className = "control-inline scene-dem-toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = "scene-pair-section";
    label.append(input, " 地図の横に、建物の断面図（水の入り道）を並べる（②で形を選ぶか見本を開くと出ます）");
    const map = document.getElementById("map");
    settingsBox().append(label);
    const figure = document.createElement("figure");
    figure.className = "map-pair-section";
    figure.hidden = true;
    const image = document.createElement("img");
    image.alt = "断面図（水の入り道）";
    const caption = document.createElement("figcaption");
    figure.append(image, caption);
    let pair = null;
    const refresh = () => {
      const plan = App.building && App.shapeChosen !== false ? App.building.sample.plan : null;
      const on = input.checked && plan && plan.section_png;
      if (on && !pair) {
        pair = document.createElement("div");
        pair.className = "map-pair";
        map.before(pair);
        pair.append(map, figure);
      }
      if (pair) pair.classList.toggle("is-paired", Boolean(on));
      figure.hidden = !on;
      if (on) {
        image.src = plan.section_png;
        caption.textContent = "断面図（説明用の見本の図。あなたの建物の図面ではありません）。地図で周りの低い向きを見てから、道路から建物の中へ水が入る道をたどれます。";
      } else if (input.checked) {
        caption.textContent = "";
      }
      HazardMap.refresh();
    };
    input.addEventListener("change", refresh);
    window.addEventListener("building-shown", refresh);
    document.getElementById("stage-tabs").addEventListener("click", () => setTimeout(refresh, 0));
  })();

  function colored(reading, key) {
    const hazard = reading.hazards.find((item) => item.key === key);
    return Boolean(hazard && (hazard.status === "color" || hazard.nearby_legend));
  }

  // そのパターンが、この土地の地図で当てはまるか。建物の側のパターンは null を返す。
  function applies(pattern, reading) {
    const flood = colored(reading, "flood_max") || colored(reading, "flood_planned");
    switch (pattern) {
      case 1:
      case 2:
        return flood;
      case 3:
        return colored(reading, "inland") || reading.basin;
      case 4:
        return colored(reading, "storm_surge");
      case 5:
        return colored(reading, "storm_surge") || flood;
      case 6:
        return colored(reading, "tsunami");
      default:
        return null;
    }
  }

  function count(scene, reading) {
    return scene.patterns.filter((pattern) => applies(pattern, reading)).length;
  }

  function patternList(scene, reading) {
    const list = element("ul", undefined, "scene-patterns");
    scene.patterns.forEach((pattern) => {
      const hit = applies(pattern, reading);
      const state = hit === null ? "②建物で確かめる" : hit ? "この土地に地図の色・凹み" : "地図に色なし（安全という意味ではない）";
      const item = element("li", undefined, hit === null ? "scene-building" : hit ? "scene-hit" : "");
      item.append(element("b", PATTERNS[pattern]), ` ${state}`);
      list.append(item);
    });
    return list;
  }

  function resultText(scene, reading, outcome) {
    const lines = [];
    const hazards = reading.hazards.filter((item) => scene.layers.includes(item.layer) && item.status === "color");
    if (hazards.length) lines.push(`この建物の前：${hazards.map((item) => `${item.label} ${item.legend}`).join("、")}（地図の色）`);
    else if (outcome.hadColor) lines.push("この建物の前に地図の色はありません。周りの色は地図のとおりです。");
    if (outcome.hadDem) lines.push("水色は、建物の地面の高さまで水位を上げたときの模式です。水の量や流れは計算していません。");
    if (!lines.length) lines.push("この範囲に、この場面の地図の色はありません。色がないことは安全という意味ではありません。");
    lines.push("地下への流入と下水の逆流は、②建物で確かめます。");
    return lines;
  }

  function play(scene, card) {
    const state = App.locationState;
    if (!state) return;
    active = scene.key;
    activeCard = card;
    document.querySelectorAll(".scene-card").forEach((item) => item.classList.toggle("active", item === card));
    App.scene = scene.key;
    if (App.building && App.scenario()) App.applyScenario();
    const box = document.getElementById("scene-result");
    // 結果は地図の左下に重ねる。押しても地図の場所選びにならないようにする。
    if (box.parentElement.id !== "map") {
      document.getElementById("map").append(box);
      L.DomEvent.disableClickPropagation(box);
      L.DomEvent.disableScrollPropagation(box);
    }
    box.hidden = false;
    box.replaceChildren(element("p", `${scene.name}：水が広がっています。`, "scene-result-head"));
    // 狭い画面では地図がカードの下にあるので、地図まで動かしてから広げる。
    const mapBox = document.getElementById("map").getBoundingClientRect();
    if (mapBox.top < 0 || mapBox.bottom > window.innerHeight) document.getElementById("map").scrollIntoView({ block: "center", behavior: "smooth" });
    // 模式を出さないときは標高タイルを読まず、水色も塗らない（outcome.hadDem が偽になり、凡例と結果の文から模式が消える）。
    const shown = { ...scene, useDem: scene.useDem && !demToggle.checked };
    HazardMap.playScene(shown, (outcome) => {
      if (active !== scene.key) return;
      box.replaceChildren(
        element("p", `${scene.name}：${scene.line}`, "scene-result-head"),
        ...(outcome.hadColor || outcome.hadDem ? [legend(outcome)] : []),
        ...resultText(scene, state.location.reading, outcome).map((line) => element("p", line)),
      );
    });
  }

  function legend(outcome) {
    const row = element("p", undefined, "scene-legend");
    const item = (className, text) => {
      const swatch = element("span", undefined, `scene-swatch ${className}`);
      row.append(swatch, element("span", text));
    };
    if (outcome.hadColor) item("swatch-map", "地図の色の所（深い区分ほど濃い）");
    if (outcome.hadDem) item("swatch-dem", "凹みにたまる水（模式）");
    return row;
  }

  // 地図の重ね方を選び直したら、場面の再生をやめた表示に戻す。
  document.getElementById("layer-choices").addEventListener("change", () => {
    active = null;
    activeCard = null;
    document.querySelectorAll(".scene-card").forEach((item) => item.classList.remove("active"));
    document.getElementById("scene-result").hidden = true;
  });

  function card(scene, reading) {
    const hits = count(scene, reading);
    const tone = hits >= 2 ? "scene-hot" : hits === 1 ? "scene-warm" : "scene-none";
    const box = element("article", undefined, `scene-card ${tone}`);
    const button = element("button", undefined, "scene-play");
    button.type = "button";
    button.append(element("span", scene.name, "scene-name"), element("strong", scene.line, "scene-line"));
    // 数は「水の来方（浸水のパターン）」のうち、この土地の地図の色や凹みに当てはまるものの数（2026-11-04 言い方を直した）。
    button.append(element("span", hits ? `この土地に当てはまる水の来方：${hits}つ` : "地図の色は当てはまらない", "scene-count"));
    button.addEventListener("click", () => play(scene, box));
    const more = element("details", undefined, "why-more");
    more.append(element("summary", "パターンと出典"), patternList(scene, reading), element("p", scene.note));
    box.append(button, more);
    return box;
  }

  function render(state) {
    const reading = state.location.reading;
    active = null;
    activeCard = null;
    App.scene = null;
    document.getElementById("scene-result").hidden = true;
    // この土地に当てはまる水の来方が多い場面から並べる（同じ数なら元の順のまま）。
    const ordered = SCENES.map((scene, index) => ({ scene, index, hits: count(scene, reading) })).sort((a, b) => b.hits - a.hits || a.index - b.index);
    document.getElementById("scene-cards").replaceChildren(...ordered.map(({ scene }) => card(scene, reading)));
  }

  return { render, SCENES, PATTERNS, applies, BUILDING_PATTERNS };
})();
