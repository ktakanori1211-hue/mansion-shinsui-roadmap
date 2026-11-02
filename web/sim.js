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

  function markFor(measure, region, checked) {
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

  function renderResult(box) {
    const building = App.building;
    const measures = building.measures.filter((m) => state.checked.has(m.key));
    const region = state.region;
    const subsidy = building.subsidies[region];
    box.replaceChildren();

    const band = bandText(measures);
    const message = band ? `選んだ手の合計の桁：${band}` : measures.length ? "選んだ手に、足せる桁はありません。" : "手を選ぶと、合計の桁が出ます。";
    box.append(element("p", message, "sim-band"));
    measures
      .filter((m) => m.open_ended)
      .forEach((m) => box.append(element("p", `上限のない手：${m.label}（${m.range}）。合計の桁には入れていません。`, "hint")));
    box.append(element("p", "費用は桁の目安で、保安法人・工事業者の見積りに置き換えること", "fixed-note strong"));
    box.append(element("p", "調査費用：見積りで確かめる", "sim-survey"));

    const decisions = [...new Set(measures.map((m) => m.decision))];
    if (decisions.length) box.append(element("p", `決める場：${decisions.join("／")}`));

    const amountOf = (m) => Math.max(0, Number(state.estimates[m.key]) || 0);
    const total = measures.reduce((sum, m) => sum + amountOf(m), 0);
    const eligible = measures.reduce(
      (sum, m) => sum + (markFor(m, region, measures)[1] ? amountOf(m) : 0),
      0,
    );
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
        element("p", "計算の例で、交付額ではありません。見積り額が補助対象経費と同じとは限らず、消費税の扱いは確かめていません。", "fixed-note strong"),
      );
    } else if (measures.length) {
      box.append(element("p", "見積り額を入れるか、見本の金額のボタンを押すと、補助の計算の例が出ます。", "hint"));
    }
    box.append(element("p", subsidy.rate_label, "sheet-text"));
    subsidy.cautions.forEach((line) => box.append(element("p", line, "fixed-note strong")));
    if (region !== building.sample.subsidy && region !== "none") {
      const name = subsidy.label.replace(/（.*$/, "");
      box.append(element("p", `この住所の制度ではありません（${name}の計算例）`, "fixed-note emphasis"));
    }
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
    root.append(controls);

    const table = element("table", undefined, "slim-table sim-table");
    const header = table.createTHead().insertRow();
    ["選ぶ", "いつ", "何をするか", "決め方", "お金の出どころ", "桁", "補助", "見積り額（円）"].forEach((name) => header.append(element("th", name)));
    const body = table.createTBody();
    const result = element("div", undefined, "sim-result");

    const rows = [];
    building.measures.forEach((measure) => {
      const row = body.insertRow();
      const check = document.createElement("input");
      check.type = "checkbox";
      check.dataset.key = measure.key;
      check.setAttribute("aria-label", measure.label);
      check.checked = state.checked.has(measure.key);
      row.insertCell().append(check);
      row.append(
        element("td", measure.tier),
        element("td", measure.label),
        element("td", measure.decision),
        element("td", measure.account),
        element("td", measure.range),
      );
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
    root.append(scroll, result);
    refresh();
  }

  async function consult() {
    const body = document.getElementById("consult-body");
    body.replaceChildren(element("p", "文書を作っています。", "hint"));
    const response = await fetch("/api/consult", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sample_id: App.building.sample.id,
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
    [
      ["① 現地調査・見積もり仕様カルテ", documents.karte],
      ["② 交付決定前に守るべき手続きの段取り", documents.schedule],
      ["③ 管理会社・保安法人・公的相談窓口への依頼文", documents.letter],
    ].forEach(([title, text]) => {
      const section = element("section", undefined, "doc");
      const copy = element("button", "コピー");
      copy.type = "button";
      copy.addEventListener("click", () => navigator.clipboard?.writeText(text));
      section.append(element("h3", title), element("pre", text), copy);
      body.append(section);
    });
    body.append(renderRecipients(documents.letter));
    body.append(
      element("p", "依頼文ができました。送るのは管理組合です。この道具から外へは送っていません。業者の紹介はしません。", "fixed-note strong"),
    );
    const future = element("section", undefined, "future");
    future.append(
      element("h3", "将来の形：手続きも含めて相談できる窓口（デモ画面：実際には送信していません。紹介料は取りません）"),
      element("p", "ここから先は将来の姿のイメージです。動いていません。"),
      element("p", "相談を受け付けました。担当から手続きの順番と現地調査の進め方をご案内します。", "future-done"),
    );
    body.append(future);
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

  return { reset, render, consult, get checked() { return [...state.checked]; } };
})();

document.getElementById("consult-button").addEventListener("click", () => SimPanel.consult());
