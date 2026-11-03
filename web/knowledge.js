"use strict";

// 「調べたこと」の段階。本人の調べた中身（なぜ・何を・市場とモデル・どう作るか・判定表・数字と出典）を、
// 薄めずに全部並べる。中身は knowledge.json にあり、画面はそれを読んで出すだけ。
const Knowledge = (() => {
  const LABEL_CLASS = { 事実: "kb-fact", 仮説: "kb-hypo", 決定: "kb-decided", 機能: "kb-feature", 注意: "kb-caution" };
  const STATE_CLASS = { 実装済み: "kb-done", 今回追加: "kb-added", 未実装: "kb-todo" };
  let data = null;
  let filter = { area: "all", text: "" };

  function sourceList(sources) {
    if (!sources || !sources.length) return null;
    const list = element("ul", undefined, "kb-sources");
    sources.forEach((source) => {
      const item = element("li");
      if (source.url) {
        const link = element("a", source.name);
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noopener";
        item.append(link);
      } else {
        item.append(source.name);
      }
      list.append(item);
    });
    return list;
  }

  function entryCard(entry) {
    const card = element("article", undefined, "kb-entry");
    card.dataset.area = entry.area;
    const head = element("header", undefined, "kb-entry-head");
    head.append(element("span", entry.label, `kb-label ${LABEL_CLASS[entry.label] || ""}`), element("h3", entry.title));
    card.append(head);
    entry.body.split("\n\n").forEach((paragraph) => card.append(element("p", paragraph)));
    const sources = sourceList(entry.sources);
    if (sources) card.append(sources);
    card.append(element("p", `ノートの項目：${entry.note_ids.join("、")}`, "kb-ids"));
    return card;
  }

  function matches(entry) {
    if (filter.area !== "all" && entry.area !== filter.area) return false;
    if (!filter.text) return true;
    const haystack = `${entry.title}\n${entry.body}\n${(entry.sources || []).map((s) => s.name).join("\n")}`;
    return haystack.includes(filter.text);
  }

  function coverageTable() {
    const table = element("table", undefined, "slim-table kb-coverage");
    const header = table.createTHead().insertRow();
    ["領域", "項目", "アプリに既にある", "資料として追加", "機能として追加", "仕様書だけ（下の全文にある）", "数字・名前を外して要件定義に入れた", "見出し"].forEach((name) => header.append(element("th", name)));
    const body = table.createTBody();
    data.areas.forEach((area) => {
      const row = body.insertRow();
      const c = data.coverage[area.key] || {};
      [area.title, c.total, c.in_app, c.app_content, c.app_feature, c.spec_only, c.excluded, c.structure].forEach((value) => row.append(element("td", value === undefined ? "—" : String(value))));
    });
    return table;
  }

  function featureTable() {
    const table = element("table", undefined, "slim-table kb-features");
    const header = table.createTHead().insertRow();
    ["状態", "機能", "画面の場所", "補足", "ノートの項目"].forEach((name) => header.append(element("th", name)));
    const body = table.createTBody();
    data.features.forEach((feature) => {
      const row = body.insertRow();
      row.append(
        element("td", feature.state, `kb-state ${STATE_CLASS[feature.state] || ""}`),
        element("td", feature.title),
        element("td", feature.where || "—"),
        element("td", feature.reason || "—"),
        element("td", feature.note_ids.join("、"), "kb-ids"),
      );
    });
    return table;
  }

  function renderEntries() {
    const root = document.getElementById("kb-entries");
    const shown = data.entries.filter(matches);
    document.getElementById("kb-count").textContent = `${shown.length}件／全${data.entries.length}件`;
    root.replaceChildren(
      ...data.areas
        .map((area) => {
          const items = shown.filter((entry) => entry.area === area.key);
          if (!items.length) return null;
          const section = element("section", undefined, "kb-area");
          section.append(element("h2", `${area.title}（${items.length}件）`), ...items.map(entryCard));
          return section;
        })
        .filter(Boolean),
    );
  }

  function renderControls() {
    const chips = document.getElementById("kb-areas");
    const make = (key, title) => {
      const button = element("button", title, filter.area === key ? "active" : "");
      button.type = "button";
      button.addEventListener("click", () => {
        filter.area = key;
        renderControls();
        renderEntries();
      });
      return button;
    };
    chips.replaceChildren(make("all", "すべて"), ...data.areas.map((area) => make(area.key, area.title)));
  }

  const REASON_NAMES = {
    決まり2: "出典を確かめていない数字（印が「未」）だけの行",
    決まり3: "実在の建物や場所の特定につながる",
    印: "ノートの印に「書かない」「使わない」とある",
    印の条件: "済だが、印の欄に「公開物には使わない」とある",
  };

  function excludedTable() {
    const table = element("table", undefined, "slim-table kb-coverage");
    const header = table.createTHead().insertRow();
    ["領域", "外したものの理由", "数", "ノートの項目（要件定義の全文で、この番号の行を読めます）"].forEach((name) => header.append(element("th", name)));
    const body = table.createTBody();
    data.areas.forEach((area) => {
      Object.entries(data.excluded[area.key] || {}).forEach(([reason, item]) => {
        const row = body.insertRow();
        row.append(element("td", area.title), element("td", REASON_NAMES[reason] || reason), element("td", String(item.count)), element("td", item.ids.join("、"), "kb-ids"));
      });
    });
    return table;
  }

  // 主任技術者向けの値と注意。住民・理事・管理員向けの本文とは分け、折りたたみに入れる。
  function engineerBlock() {
    const box = document.createDocumentFragment();
    data.engineer.entries.forEach((entry) => box.append(entryCard(entry)));
    if (data.engineer.requirement_lines.length) {
      box.append(element("h3", "要件定義のうち、主任技術者向けの行"));
      data.engineer.requirement_lines.forEach((line) => box.append(element("p", line, "kb-eng-line")));
    }
    return box;
  }

  // 要件定義の全文。見出しと表の行が分かる程度に、行ごとに出す。
  function requirementsText() {
    const box = document.createDocumentFragment();
    data.requirements.split("\n").forEach((line) => {
      const heading = line.match(/^(#+)\s+(.*)/);
      if (heading) box.append(element(heading[1].length <= 2 ? "h3" : "h4", heading[2]));
      else if (line.trim()) box.append(element("p", line));
    });
    return box;
  }

  async function load() {
    if (data) return;
    const response = await fetch("/knowledge.json");
    data = await response.json();
    document.getElementById("kb-coverage").replaceChildren(coverageTable());
    document.getElementById("kb-feature-list").replaceChildren(featureTable());
    document.getElementById("kb-excluded").replaceChildren(excludedTable());
    document.getElementById("kb-requirements").replaceChildren(requirementsText());
    document.getElementById("kb-engineer").replaceChildren(engineerBlock());
    renderControls();
    renderEntries();
  }

  document.getElementById("kb-search").addEventListener("input", (event) => {
    filter.text = event.target.value.trim();
    if (data) renderEntries();
  });

  return { load };
})();
