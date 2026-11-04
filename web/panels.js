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
        label.title = level.text;
        label.append(input, element("span", level.label));
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
        label.title = item.label;
        label.append(input, element("span", item.short));
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
        button.title = pin.title;
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
    box.replaceChildren(element("h3", "停電の連鎖（止まる想定はオレンジ。文を読まなくても、どこまで止まるかが見えます）"));
    chainPaths(App.building.chain).forEach((path) => box.append(chainRow(path, scenario)));
    box.append(element("p", App.building.fixed.chain, "fixed-note"));
    // 借室の有無と受電の形で、止まる範囲の言い方を書き分けた一文（サーバーの chain.note）。
    if (App.building.chain.note) box.append(element("p", App.building.chain.note, "fixed-note chain-note"));
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
      const head = element("th", row.label);
      // 借室の行の固定の文と、「位置は図面で未確認」「高さは未確認」の札を、行の名前の下に小さく出す。
      if (row.note) head.append(element("small", row.note, "row-note"));
      if (row.tags?.length) {
        const tags = element("span", undefined, "row-tags");
        row.tags.forEach((tag) => tags.append(element("small", tag, "row-tag")));
        head.append(tags);
      }
      line.append(head);
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

  function renderCaption() {
    const { water_levels: levels, model_measures: measures } = App.building;
    const level = levels.find((item) => item.key === App.water);
    const measure = measures.find((item) => item.key === App.measure);
    document.getElementById("control-caption").replaceChildren(
      element("span", `${level.label} ${level.text}`),
      element("span", `対策：${measure.label}`),
    );
  }

  // 水位に合わせて「止まる設備」の数と、どれが止まるかを並べる。
  let lastCount = null;
  function renderStopCount(scenario) {
    const box = document.getElementById("stop-count");
    const count = scenario.services.filter((item) => item.state === "stopped").length;
    const number = element("strong", String(count), "stop-number");
    if (lastCount !== null && lastCount !== count) number.classList.add("stop-changed");
    lastCount = count;
    const head = element("p", undefined, "stop-head");
    // 下のカードの札（未確認）と食い違って見えないよう、「この水位まで来たら」の仮定だと見出しで言う。
    head.append(element("span", "この水位まで来たら止まる", "stop-kicker"), number, element("span", `／${scenario.services.length}`, "stop-total"));
    const chips = element("ul", undefined, "stop-chips");
    scenario.services.forEach((item) => {
      const mark = { stopped: "止まる想定", running: "—", unknown: "東京電力の部屋で中が見えない" }[item.state];
      const chip = element("li", undefined, `stop-chip stop-${item.state}`);
      chip.append(element("b", item.label), element("span", mark));
      chips.append(chip);
    });
    box.replaceChildren(head, chips);
  }

  // ①で選んだ場面と、この建物で確かめる入り道（地図には出ないパターン）。
  function renderSceneContext() {
    const box = document.getElementById("scene-context");
    const scene = typeof Scenes !== "undefined" && Scenes.SCENES.find((item) => item.key === App.scene);
    box.hidden = !scene;
    if (!scene) return;
    const routes = scene.patterns.filter((pattern) => Scenes.BUILDING_PATTERNS.includes(pattern)).map((pattern) => Scenes.PATTERNS[pattern]);
    box.replaceChildren(element("b", `①の場面：${scene.name}`), ` ${scene.line}。`, routes.length ? `この建物で確かめる入り道：${routes.join("／")}` : "");
  }

  function render(scenario) {
    const fixed = App.building.fixed;
    renderStopCount(scenario);
    renderSceneContext();
    renderCaption();
    document.getElementById("model-fixed").replaceChildren(
      ...scenario.notes.map((line) => element("p", line, "fixed-note strong")),
      element("p", fixed.water_not_entry, "fixed-note strong"),
      element("p", App.building.sample.has_chief_engineer ? fixed.ordinary : fixed.ordinary_no_engineer, "fixed-note strong"),
      element("p", App.disclaimerText(), "fixed-note strong disclaimer-line"),
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
  const last = {};
  const SHEET_LABELS = {
    tepco: "東京電力の変圧器の部屋の扉と穴の浸水対策を東京電力パワーグリッドに照会し、申し入れる",
    hole: "マンション側の壁の穴をふさぐ（施工は電気工事の業者。理事や管理員は部屋に入らない。変圧器の部屋の穴には、だれも栓や止水材を入れない）",
    door: "マンション側の電気室の扉を防水扉にする（今の枠。変圧器の部屋の扉は含めない）",
    vent: "足元の換気口を高くする／電源車をつなげる受け口を 1 階につくる",
    panel: "ポンプのスイッチ盤を高くする（盤の下の端が低いと分かった場合）",
    power: "電源車をつなげる受け口を 1 階につくる",
  };

  // 主任技術者の方へ：水に浸かった機器で確かめること。使える／使えないの判定は出さず、判断する人を書く。
  // 数字（絶縁抵抗の値、日数、費用）は書かない。住民向けの面（おもて・3D・チャット）には出さない。
  const REUSE_LEAD = "水に浸かった機器で確かめること（この道具の作成者（電気主任技術者）の実務の目安で、出典で確かめた基準ではありません）。再び使えるかの判断には製造メーカーの技術者の派遣が必要で、排水の前に電気設備関係者が点検・測定・開閉器類の開放などの安全処置を行います（国交省・経産省ガイドライン本体 P.16）。";
  const REUSE_LEAD_NO_ENGINEER = "水に浸かった機器で確かめること（宛先：電気工事の業者とメーカーの技術者へ。この道具の作成者（電気主任技術者）の実務の目安で、出典で確かめた基準ではありません）。再び使えるかの判断には製造メーカーの技術者の派遣が必要で、排水の前に電気設備関係者が点検・測定・開閉器類の開放などの安全処置を行います（国交省・経産省ガイドライン本体 P.16）。";
  const REUSE_ROWS = [
    { key: "hv_panel", name: "高圧盤の筐体・母線・支持がいし", look: "洗浄と乾燥のあとの絶縁の試験の結果と、泥や塩分の残りをみる", who: "主任技術者とメーカーの技術者" },
    { key: "breaker", name: "真空遮断器・負荷開閉器・保護継電器・計器", look: "遮断の機構や基板に泥水が入ると、事故のときに遮断できなくなるおそれがある", who: "主任技術者とメーカーの技術者" },
    { key: "oil_tr", name: "油入変圧器", look: "絶縁油に水分が入っていないか", who: "主任技術者とメーカーの技術者" },
    { key: "mold_tr", name: "モールド変圧器", look: "洗浄と乾燥のあとの試験の結果をみる。計画的な更新もあわせて検討する", who: "主任技術者とメーカーの技術者" },
    { key: "pump", name: "ポンプと制御盤", look: "本体と制御盤を分けて確かめる。陸上に置くポンプは、モーターの巻線と軸受が浸かったかをみる", who: "ポンプの保守業者とメーカーの技術者（電気の側は主任技術者）", whoNoEngineer: "ポンプの保守業者とメーカーの技術者（電気の側は電気工事の業者）", always: true },
    { key: "ev", name: "エレベーター（底だけ／巻上機と制御盤まで）", look: "底（ピット）だけでも止まり、再開には保守会社の点検が要る。巻上機や制御盤まで浸かると、部品の交換や分解整備が要り、時間がかかることがある", who: "エレベーターの保守会社とメーカー", always: true },
    { key: "cable", name: "高圧ケーブル（引込み・構内）", look: "端末や接続部が浸かったときや、長く浸かったときは、ケーブルの状態に応じた絶縁の診断をする（日本電線工業会の資料）。浸かった時間と水の質でも変わる（実務の見立て）", who: "主任技術者（借室の中と東京電力側のケーブルは東京電力パワーグリッドが扱う）", underground: true },
  ];

  // 盤の中の湿気（主任技術者の方への欄。主任技術者のいない建物でも、点検や現地調査の着眼点として出す）。
  const ENGINEER_DAMP = "壁の穴をふさいでも、ケーブルの端や配管から盤の中に湿気や水分が入ることがあります。ケーブルの端末部と接続部の防水処理を、点検や現地調査で確かめてください（日本電線工業会の資料。毛細管や結露で入る経路は実務の見立て）。";

  // 水が引いたあと、管理組合がすること（A4 の裏）。
  const AFTER_LINES = [
    "記録写真：主任技術者（いない建物では電気工事業者）が入ってよいと言った範囲だけで、水の跡の高さと浸かった設備を撮り、保険の請求と見積りの材料にします。借室（東京電力の変圧器の部屋）と、水が残る部屋には入りません。",
    "費用の出どころ：共用部の復旧の費用が、管理組合のマンション保険（水災）で払われる条件を、管理会社に約款で確かめてもらいます。条件の例として、ある損害保険会社の約款では「床上浸水、または地盤面より45cmを超える浸水」が要件です（東京海上日動 マンション保険の約款）。個人で入る水災の補償が共用部には使えないことがある点は、NHK の番組（クローズアップ現代 2026/10/26 放送）の紹介文でも取り上げられています。",
    "泊まる先：断水や停電が長引いたとき、高齢の人や医療機器を使う人がどこに泊まるか、その費用を誰が持つかを、平時に理事会で話しておきます。",
  ];

  // 処置の表の「何をするか」に、折りたたみの補足を付ける（印刷では括弧書きで出す）。
  function withNote(text, note, title) {
    if (!note) return text;
    const box = element("span");
    const more = element("details", undefined, "sheet-fold screen-only");
    more.append(element("summary", title), element("span", note));
    box.append(element("span", text), more, element("span", `（${title}：${note}）`, "print-only sheet-fold-print"));
    return box;
  }

  // 「何が止まるか」の分かったことの欄。規模の重点の札は、行を増やさず先頭に付ける。
  function summaryCell(item) {
    const badges = item.badges || [];
    if (!badges.length) return item.summary;
    const box = element("span");
    badges.forEach((badge) => box.append(element("b", badge, "scale-tag"), " "));
    box.append(item.summary);
    if (item.scale_focus?.length) box.append(element("small", `（重点：${item.scale_focus.join("／")}）`, "scale-focus"));
    return box;
  }

  // おもての「止まるもの」の欄。規模の重点の札は名前の後ろに付け、行を増やさない（重点の中身は別紙の表）。
  function labelCell(item) {
    const badges = item.badges || [];
    if (!badges.length) return item.label;
    const box = element("span", item.label);
    badges.forEach((badge) => box.append(" ", element("b", badge, "scale-tag")));
    return box;
  }

  // 「更新と一緒」の段は1行にまとめる。
  function renewalRow(items, region) {
    const names = items.map((m) => m.label.replace(/（設備の更新に合わせて）$/, ""));
    const decisions = [...new Set(items.map((m) => m.decision))].join("／");
    const accounts = [...new Set(items.map((m) => m.account))].join("／");
    // 印が手ごとに違うときは、桁の欄と同じく手の順に並べる。
    const each = items.map((m) => SimPanel.markFor(m, region)[0]);
    const marks = new Set(each).size === 1 ? each[0] : each.join("／");
    // 桁は手の順に1行ずつ（「／」でつなぐと桁の列が広がりすぎるため）。
    const ranges = element("span");
    items.forEach((m) => ranges.append(element("span", m.range, "range-part")));
    return ["更新と一緒", `設備の更新に合わせて：${names.join("／")}`, `${decisions}・${accounts}`, ranges, "—", marks];
  }

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
    // 住所は町丁まで。番地はピンの位置から来ることがあり、建物の住所とは限らないため（2026-11-04）。
    const label = `住所：${sample.name}／${townLabel(App.locationState.site.label)}${sample.custom ? "（図と設備の形は見本から借りています）" : "（建物は架空）"}`;
    document.getElementById("sheet-address").textContent = label;
    document.getElementById("sheet-basis-address").textContent = label;
    // 対象の範囲の一行（F-035、web/index.html の #sheet-basis .scope-line）の直後に、区域の外の一行を一度だけ足す（F-049）。
    const scopeLine = document.querySelector("#sheet-basis .scope-line");
    if (scopeLine && !document.querySelector("#sheet-basis .scope-outside")) {
      scopeLine.after(element("p", "東京電力パワーグリッドの区域の外では、借室の照会先はその地域の電力会社（一般送配電事業者）になるので、この道具の文はそのままでは当てはまりません。区域に入る都道府県の一覧は、まだ確かめていません。", "sheet-pointer scope-outside"));
    }
    document.getElementById("sheet-memo-address").textContent = label;
    document.getElementById("sheet-detail-address").textContent = label;
    document.getElementById("sheet-engineer-address").textContent = label;

    document.querySelectorAll(".disclaimer li:first-child").forEach((node) => {
      node.textContent = App.disclaimerText();
    });

    const top = document.getElementById("sheet-top");
    top.replaceChildren(element("p", building.top_line.lead, "top-lead"));
    // 何が分かれば答えが出るか・誰に頼むか（画面の②の頭と同じ）。
    if ((building.top_line.steps || []).length) top.append(answerSteps(building, "answer-steps sheet-steps"));
    const land = landChips(App.locationState.location.rows).map((chip) => chip.text).join("／");
    top.append(element("p", `この土地（${land}）× 大雨（線状降水帯）＝ 電気室やポンプに水が入ると、水と電気が止まるおそれ`, "top-notes strong"));
    if (building.direction_line) top.append(element("p", building.direction_line, "top-notes strong"));
    // 一行目の根拠と補足（画面では「根拠と補足」の折りたたみ）は、別紙の先頭へ移す。
    const topNotes = document.getElementById("sheet-detail-notes");
    topNotes.replaceChildren();
    if (building.top_line.notes.length) {
      const notes = element("p", building.top_line.notes.join(""), "top-notes");
      notes.dataset.polish = "top";
      topNotes.append(notes);
    }
    // A4 と共有の画面だけに出す文（千葉の見通し）。Claude の整形に渡さないよう data-polish を付けない。
    (building.top_line.a4_notes || []).forEach((line) => topNotes.append(element("p", line, "top-notes a4-note")));
    if (topNotes.childElementCount) topNotes.prepend(element("h3", "一行目の根拠と補足"));

    const equipmentBelow = [];
    if (building.heights?.length) {
      equipmentBelow.push(element("p", `高さの入力値（入れた値をそのまま出しています。浸かるかは計算していません）：${building.heights.map((h) => `${h.label} ${h.text}`).join("／")}`, "sheet-pointer"));
    }
    if (building.scale?.shown) {
      equipmentBelow.push(element("p", `規模（${building.scale.label}）の「この規模で重点」の札：${building.scale.note}${building.scale.out_of_scope}`, "sheet-pointer"));
    }
    // おもては「止まるもの・判定・誰が確かめるか」の1行ずつにし、分かったことと高さ・規模の一行は別紙へ移す（表裏1枚に収めるため）。
    const frontEquipment = slim(
      ["止まるもの", "判定", "誰が確かめるか"],
      building.equipment.map((item) => [labelCell(item), verdictTag(item.verdict, item.verdict_label), `${item.confirm_short || "—"}${item.memo_no ? `（メモ${item.memo_no}）` : ""}`]),
    );
    frontEquipment.classList.add("equipment-front");
    document.getElementById("sheet-equipment").replaceChildren(frontEquipment);
    const detailEquipment = slim(
      ["止まるもの", "判定", "分かったこと"],
      building.equipment.map((item) => [item.label, verdictTag(item.verdict, item.verdict_label), summaryCell(item)]),
    );
    detailEquipment.classList.add("equipment-detail");
    document.getElementById("sheet-detail-equipment").replaceChildren(detailEquipment, ...equipmentBelow);

    // 段の順に並べ、電源車の受け口は A4 では出さない。「更新と一緒」の段は1行にまとめる。
    const region = sample.subsidy;
    const measures = SimPanel.byTier(building.measures.filter((m) => m.key !== "power"));
    const renewal = measures.filter((m) => m.tier === "更新と一緒");
    // 表の行は、別紙の表（6列）とおもての表（先頭の4列）で別々に作る（同じ要素を二つの表に入れないため）。
    const measureRows = (front) => {
      const rows = [];
      measures.forEach((m) => {
        if (m.tier === "更新と一緒") {
          if (m === renewal[0]) rows.push(renewalRow(renewal, region));
          return;
        }
        rows.push([
          m.tier,
          front ? SHEET_LABELS[m.key] || m.label : withNote(SHEET_LABELS[m.key] || m.label, m.note, "止水材の使い分け"),
          `${m.decision.replace("（建物の規約と予算による）", "＊").replace("理事会で申し入れる。工事になるときの決め方は内容が分かってから", "理事会で申し入れる。工事は内容が分かってから")}・${m.account}`,
          m.range,
          m.owner || "—",
          SimPanel.markFor(m, region)[0],
        ]);
      });
      return front ? rows.map((cells) => cells.slice(0, 4)) : rows;
    };
    // おもては「いつ・何をするか・決め方・桁」の4列。担当・補助の列と止水材の使い分け、規約と予算の長い補足は別紙へ移す。
    const frontMeasures = slim(["いつ", "何をするか", "決め方・お金の出どころ", "桁"], measureRows(true));
    frontMeasures.classList.add("measure-front");
    document.getElementById("sheet-measures").replaceChildren(
      frontMeasures,
      // おもてから別紙へ移したものの案内も、この一行にまとめる。
      element("p", "＊建物の規約と予算による（条件は別紙）。別紙には、一行目の根拠と補足、止まるものごとの分かったこと、担当と補助の列もあります。", "sheet-pointer front-footer"),
    );
    const measureTable = slim(["いつ", "何をするか", "決め方・お金の出どころ", "桁", "担当", "補助"], measureRows(false));
    measureTable.classList.add("measure-table");
    document.getElementById("sheet-detail-measures").replaceChildren(
      measureTable,
      ...(building.equipment.find((item) => item.key === "tr").verdict !== "risk"
        ? [element("p", "東京電力の変圧器の部屋が地下にあり、そこまで水が来るおそれがあると図面と立地で確かめられたら、扉と穴の浸水対策を東京電力パワーグリッドに申し入れます。", "sheet-pointer")]
        : []),
      element("p", "＊建物の規約と予算による。総会から任されている、規約に定めがある、その年の予算に入っている、のどれかに当たるときのことです。予算に入っているだけで足りるかは規約によるので、当たるかを管理会社に規約・予算書・議事録で確かめてもらいます。当たらなければ、総会で決めるか、総会から理事会に任せてもらいます。管理費か修繕積立金かも確かめます。屋上移設（数千万〜1億円超）と枠ごとの防水扉（300万円〜）は総会の特別決議です。", "sheet-pointer"),
      element("p", "補助の列は、この住所の制度で当たりうるかの印です。申請を勧めるものではありません。条件は、画面の③の折りたたみ「費用の桁と補助・専門家への相談」にあります。", "sheet-pointer"),
    );

    const reading = App.locationState.location.reading;
    const center = reading.elevation.points[0].elevation_m;
    const surge = reading.hazards.find((h) => h.key === "storm_surge");
    const tide = (center !== null && center <= 5) || surge.status === "color";
    const hasEngineer = sample.has_chief_engineer;
    // 建物の位置で読めたときだけ「建物の位置では未確認」の添え書きを外す。代表点のときは今の文のまま。
    const atBuilding = App.locationState.site.basis === "building";
    const tideLead = atBuilding ? "低い土地か高潮の色がかかる地点なので、" : "低い土地か高潮の色がかかる地点なので（建物の位置では未確認）、";
    // 雨水の導入管の止水弁は、貯留槽と止水弁がともにある建物だけ、満潮の分岐の中に足す（時間の数字は持ち込まない）。
    const valve = building.rain_tank_valve?.show ? building.rain_tank_valve.text : "";
    const rain = [
      "警戒レベル3：車を上へ。決議は要らず、住民が今日からできる対策です。",
      `警戒レベル4：止水板と土のうを出します。誰が出すかを先に決めます。${tide ? `${tideLead}満潮の2時間前までに出します（仮の目安。満潮と重なると排水が遅れると考えられ、時刻は潮位表で確かめます）。${valve}` : ""}`,
      // 三行目はサーバーの building.rain.third（下の固定の文と同じ文）を使う。無いときは固定の文。
      building.rain?.third ||
      (sample.engineer_unsure
        ? "電気の部屋や変圧器の部屋に水が来そうになったら：管理員か理事長が東京電力パワーグリッドと管理会社と、いれば主任技術者に連絡します。部屋に入りません。在宅で医療機器を使う人へ先に知らせ、全戸へ排水しないよう放送します。"
        : hasEngineer
        ? "電気の部屋に水が来そうになったら：管理員か理事長が主任技術者に連絡します。操作は主任技術者の指示で行い、電気の部屋には、水が来る前も後も、主任技術者の同行なしに入りません。在宅で医療機器を使う人へ先に知らせ、止めると同時に全戸へ排水しないよう放送します。"
        : "盤の部屋や変圧器の部屋に水が来そうになったら：管理員か理事長が東京電力パワーグリッドと管理会社に連絡します。部屋に入りません。在宅で医療機器を使う人へ先に知らせ、全戸へ排水しないよう放送します。"),
      ...(building.rain?.extra || []),
    ];
    last.rain = rain;
    const list = element("ul", undefined, "sheet-list");
    rain.forEach((line) => list.append(element("li", line)));
    document.getElementById("sheet-rain").replaceChildren(
      list,
      element("p", "合図は自治体や気象庁が出す警戒レベルです。予報ではありません。", "sheet-pointer"),
    );

    const scenario = building.scenarios["3:plate"];
    const during = element("ul", undefined, "sheet-list");
    last.during = [`水が来た当日：${scenario.table[scenario.table.length - 1].cells[1]}`, `水が引いた翌朝：${scenario.table[scenario.table.length - 1].cells[2]}`];
    last.during.forEach((line) => during.append(element("li", line)));
    // 大雨の手順の三点セットは、おもてから裏の「水が来ている間」の下へ移す（表裏1枚に収めるため）。
    document.getElementById("sheet-during").replaceChildren(during, ...(building.rain?.set_of_three ? [element("p", building.rain.set_of_three, "sheet-pointer strong")] : []));

    last.days = `給水・排水の制御盤は製作に約2か月（建築設備技術者協会の報告書）。供給用変圧器${hasEngineer ? "・受電設備" : ""}が浸かった場合、排水開始から仮復旧まで4〜7日程度（経産省の検討会資料、一般的な目安）。${hasEngineer ? "受変電の特注品は復旧に1年以上の場合も（同協会の報告書）。" : ""}武蔵小杉は停電5日・断水8日・トイレ11日、本復旧6〜8か月（建築設備技術者協会の調査など。ほかの建物の例）。`;
    document.getElementById("sheet-days").replaceChildren(
      element("p", building.fixed.timeline_top, "sheet-text strong"),
      element("p", last.days, "sheet-text"),
    );

    const after = document.getElementById("sheet-after");
    if (after) {
      const afterList = element("ul", undefined, "sheet-list");
      AFTER_LINES.forEach((line) => afterList.append(element("li", line)));
      after.replaceChildren(afterList);
    }

    // 新しく足した復電・検電・水没機器の文は、主任技術者の有無が書類で分かっている建物だけ（免責の1行目と同じ条件）。
    const engineerSure = hasEngineer && !sample.engineer_unsure;
    const engineerLines = hasEngineer
      ? [
          "受電設備内の検電・残留電荷の放電・短絡接地は、水が引いて入室できる状態になり、電源側が切れていることを確かめてから行います（労働安全衛生規則第339条）。",
          "水が引いた直後に遮断器を入れません。泥と塩分が残ったまま通電すると短絡のおそれがあり、波及事故の防止にも関わります。",
          "電気室に入らずに遮断できる手段があるかと、受電設備側の最初の開閉器の位置を、単線結線図で事前に確かめてください。",
          "どの水位で誰が連絡して電気を止めるかの事前の合意を、保安規程の変更にするか覚書にするかは確かめてください。",
          sample.underground_feed ? "地中引込の建物なので、高圧ケーブルの敷設年と点検の記録、大雨や浸水のあとに行う確認結果を確かめてください。一度の冠水で劣化がどこまで進むかは、まだ確かめていません。歩道ぎわの蓋は開けないでください。" + "点検に含まれるか、別の診断になるかは、保安管理業務の契約によります。ケーブルと管路の所有は、単線結線図と、東京電力パワーグリッドへの書面での確認で確かめてください。" : "",
          engineerSure && "太陽光発電・蓄電池や非常用発電機がある建物では、逆充電や直流側の充電が残ることがあるので、検電は負荷側全体で行います（逆充電と直流側の部分は実務の見立て）。",
          engineerSure && "排水は、東京電力パワーグリッドの切り離しと主任技術者の開放を確かめてから始めます。入室したら検電・放電・短絡接地を先に済ませ、それまで設備に触れません。",
          engineerSure && "電気を戻す前に、借室（東京電力の変圧器の部屋）は東京電力パワーグリッドが、マンション側の受電設備は主任技術者が確かめます。マンション側の設備を使い直してよいかは、法令の絶縁抵抗の下限を測って終わりにせず、機器の状態をみて主任技術者が判断します。洗浄や部品交換で使い続けられるかはメーカーの技術者に確かめ、保護継電器の動作試験の合格もあわせて確かめます。どれか一つでも確かめられていなければ、電気を戻しません。",
          ENGINEER_DAMP,
          "借室の穴や管路には、だれも栓や非硬化の止水材を入れません。壁の穴の施工は、停電の要否・離隔・止水材を電気工事業者と決めてから行います。",
          "防水扉や換気口のかさ上げは、施錠・立入禁止の表示・防火・換気や放熱を損なわないか確かめてください。",
        ]
      : [
          "この建物にマンション側の受電設備と電気主任技術者はありません（書類の記載）。共用部の電気代の明細で契約種別が低圧か、同じ敷地に発電設備がないかを、依頼メモ①で確かめます。",
          "盤の部屋の現地調査は電気工事業者が立ち会い、防水業者は目で見るだけとします。穴をふさぐ前に、停電の要否、盤との離隔、止水材を電気工事業者と決めます。",
          "借室の穴や管路には、だれも栓や非硬化の止水材を入れません。",
          ENGINEER_DAMP,
        ];
    if (sample.engineer_unsure) engineerLines.unshift("マンション側の受電設備と電気主任技術者の有無は、まだ書類で確かめていません。点検報告書か保安規程で確かめてください。");
    const engineerList = element("ul", undefined, "sheet-list");
    engineerLines.filter(Boolean).forEach((line) => engineerList.append(element("li", line)));
    // 水に浸かった機器の表。主任技術者のいない建物は、ポンプとエレベーターの行だけ。高圧ケーブルは地中引込の建物だけ。
    const reuseRows = REUSE_ROWS.filter((row) => (engineerSure || row.always) && (!row.underground || sample.underground_feed)).map((row) => [
      row.name,
      row.look,
      engineerSure ? row.who : row.whoNoEngineer || row.who,
    ]);
    const reuseTable = slim(["機器", "浸かったときに確かめること・理由", "判断する人"], reuseRows);
    reuseTable.classList.add("reuse-table");
    document.getElementById("sheet-engineer").replaceChildren(
      engineerList,
      element("p", engineerSure ? REUSE_LEAD : REUSE_LEAD_NO_ENGINEER, "sheet-pointer reuse-lead"),
      reuseTable,
    );

    const memo = document.getElementById("sheet-memo-body");
    memo.replaceChildren();
    building.memos.forEach((section) => {
      memo.append(element("h3", `依頼メモ${section.label}　${section.title}`));
      const items = element("ul", undefined, "sheet-list");
      section.items.forEach((item, i) => {
        const line = element("li");
        const textNode = element("span", item.text);
        textNode.dataset.polish = `memo-${building.memos.indexOf(section)}-${i}`;
        // 番号（①-1 など）は整形で消えないよう、polish の span の外に置く。
        if (item.no) line.append(element("b", item.no, "memo-no"), " ");
        line.append(element("strong", `${item.from}：`), textNode);
        items.append(line);
      });
      if (!section.items.length) items.append(element("li", "今はありません。"));
      memo.append(items);
    });
    // おもての「何が止まるか」の行と、依頼メモの番号の対照表。
    const xref = building.equipment.filter((item) => item.memo_no);
    if (xref.length) {
      memo.append(element("h3", "対照表：おもての行 → 依頼メモの番号"));
      memo.append(element("p", xref.map((item) => `${item.label} → ${item.memo_no}`).join("／"), "sheet-text memo-xref"));
    }
    memo.append(element("p", "追加の費用がかかるかは、管理委託契約と保守の契約によります。", "sheet-pointer"));
    ["sheet-detail", "sheet-memo", "sheet-engineer-memo"].forEach((id) => {
      document.getElementById(id).hidden = false;
    });
  }

  function shareData() {
    const building = App.building;
    const { sample } = building;
    // 規模の重点の札とメモの番号は、おもての行（equipment）にだけある。立地の行では空のまま。
    const toCard = (row) => ({ verdict: row.verdict, verdict_label: row.verdict_label, label: row.label, text: row.headline, confirm: row.confirm_by, badges: row.badges || [], scale_focus: row.scale_focus || [], memo_no: row.memo_no || "" });
    // 主任技術者の欄と表の下の一行は、建物ごとの出し分けが render の中にあるので、描いた A4 から読む（同じ条件を二度書かない）。
    const texts = (selector) => [...document.querySelectorAll(selector)].map((node) => node.textContent);
    const region = sample.subsidy;
    const trRisk = building.equipment.find((item) => item.key === "tr")?.verdict === "risk";
    return {
      name: sample.name,
      address: `${townLabel(App.locationState.site.label)}${sample.custom ? "" : "（建物は架空）"}`,
      question: "水が引いた翌朝、この建物は何日で水が出るか",
      lead: building.top_line.lead,
      // 共有の画面（view.html）は notes を最上段に出すので、A4 だけの文（a4_notes）をここで後ろに足す。
      notes: [...building.top_line.notes, ...(building.top_line.a4_notes || [])].join(""),
      direction: building.direction_line,
      location: App.locationState.location.rows.map(toCard),
      equipment: building.equipment.map(toCard),
      // 高さの入力値と規模の一行（A4 の別紙「何が止まるか（分かったこと）」の表の下）。
      equipment_notes: texts("#sheet-detail-equipment > p"),
      // 「担当」「補助」の列と、穴の行の「止水材の使い分け」の補足（A4 の処置の表と同じ値）。
      measures: SimPanel.byTier(building.measures).map((m) => ({ tier: m.tier, label: m.label, decision: m.decision, account: m.account, range: m.range, owner: m.owner || "—", mark: SimPanel.markFor(m, region)[0], note: m.note || "" })),
      measure_tepco: trRisk ? "" : "東京電力の変圧器の部屋が地下にあり、そこまで水が来るおそれがあると図面と立地で確かめられたら、扉と穴の浸水対策を東京電力パワーグリッドに申し入れます。",
      // A4 の別紙の補助の一行の前の二文（共有の画面には③の折りたたみ「費用の桁と補助・専門家への相談」がないので、その案内の文は入れない）。
      mark_note: "補助の列は、この住所の制度で当たりうるかの印です。申請を勧めるものではありません。",
      set_of_three: building.rain?.set_of_three || "",
      measure_note: "「理事会で決められる場合がある」は、総会から任されている、規約に定めがある、その年の予算に入っている、のどれかに当たるときのことです。予算に入っているだけで足りるかは規約によるので、当たるかを管理会社に規約・予算書・総会の議事録で確かめてもらいます。当たらなければ、総会で決めるか、総会から理事会に任せてもらいます。",
      rain: last.rain,
      during: last.during,
      days_top: building.fixed.timeline_top,
      days: last.days,
      // A4 の裏に足した欄。図面とチャットは共有に入れない。
      after: AFTER_LINES,
      engineer: {
        lines: texts("#sheet-engineer > ul > li"),
        reuse_lead: texts("#sheet-engineer .reuse-lead").join(""),
        reuse_head: texts("#sheet-engineer .reuse-table thead th"),
        reuse_rows: [...document.querySelectorAll("#sheet-engineer .reuse-table tbody tr")].map((tr) => [...tr.cells].map((td) => td.textContent)),
      },
      // 対象の範囲の一行（A4 の別紙）と、区域の外の一行。
      scope: texts("#sheet-basis .scope-line, #sheet-basis .scope-outside"),
      // 依頼メモの番号を、共有の画面でも項目の頭に出す。
      memos: building.memos.map((section) => ({ ...section, items: section.items.map((item) => ({ ...item, from: item.no ? `${item.no} ${item.from}` : item.from })) })),
      // 免責と注意書きは、ページの一番下の disclaimers に一度だけ出す。
      board: building.exits.board,
      procedure: `${building.exits.procedure}\n\n${building.exits.procedure_actions}`,
      disclaimers: [
        App.disclaimerText(),
        "浸水実績は自治体の公表データを独自に集計・加工したもので、自治体の公式証明ではない",
        "本シートは予報ではなく、現時点の静的な整理である",
        "費用は桁の目安で、保安法人・工事業者の見積りに置き換えること",
      ],
    };
  }

  function applyPolish(polished) {
    document.querySelectorAll("[data-polish]").forEach((node) => {
      const text = polished[node.dataset.polish];
      if (text) node.textContent = text;
    });
  }

  return { render, shareData, applyPolish };
})();
