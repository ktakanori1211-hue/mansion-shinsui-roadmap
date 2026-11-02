"use strict";

// 水の位置と対策の切り替え、連鎖の図、五段の表、固定の文。
const ModelPanel = (() => {
  const COLUMNS = ["大雨が近づいたとき", "水が来た当日", "水が引いた翌朝", "数日〜1週間", "約2か月〜本復旧"];

  function renderControls() {
    const building = App.building;
    const water = document.getElementById("water-controls");
    water.replaceChildren(
      ...building.water_levels.map((level) => {
        const label = element("label", undefined, "control");
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "water";
        input.value = level.key;
        input.checked = level.key === App.water;
        input.addEventListener("change", () => App.setWater(level.key));
        label.append(input, element("span", `${level.label} ${level.text}`));
        return label;
      }),
    );
    const measure = document.getElementById("measure-controls");
    measure.replaceChildren(
      ...building.model_measures.map((item) => {
        const label = element("label", undefined, "control");
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "measure";
        input.value = item.key;
        input.checked = item.key === App.measure;
        input.addEventListener("change", () => App.setMeasure(item.key));
        label.append(input, element("span", item.label));
        return label;
      }),
    );
    document.getElementById("tr-note").textContent = `東京電力の変圧器の部屋：${building.fixed.tr_box}`;
    document.getElementById("model-fixed-top").textContent = building.fixed.model;
    const focus = document.getElementById("focus-buttons");
    const overview = element("button", "全体");
    overview.type = "button";
    overview.addEventListener("click", () => App.focus("overview"));
    focus.replaceChildren(
      overview,
      ...building.sample.pins.map((pin) => {
        const button = element("button", `${pin.key} ${pin.title}`, `who-border-${pin.who_kind}`);
        button.type = "button";
        button.addEventListener("click", () => App.selectPin(pin.key));
        return button;
      }),
    );
  }

  function chainRow(path, scenario) {
    const row = element("div", undefined, "chain-row");
    path.forEach((node, index) => {
      if (index) row.append(element("span", "→", "chain-arrow"));
      const stopped = scenario.stopped.includes(node.key);
      let cls = "chain-box";
      if (stopped) cls += " chain-stopped";
      if (node.key === "tr" && !stopped) cls += " chain-unknown";
      const box = element("span", node.label, cls);
      if (stopped) box.append(element("small", "止まる想定"));
      if (node.key === "tr" && !stopped) box.append(element("small", "中は建物側から分からない"));
      row.append(box);
    });
    return row;
  }

  function chainPaths(chain) {
    const nodes = Object.fromEntries(chain.nodes.map((node) => [node.key, node]));
    const next = {};
    chain.edges.forEach(([from, to]) => {
      (next[from] = next[from] || []).push(to);
    });
    const paths = [];
    const walk = (key, path) => {
      const children = next[key] || [];
      if (!children.length) {
        paths.push([...path, nodes[key]]);
        return;
      }
      children.forEach((child) => walk(child, [...path, nodes[key]]));
    };
    walk("line", []);
    return paths;
  }

  function renderChain(scenario) {
    const box = document.getElementById("chain");
    box.replaceChildren(element("h3", "停電の連鎖"));
    chainPaths(App.building.chain).forEach((path) => box.append(chainRow(path, scenario)));
    box.append(element("p", App.building.fixed.chain, "fixed-note"));
    box.append(element("p", `東京電力の変圧器の部屋：${App.building.fixed.tr_box}`, "fixed-note"));
  }

  function renderTable(scenario) {
    const table = element("table", undefined, "timeline-table");
    const header = table.createTHead().insertRow();
    header.append(element("th", ""));
    COLUMNS.forEach((name) => header.append(element("th", name)));
    const body = table.createTBody();
    scenario.table.forEach((row) => {
      const line = body.insertRow();
      line.append(element("th", row.label));
      row.cells.forEach((cell) => {
        let cls = "";
        if (cell === "止まる想定" || cell.startsWith("止まる想定")) cls = "cell-stopped";
        if (cell === "建物側から分からない") cls = "cell-unknown";
        if (cell === "目安なし＊") cls = "cell-gone";
        line.append(element("td", cell, cls));
      });
    });
    document.getElementById("timeline").replaceChildren(table);
    document.getElementById("timeline-below").replaceChildren(
      ...scenario.below.map((line) => element("p", line, "fixed-note strong")),
    );
  }

  function render(scenario) {
    const fixed = App.building.fixed;
    document.getElementById("model-fixed").replaceChildren(
      ...scenario.notes.map((line) => element("p", line, "fixed-note strong")),
      element("p", fixed.water_not_entry, "fixed-note strong"),
      element("p", App.building.sample.has_chief_engineer ? fixed.ordinary : fixed.ordinary_no_engineer, "fixed-note strong"),
      element("p", fixed.disclaimer_1, "fixed-note strong disclaimer-line"),
      element("p", "本シートは予報ではなく、現時点の静的な整理である", "fixed-note strong"),
    );
    renderChain(scenario);
    renderTable(scenario);
  }

  function highlightFocus(active) {
    document.querySelector(".disclaimer-line")?.classList.toggle("emphasis", active);
  }

  return { renderControls, render, highlightFocus };
})();

// 紙のおもて、裏、依頼メモ。
const SheetPanel = (() => {
  const SHEET_LABELS = {
    tepco: "東京電力の変圧器の部屋の扉と穴の浸水対策を東京電力パワーグリッドに照会し、申し入れる",
    hole: "マンション側の壁の穴をふさぐ（施工は電気工事の業者。理事や管理員は部屋に入らない。変圧器の部屋の穴には、だれも栓や止水材を入れない）",
    door: "マンション側の電気室の扉を防水扉にする（今の枠。変圧器の部屋の扉は含めない）",
    vent: "足元の換気口を高くする／電源車をつなげる受け口を 1 階につくる",
    panel: "ポンプのスイッチ盤を高くする（盤の下の端が低いと分かった場合）",
    power: "電源車をつなげる受け口を 1 階につくる",
  };

  function slim(headers, rows) {
    const table = element("table", undefined, "slim-table");
    const header = table.createTHead().insertRow();
    headers.forEach((name) => header.append(element("th", name)));
    const body = table.createTBody();
    rows.forEach((cells) => {
      const line = body.insertRow();
      cells.forEach((cell) => {
        const td = line.insertCell();
        if (cell instanceof Node) td.append(cell);
        else td.textContent = cell;
      });
    });
    return table;
  }

  function render() {
    const building = App.building;
    const { sample } = building;
    const label = `住所：${sample.name}／${App.locationState.site.label}（建物は架空）`;
    document.getElementById("sheet-address").textContent = label;
    document.getElementById("sheet-basis-address").textContent = label;
    document.getElementById("sheet-memo-address").textContent = label;

    const top = document.getElementById("sheet-top");
    top.replaceChildren(element("p", building.top_line.lead, "top-lead"));
    if (building.top_line.notes.length) top.append(element("p", building.top_line.notes.join(""), "top-notes"));

    document.getElementById("sheet-equipment").replaceChildren(
      slim(
        ["止まるもの", "判定", "分かったこと", "誰が確かめるか"],
        building.equipment.map((item) => [item.label, verdictTag(item.verdict, item.verdict_label), item.summary, item.confirm_short || "—"]),
      ),
    );

    const measures = building.measures.filter((m) => !["move", "door_rebuild", "power"].includes(m.key));
    document.getElementById("sheet-measures").replaceChildren(
      slim(
        ["いつ", "何をするか", "決め方・お金の出どころ", "桁"],
        measures.map((m) => [m.tier, SHEET_LABELS[m.key] || m.label, `${m.decision.replace("（建物の規約と予算による）", "＊").replace("理事会で申し入れる。工事になるときの決め方は内容が分かってから", "理事会で申し入れる。工事は内容が分かってから")}・${m.account}`, m.range]),
      ),
      ...(building.equipment.find((item) => item.key === "tr").verdict !== "risk"
        ? [element("p", "東京電力の変圧器の部屋が地下にあり、そこまで水が来るおそれがあると図面と立地で確かめられたら、扉と穴の浸水対策を東京電力パワーグリッドに申し入れます。", "sheet-pointer")]
        : []),
      element("p", "＊建物の規約と予算による。総会から任されている、規約に定めがある、その年の予算に入っている、のどれかに当たるときのことで、予算だけで足りるかは規約の書き方により確かめていません。当たるかは管理会社に規約・予算書・議事録で確かめてもらい、当たらなければ総会で決めるか任せてもらいます。屋上移設（数千万〜1億円超）と枠ごとの防水扉（300万円〜）は総会の特別決議です。", "sheet-pointer"),
    );

    const reading = App.locationState.location.reading;
    const center = reading.elevation.points[0].elevation_m;
    const surge = reading.hazards.find((h) => h.key === "storm_surge");
    const tide = (center !== null && center <= 5) || surge.status === "color";
    const hasEngineer = sample.has_chief_engineer;
    const rain = [
      "警戒レベル3：車を上へ。決議は要らず、住民が今日からできる対策です。",
      `警戒レベル4：止水板と土のうを出します。誰が出すかを先に決めます。${tide ? "低い土地か高潮の色がかかる地点なので（建物の位置では未確認）、満潮の2時間前までに出します（仮の目安。満潮と重なると排水が遅れると考えられ、時刻は潮位表で確かめます）。" : ""}`,
      hasEngineer
        ? "電気の部屋に水が来そうになったら：管理員か理事長が主任技術者に連絡します。操作は主任技術者の指示で行い、電気の部屋には、水が来る前も後も、主任技術者の同行なしに入りません。在宅で医療機器を使う人へ先に知らせ、止めると同時に全戸へ排水しないよう放送します。"
        : "盤の部屋や変圧器の部屋に水が来そうになったら：管理員か理事長が東京電力パワーグリッドと管理会社に連絡します。部屋に入りません。在宅で医療機器を使う人へ先に知らせ、全戸へ排水しないよう放送します。",
    ];
    const list = element("ul", undefined, "sheet-list");
    rain.forEach((line) => list.append(element("li", line)));
    document.getElementById("sheet-rain").replaceChildren(list, element("p", "合図は自治体や気象庁が出す警戒レベルです。予報ではありません。", "sheet-pointer"));

    const scenario = building.scenarios["3:plate"];
    const during = element("ul", undefined, "sheet-list");
    during.append(element("li", `水が来た当日：${scenario.table[scenario.table.length - 1].cells[1]}`));
    during.append(element("li", `水が引いた翌朝：${scenario.table[scenario.table.length - 1].cells[2]}`));
    document.getElementById("sheet-during").replaceChildren(during);

    document.getElementById("sheet-days").replaceChildren(
      element("p", building.fixed.timeline_top, "sheet-text strong"),
      element("p", `給水・排水の制御盤は製作に約2か月（建築設備技術者協会の報告書）。供給用変圧器${hasEngineer ? "・受電設備" : ""}が浸かった場合、排水開始から仮復旧まで4〜7日程度（経産省の検討会資料、一般的な目安）。${hasEngineer ? "受変電の特注品は復旧に1年以上の場合も（同協会の報告書）。" : ""}武蔵小杉は停電5日・断水8日・トイレ11日、本復旧6〜8か月（建築設備技術者協会の調査など。ほかの建物の例）。`, "sheet-text"),
    );

    const engineerLines = hasEngineer
      ? [
          "受電設備内の検電・残留電荷の放電・短絡接地は、水が引いて入室できる状態になり、電源側が切れていることを確かめてから行います（労働安全衛生規則第339条）。",
          "水が引いた直後に遮断器を入れません。泥と塩分が残ったまま通電すると短絡のおそれがあり、波及事故の防止にも関わります。",
          "電気室に入らずに遮断できる手段があるかと、受電設備側の最初の開閉器の位置を、単線結線図で事前に確かめてください。",
          "どの水位で誰が連絡して電気を止めるかの事前の合意を、保安規程の変更にするか覚書にするかは確かめてください。",
          sample.underground_feed ? "地中引込の建物なので、高圧ケーブルの敷設年と点検の記録、大雨や浸水のあとに行う確認を確かめてください。一度の冠水でどの程度進むかは確かめていません。歩道ぎわの蓋は開けないでください。" : "",
          "借室の穴や管路には、だれも栓や非硬化の止水材を入れません。壁の穴の施工は、停電の要否・離隔・止水材を電気工事業者と決めてから行います。",
          "防水扉や換気口のかさ上げは、施錠・立入禁止の表示・防火・換気や放熱を損なわないか確かめてください。",
        ]
      : [
          "この建物にマンション側の受電設備と電気主任技術者はありません（書類の記載）。共用部の電気代の明細で契約種別が低圧か、同じ敷地に発電設備がないかを、依頼メモ①で確かめます。",
          "盤の部屋の現地調査は電気工事業者が立ち会い、防水業者は目で見るだけとします。穴をふさぐ前に、停電の要否、盤との離隔、止水材を電気工事業者と決めます。",
          "借室の穴や管路には、だれも栓や非硬化の止水材を入れません。",
        ];
    const engineerList = element("ul", undefined, "sheet-list");
    engineerLines.filter(Boolean).forEach((line) => engineerList.append(element("li", line)));
    document.getElementById("sheet-engineer").replaceChildren(engineerList);

    const memo = document.getElementById("sheet-memo-body");
    memo.replaceChildren();
    building.memos.forEach((section) => {
      memo.append(element("h3", `依頼メモ${section.label}　${section.title}`));
      const items = element("ul", undefined, "sheet-list");
      section.items.forEach((item) => {
        const line = element("li");
        line.append(element("strong", `${item.from}：`), item.text);
        items.append(line);
      });
      if (!section.items.length) items.append(element("li", "今はありません。"));
      memo.append(items);
    });
    memo.append(element("p", "追加の費用がかかるかは、管理委託契約と保守の契約によります。", "sheet-pointer"));
    document.getElementById("sheet-memo").hidden = false;
  }

  return { render };
})();
