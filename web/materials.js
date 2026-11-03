"use strict";

// 「根拠と資料」。需要の証拠・境目の盲点・本音（仮説）・原価を下げる仕組み・判定の基準・出典を、
// 初見の人が読める短い文で出す。中身は materials.json にあり、開いたときに一度だけ読む。
// カードの表面は太字の一行と大きな値だけにし、詳しい文は折りたたみに入れる（原則1）。
const Materials = (() => {
  const LABEL_CLASS = { 事実: "mt-fact", 仮説: "mt-hypo", 決定: "mt-decided", 注意: "mt-caution" };
  let loaded = false;

  function label(text) {
    return element("span", text, `mt-label ${LABEL_CLASS[text] || ""}`);
  }

  function link(source) {
    if (!source.url) return document.createTextNode(source.name);
    const anchor = element("a", source.name);
    anchor.href = source.url;
    anchor.target = "_blank";
    anchor.rel = "noopener";
    return anchor;
  }

  function sourceList(sources) {
    const list = element("ul", undefined, "mt-sources");
    (sources || []).forEach((source) => {
      const item = element("li");
      item.append(link(source));
      list.append(item);
    });
    return list;
  }

  function paragraphs(lines) {
    return (lines || []).map((line) => element("p", line));
  }

  function part(item) {
    const box = element("div", undefined, `mt-part ${LABEL_CLASS[item.label] || ""}-edge`);
    const head = element("p", undefined, "mt-part-head");
    head.append(label(item.label), element("strong", item.heading));
    box.append(head, ...paragraphs(item.body));
    return box;
  }

  function figures(items) {
    const row = element("div", undefined, "mt-figures");
    items.forEach((item) => {
      const cell = element("div", undefined, "mt-figure");
      cell.append(element("b", item.value), element("span", item.text));
      row.append(cell);
    });
    return row;
  }

  function voices(items) {
    const grid = element("div", undefined, "mt-voices");
    items.forEach((item) => {
      const card = element("article", undefined, "mt-voice");
      const answer = element("p", undefined, "mt-voice-answer");
      answer.append(element("span", "一枚の答え", "mt-mini"), item.answer);
      card.append(element("p", item.who, "mt-voice-who"), element("p", item.honne, "mt-voice-honne"), answer);
      if (item.note) card.append(element("p", item.note, "mt-voice-note"));
      grid.append(card);
    });
    return grid;
  }

  function steps(items) {
    const list = element("ol", undefined, "mt-steps");
    items.forEach((item) => {
      const step = element("li");
      step.append(element("strong", item.head), element("span", item.text));
      list.append(step);
    });
    return list;
  }

  function verdicts(items) {
    const grid = element("div", undefined, "mt-verdicts");
    items.forEach((item) => {
      const card = element("div", undefined, `mt-verdict mt-verdict-${item.key}`);
      card.append(verdictTag(item.key, item.name), element("p", item.short, "mt-verdict-short"), fold("決め方", element("p", item.text)));
      grid.append(card);
    });
    return grid;
  }

  function sectionCard(section) {
    const card = element("section", undefined, "card mt-section");
    card.id = `mt-${section.id}`;
    const head = element("header", undefined, "mt-head");
    head.append(label(section.label), element("h2", section.title));
    card.append(head, element("p", section.lead, "mt-lead"));
    if (section.figures) card.append(figures(section.figures));
    if (section.voices) card.append(voices(section.voices));
    if (section.steps) card.append(steps(section.steps));
    if (section.verdicts) card.append(verdicts(section.verdicts));
    const more = [...paragraphs(section.body), ...(section.parts || []).map(part)];
    if (section.sources && section.sources.length) more.push(element("p", "出典", "mt-mini"), sourceList(section.sources));
    if (more.length) card.append(fold("詳しく読む", ...more));
    return card;
  }

  function sourcesCard(groups) {
    const card = element("section", undefined, "card mt-section");
    card.id = "mt-sources";
    const head = element("header", undefined, "mt-head");
    head.append(element("h2", "出典一覧"));
    card.append(head);
    const grid = element("div", undefined, "mt-source-groups");
    groups.forEach((group) => {
      const box = element("div");
      box.append(element("h3", group.group), sourceList(group.items));
      grid.append(box);
    });
    card.append(grid);
    return card;
  }

  // 主任技術者向けの値と注意。住民・理事・管理員向けの本文とは分け、折りたたみに入れる。
  function engineerFold(engineer) {
    const box = element("details", undefined, "fold mt-eng");
    box.id = "mt-engineer";
    box.append(element("summary", engineer.summary), element("p", engineer.fixed, "fixed-note strong"));
    engineer.items.forEach((item) => {
      const entry = element("article", undefined, "mt-eng-item");
      const head = element("p", undefined, "mt-part-head");
      head.append(label(item.label), element("strong", item.title));
      entry.append(head, ...paragraphs(item.body), sourceList(item.sources));
      box.append(entry);
    });
    return box;
  }

  function toc(data) {
    const nav = element("nav", undefined, "mt-toc");
    nav.setAttribute("aria-label", "資料の目次");
    const items = [...data.sections.map((s) => [`mt-${s.id}`, s.title.split("：")[0]]), ["mt-sources", "出典一覧"], ["mt-engineer", "電気主任技術者の方へ"]];
    items.forEach(([id, title]) => {
      const anchor = element("a", title);
      anchor.href = `#${id}`;
      anchor.addEventListener("click", (event) => {
        event.preventDefault();
        const target = document.getElementById(id);
        if (target.tagName === "DETAILS") target.open = true;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      nav.append(anchor);
    });
    return nav;
  }

  async function load() {
    if (loaded) return;
    loaded = true;
    const root = document.getElementById("materials-body");
    try {
      const data = await (await fetch("/materials.json")).json();
      root.replaceChildren(
        element("p", data.lead, "hint"),
        toc(data),
        ...data.sections.map(sectionCard),
        sourcesCard(data.sources),
        engineerFold(data.engineer),
      );
    } catch (error) {
      loaded = false;
      root.replaceChildren(element("p", "資料を読み込めませんでした。もう一度開いてください。", "error"));
    }
  }

  return { load };
})();
