"use strict";

// 第4段階の試算と、相談の文書。費用は桁の帯で足し、円の金額は見積り額が入ったときだけ計算する。
const SimPanel = (() => {
  const BANDS = { 4: "数万円", 5: "数十万円", 6: "数百万円", 7: "数千万円", 8: "1億円超" };
  const MARKS = {
    yes: ["対象になりうる", 1],
    with_plate: ["止水板などと併せるときに限る", 0],
    no: ["対象外になりうる", 0],
    unknown: ["未確認", 0],
    none: ["—", 0],
  };
  let state = { checked: new Set(), estimates: {}, region: null };

  function reset() {
    state = { checked: new Set(), estimates: {}, region: App.building.sample.subsidy };
  }

  function bandText(checked) {
    const banded = checked.filter((m) => m.low !== null);
    if (!banded.length) return null;
    const low = Math.max(...banded.map((m) => m.low));
    const high = Math.max(...banded.map((m) => m.high));
    return low === high ? BANDS[low] : `${BANDS[low].replace("円", "")}〜${BANDS[high]}`;
  }

  // 段の順。サーバーが後から足した手（pump_check など）は末尾に来るので、段ごとに並べ直す（同じ段の中の順は保つ）。
  const TIER_ORDER = ["今すぐ", "工事が要る", "更新と一緒"];
  function byTier(measures) {
    const rank = (m) => (TIER_ORDER.includes(m.tier) ? TIER_ORDER.indexOf(m.tier) : TIER_ORDER.length);
    return measures
      .map((m, i) => [m, i])
      .sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1])
      .map(([m]) => m);
  }

  // 補助の印。A4 の紙（手を選ばない）では checked を渡さず、制度の条件の文をそのまま出す。
  function markFor(measure, region, checked) {
    if (!checked) {
      if (region === "tokyo" || region === "chiba") return MARKS[measure[region]] || MARKS.unknown;
      return MARKS.unknown;
    }
    if (region === "tokyo") {
      if (measure.tokyo === "with_plate") {
        const joined = checked.some((m) => m.tokyo === "yes");
        return joined ? ["止水板などと併せる場合に対象になりうる", 1] : ["それだけでは対象外になりうる", 0];
      }
      return MARKS[measure.tokyo];
    }
    if (region === "chiba") return MARKS[measure.chiba];
    return MARKS.unknown;
  }

  function subsidyAmount(eligible, region, alreadyUsed) {
    if (region === "tokyo") return Math.max(0, Math.min(Math.floor((eligible * 2) / 3 / 1000) * 1000, 8330000 - alreadyUsed));
    if (region === "chiba") return Math.min(Math.floor(eligible / 2 / 100) * 100, 750000);
    return 0;
  }

  const yen = (value) => `${value.toLocaleString("ja-JP")}円`;

  // 末尾の括弧書きを、太字の名前と小さな補足に分ける。
  function splitLabel(label) {
    const found = label.match(/^(.+)（([^（）]+)）$/);
    return found ? { name: found[1], note: found[2] } : { name: label, note: "" };
  }

  function namedCell(label) {
    const { name, note } = splitLabel(label);
    const cell = element("td");
    cell.append(element("strong", name, "sim-name"));
    if (note) cell.append(element("small", note, "sim-note"));
    return cell;
  }

  function renderCautions(box, cautions) {
    if (!cautions.length) return;
    box.append(element("p", cautions[0], "fixed-note strong"));
    if (cautions.length === 1) return;
    const more = element("details", undefined, "fold");
    more.open = Boolean(state.cautionsOpen);
    more.addEventListener("toggle", () => {
      state.cautionsOpen = more.open;
    });
    more.append(element("summary", "補助の条件をすべて開く"));
    cautions.slice(1).forEach((line) => more.append(element("p", line)));
    box.append(more);
  }

  function renderResult(box) {
    const building = App.building;
    const measures = building.measures.filter((m) => state.checked.has(m.key));
    const region = state.region;
    const subsidy = building.subsidies[region];
    box.replaceChildren();

    const band = bandText(measures);
    box.append(element("p", "選んだ手の合計の桁", "sim-kicker"));
    box.append(element("p", band || (measures.length ? "足せる桁はありません" : "手を選ぶと出ます"), band ? "sim-band" : "sim-band sim-band-empty"));
    measures
      .filter((m) => m.open_ended)
      .forEach((m) => box.append(element("p", `上限のない手：${splitLabel(m.label).name}（${m.range}）。合計の桁には入れていません。`, "hint")));

    const decisions = [...new Set(measures.map((m) => m.decision))];
    if (decisions.length) {
      box.append(element("p", "決める場", "sim-kicker"));
      const list = element("ul", undefined, "sim-decisions");
      decisions.forEach((line) => list.append(element("li", line)));
      box.append(list);
    }

    const amountOf = (m) => Math.max(0, Number(state.estimates[m.key]) || 0);
    const total = measures.reduce((sum, m) => sum + amountOf(m), 0);
    const eligible = measures.reduce(
      (sum, m) => sum + (markFor(m, region, measures)[1] ? amountOf(m) : 0),
      0,
    );
    box.append(element("p", "補助の計算の例", "sim-kicker"));
    if (total > 0) {
      const amount = subsidyAmount(eligible, region, Number(state.used) || 0);
      const table = element("table", undefined, "slim-table sim-table");
      const body = table.createTBody();
      const add = (name, value) => {
        const row = body.insertRow();
        row.append(element("th", name), element("td", value));
      };
      add("補助を使わない場合の負担", yen(total));
      add("対象になりうる額", yen(eligible));
      if (region === "tokyo" || region === "chiba") {
        add("補助の計算の例", yen(amount));
        add("補助を使う場合の負担の計算の例", yen(total - amount));
      }
      box.append(
        table,
        element("p", "計算の例で、交付額ではありません。見積り額がそのまま補助対象経費になるとは限りません。消費税の扱いも、まだ確かめていません。", "fixed-note strong"),
      );
    } else {
      box.append(element("p", "手を選んで見積り額を入れるか、見本の金額のボタンを押すと出ます。", "hint"));
    }
    box.append(element("p", "費用は桁の目安で、保安法人・工事業者の見積りに置き換えること", "fixed-note strong"));
    box.append(element("p", "調査費用：見積りで確かめる", "sim-survey"));
    box.append(element("p", "補助の条件", "sim-kicker"));
    box.append(element("p", subsidy.rate_label, "sheet-text"));
    if (region !== building.sample.subsidy && region !== "none") {
      const name = subsidy.label.replace(/（.*$/, "");
      box.append(element("p", `この住所の制度ではありません（${name}の計算例）`, "fixed-note emphasis"));
    }
    renderCautions(box, subsidy.cautions);
    box.append(element("p", "申請を勧めるものではありません。使うかどうかは管理組合が決めます。", "hint"));
  }

  function render() {
    const building = App.building;
    const root = document.getElementById("sim-body");
    root.replaceChildren();
    const controls = element("div", undefined, "sim-controls");
    const select = document.createElement("select");
    select.id = "subsidy-select";
    Object.entries(building.subsidies).forEach(([key, item]) => {
      const option = element("option", item.label);
      option.value = key;
      option.selected = key === state.region;
      select.append(option);
    });
    const selectLabel = element("label", "補助の地域");
    selectLabel.htmlFor = "subsidy-select";
    const sampleButton = element("button", "見本の金額を入れる（架空。見積りではありません）");
    sampleButton.type = "button";
    controls.append(selectLabel, select, sampleButton);
    if (state.region === "tokyo") {
      const used = document.createElement("input");
      used.type = "number";
      used.min = "0";
      used.id = "used-input";
      used.value = state.used || "";
      used.placeholder = "0";
      const usedLabel = element("label", "調査・企画で既に受けた補助額（円）");
      usedLabel.htmlFor = "used-input";
      used.addEventListener("input", () => {
        state.used = used.value;
        renderResult(result);
      });
      controls.append(usedLabel, used);
    }
    const left = element("div", undefined, "sim-left");
    left.append(controls);

    const table = element("table", undefined, "slim-table sim-table");
    const header = table.createTHead().insertRow();
    ["選ぶ", "何をするか", "決め方とお金", "桁", "補助", "見積り額（円）"].forEach((name) => header.append(element("th", name)));
    const body = table.createTBody();
    const result = element("div", undefined, "sim-result");

    const rows = [];
    let tier = null;
    byTier(building.measures).forEach((measure) => {
      if (measure.tier !== tier) {
        tier = measure.tier;
        const heading = element("th", tier);
        heading.colSpan = 6;
        const line = body.insertRow();
        line.className = "sim-tier";
        line.append(heading);
      }
      const row = body.insertRow();
      const check = document.createElement("input");
      check.type = "checkbox";
      check.dataset.key = measure.key;
      check.setAttribute("aria-label", measure.label);
      check.checked = state.checked.has(measure.key);
      row.insertCell().append(check);
      const decision = element("td");
      decision.append(element("span", measure.decision), element("small", measure.account, "sim-note"));
      if (measure.owner) decision.append(element("small", `担当：${measure.owner}`, "sim-note sim-owner"));
      row.append(namedCell(measure.label), decision, element("td", measure.range, "sim-range"));
      const markCell = row.insertCell();
      const estimateCell = row.insertCell();
      const estimate = document.createElement("input");
      estimate.type = "number";
      estimate.min = "0";
      estimate.setAttribute("aria-label", `${measure.label}の見積り額`);
      estimate.value = state.estimates[measure.key] || "";
      estimate.addEventListener("input", () => {
        state.estimates[measure.key] = estimate.value;
        renderResult(result);
      });
      estimateCell.append(estimate);
      check.addEventListener("change", () => {
        if (check.checked) state.checked.add(measure.key);
        else state.checked.delete(measure.key);
        refresh();
      });
      rows.push({ measure, markCell, estimate });
    });

    function refresh() {
      const checked = building.measures.filter((m) => state.checked.has(m.key));
      rows.forEach(({ measure, markCell }) => {
        markCell.textContent = markFor(measure, state.region, checked)[0];
      });
      renderResult(result);
    }

    select.addEventListener("change", () => {
      state.region = select.value;
      render();
    });
    sampleButton.addEventListener("click", () => {
      rows.forEach(({ measure, estimate }) => {
        if (state.checked.has(measure.key)) {
          state.estimates[measure.key] = measure.sample_yen;
          estimate.value = measure.sample_yen;
        }
      });
      renderResult(result);
    });

    const scroll = element("div", undefined, "table-scroll");
    scroll.append(table);
    left.append(scroll);
    const grid = element("div", undefined, "sim-grid");
    grid.append(left, result);
    root.append(grid);
    refresh();
  }

  async function consult() {
    const body = document.getElementById("consult-body");
    body.replaceChildren(element("p", "文書を作っています。", "hint"));
    const response = await fetch("/api/consult", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sample_id: App.sampleId,
        answers: App.answers,
        label: App.locationState.site.label,
        confirmed: App.confirmed,
        document_read: App.documentRead,
        checked: [...state.checked],
        subsidy: state.region,
        location_rows: App.locationState.location.rows,
      }),
    });
    const documents = await response.json();
    body.replaceChildren();
    body.append(
      element(
        "p",
        documents.source === "claude" ? "Claude が、立地、確かめる場所、選んだ手、補助の条件から作りました。" : documents.notice,
        documents.source === "claude" ? "hint" : "notice",
      ),
    );
    body.append(element("h3", "管理組合から各窓口へ送る3文書（コピー・メール作成）", "consult-title"));
    const sets = element("div", undefined, "consult-docs");
    [
      ["① 現地調査・見積もり仕様カルテ", documents.karte],
      ["② 交付決定前に守るべき手続きの段取り", documents.schedule],
      ["③ 管理会社・保安法人・公的相談窓口への依頼文", documents.letter],
    ].forEach(([title, text]) => {
      const section = element("section", undefined, "doc");
      const copy = element("button", "コピー");
      copy.type = "button";
      copy.addEventListener("click", () => navigator.clipboard?.writeText(text));
      section.append(element("h3", title), copy, element("pre", text));
      sets.append(section);
    });
    body.append(sets, renderRecipients(documents.letter));
    body.append(
      element("p", "依頼文ができました。送るのは管理組合です。この道具から外へは送っていません。業者の紹介はしません。", "fixed-note strong"),
    );
    // 将来の形は、札を表面に、完了イメージ（押せない静的な絵）を折りたたみに入れる。
    body.append(element("p", "将来の形：手続きも含めて相談できる窓口（デモ画面：実際には送信していません。紹介料は取りません）", "future-tag"));
    const future = element("details", undefined, "fold");
    future.append(
      element("summary", "補足：将来の窓口"),
      element("p", "手続きも含めて相談できる窓口は、将来の構想です。今は送信の機能を持たず、紹介料も取りません。"),
      futureMock(),
    );
    body.append(future);
  }

  function futureMock() {
    const box = element("div", undefined, "future-mock");
    box.setAttribute("aria-label", "将来の画面の完了イメージ（押せません）");
    const to = document.createElement("input");
    to.type = "text";
    to.disabled = true;
    to.value = "宛先（管理組合が選びます）";
    to.setAttribute("aria-label", "宛先（将来の画面。入力できません）");
    const send = element("button", "送信");
    send.type = "button";
    send.disabled = true;
    box.append(element("p", "完了イメージ", "future-mock-head"), to, send, element("p", "この画面は将来の姿で、今は何も送っていません。", "future-mock-note"));
    return box;
  }

  function renderRecipients(letter) {
    const building = App.building;
    const box = element("section", undefined, "doc");
    box.append(element("h3", "宛先は管理組合が選びます"));
    const list = element("ul", undefined, "recipients");
    const subject = encodeURIComponent("調査と見積りのご相談");
    const mailBody = encodeURIComponent(letter);
    const item = (label, note, href, text) => {
      const line = element("li");
      line.append(element("strong", label), ` ${note} `);
      if (href) {
        const link = element("a", text);
        link.href = href;
        if (href.startsWith("http")) {
          link.target = "_blank";
          link.rel = "noopener";
        }
        line.append(link);
      }
      list.append(line);
    };
    item("管理会社", "", `mailto:?subject=${subject}&body=${mailBody}`, "メールを作る");
    if (building.sample.has_chief_engineer) {
      item("今の保安法人", "委託の範囲は点検と助言までで、工事は別の契約です。", `mailto:?subject=${subject}&body=${mailBody}`, "メールを作る");
    }
    item("公益財団法人マンション管理センター", "建物・設備の維持管理の相談。修繕の個別具体的な助言はしていません。", "https://www.mankan.or.jp/06_consult/tel.html", "公式ページ");
    const region = App.building.sample.subsidy;
    if (region === "tokyo") item("東京都 分譲マンション総合相談窓口", "", "https://www.mansion-tokyo.metro.tokyo.lg.jp/kanri/01sougou-madoguchi/", "公式ページ");
    if (region === "chiba") item("千葉市 分譲マンション相談会", "", "https://www.city.chiba.jp/toshi/kenchiku/jutakuseisaku/02_m-soudan.html", "公式ページ");
    if (region === "yokohama") item("横浜市 マンション管理組合向け相談窓口の案内", "", "https://www.city.yokohama.lg.jp/kurashi/sumai-kurashi/jutaku/manportal/consult/question.html", "公式ページ");
    box.append(list, element("p", "公的な窓口の案内に、水害や浸水の相談を受けるとは書かれていません。受けられるかは窓口に確かめます。", "hint"));
    return box;
  }

  return { reset, render, consult, markFor, byTier, get checked() { return [...state.checked]; } };
})();

document.getElementById("consult-button").addEventListener("click", () => SimPanel.consult());
