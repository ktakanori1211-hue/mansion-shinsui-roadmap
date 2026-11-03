"use strict";

// 第2段階の平面図。読み取り、ピン、説明、「確かめる」。
const PlanPanel = (() => {
  const message = document.getElementById("plan-message");
  const stage = document.getElementById("plan-stage");
  const fit = document.getElementById("plan-fit");
  const image = document.getElementById("plan-image");
  const pinsLayer = document.getElementById("plan-pins");
  const pinCard = document.getElementById("pin-card");
  const roomsBox = document.getElementById("plan-rooms");
  const actions = document.getElementById("plan-actions");

  const WHO_LABELS = {
    engineer: "◆ 月次点検のときに合わせて頼む",
    contractor: "■ 管理会社から業者へ",
    tepco: "▲ 管理会社から東京電力パワーグリッドへ",
    outside: "● 外から見てよい",
  };
  // 3D の札でも同じ印と色を使う（F-041）。
  window.WHO_LABELS = WHO_LABELS;

  let pins = [];
  let fromReading = false;
  let shownPlan = "";
  let shownKind = "plan";
  const tabs = document.getElementById("plan-tabs");
  const direction = document.getElementById("plan-direction");
  const absentBox = document.getElementById("plan-absent");

  // 図面の種類（F-042）。販売時の配置図も同じ入口で受ける。どちらも設備図ではないので、「描かれていない」の根拠にしない。
  const DOC_KINDS = [["plan", "竣工図の平面図"], ["sales", "販売時の配置図"]];
  let docKind = "plan";
  let shownDocKind = "plan";

  // 設備図で確かめる（F-017・F-021）。「なし」にできるのは、該当する設備図が写しにあり、人が「描かれていない」を押したときだけ。
  // 図面の種類と設備の組みは、ノートの書類の読み方（電気設備図、給排水衛生設備図など）から作った。
  const DRAWINGS = [
    ["elec", "電気設備図", ["tr", "elec", "panel_room", "gen"]],
    ["water", "給排水衛生設備図", ["pump", "tank", "drain"]],
    ["other", "そのほかの設備図（エレベーター・機械式駐車場）", ["ev", "park"]],
  ];
  const KIND_NAMES = {
    tr: "東京電力の変圧器の部屋（借室）",
    elec: "電気室（マンション側の受電の箱の部屋）",
    panel_room: "共用部のおおもとのスイッチ盤の部屋",
    gen: "非常用発電機の部屋",
    pump: "ポンプの部屋",
    tank: "地下の貯留タンク",
    drain: "汚水を汲み上げるポンプ",
    ev: "エレベーターの通り道",
    park: "機械式駐車場",
  };
  // 種類と「何が止まるか」の行（サーバーの _UPPER_ROWS・_ABSENT_ROWS と同じ対応）。
  const KIND_ROWS = { tr: "tr", elec: "power", panel_room: "power", gen: "gen", pump: "water", tank: "tank", drain: "drain", ev: "ev", park: "park" };
  // 「2階以上」を確かめられるのは、受電設備・盤・借室・ポンプの部屋だけ。
  const UPPER_KINDS = ["tr", "elec", "panel_room", "pump"];
  const CHOICE_NAMES = { absent: "描かれていない", upper: "2階以上" };
  let copies = new Set();
  let readKinds = new Set();
  let absentOpen = false;

  // 図を押すと、画面いっぱいに大きく出す。ピンを押したときは開かない。
  image.addEventListener("click", () => {
    const overlay = element("div", undefined, "drawing-zoom");
    const big = document.createElement("img");
    big.src = image.src;
    big.alt = "図面を大きく表示";
    const close = element("button", "閉じる（Esc）", "drawing-zoom-close");
    close.type = "button";
    const shut = () => {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
    };
    const onKey = (event) => {
      if (event.key === "Escape") shut();
    };
    close.addEventListener("click", shut);
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) shut();
    });
    document.addEventListener("keydown", onKey);
    overlay.append(big, close);
    document.body.append(overlay);
    close.focus();
  });

  // 図面の縦横比で、平面図のカードに収まる大きさを決める。
  image.addEventListener("load", () => {
    if (image.naturalHeight) fit.style.setProperty("--plan-ratio", image.naturalWidth / image.naturalHeight);
  });

  // 読み取りを待たずに、見本の図面とピンを出す。API は呼ばない。
  function showSamplePlan(sample) {
    fromReading = false;
    image.src = sample.plan.png;
    stage.hidden = false;
    pins = sample.pins.map((pin) => ({ ...pin }));
    renderPins();
    message.textContent = sample.custom ? "答えに近い形の見本の図面です。あなたの建物の図面ではありません。" : "架空の見本の図面です。実在の建物の図面ではありません。";
  }

  function renderPins() {
    pinsLayer.replaceChildren();
    pins.forEach((pin) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `plan-pin who-${pin.who_kind}`;
      button.textContent = pin.key;
      button.title = pin.title;
      button.style.left = `${pin.px * 100}%`;
      button.style.top = `${pin.py * 100}%`;
      button.addEventListener("click", () => {
        if (!button.dataset.dragged) App.selectPin(pin.key);
        delete button.dataset.dragged;
      });
      button.addEventListener("pointerdown", (event) => startDrag(event, button, pin));
      pinsLayer.append(button);
    });
  }

  function startDrag(event, button, pin) {
    const start = { x: event.clientX, y: event.clientY };
    const rect = fit.getBoundingClientRect();
    const move = (moved) => {
      if (Math.abs(moved.clientX - start.x) + Math.abs(moved.clientY - start.y) < 4) return;
      button.dataset.dragged = "1";
      pin.px = Math.min(1, Math.max(0, (moved.clientX - rect.left) / rect.width));
      pin.py = Math.min(1, Math.max(0, (moved.clientY - rect.top) / rect.height));
      button.style.left = `${pin.px * 100}%`;
      button.style.top = `${pin.py * 100}%`;
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }

  function showPin(pin) {
    pinCard.hidden = false;
    pinCard.replaceChildren();
    const title = element("h3", `${pin.key}　${pin.title}`);
    const close = element("button", "閉じる", "pin-close");
    close.type = "button";
    close.addEventListener("click", () => {
      pinCard.hidden = true;
      pinsLayer.querySelectorAll(".plan-pin").forEach((node) => node.classList.remove("selected"));
    });
    const verdict = App.verdictForPin(pin);
    const head = element("p", undefined, "pin-who");
    head.append(verdictTag(verdict.verdict, verdict.label), ` ${WHO_LABELS[pin.who_kind]}`);
    pinCard.append(
      close,
      title,
      head,
      element("p", `水の入り道：${pin.how_water}`),
      element("p", `確かめること：${pin.check}`),
      element("p", `確かめる人：${pin.who}（依頼メモ${["", "①", "②", "③"][pin.memo]}）`),
      element("p", App.disclaimerText(), "fixed-note strong"),
    );
    pinsLayer.querySelectorAll(".plan-pin").forEach((node) => node.classList.toggle("selected", node.textContent === pin.key));
  }

  function renderRooms(result) {
    roomsBox.replaceChildren();
    readKinds = new Set(result.rooms.map((room) => room.kind));
    if (!result.rooms.length) return;
    const table = element("table", undefined, "slim-table plan-table");
    const header = table.createTHead().insertRow();
    ["読めた語", "項目", "階", "読み方", "確かめる"].forEach((name) => header.append(element("th", name)));
    const body = table.createTBody();
    const sourceNames = { claude: "Claude", text: "PDFの文字", sample: "見本の答え" };
    result.rooms.forEach((room) => {
      const row = body.insertRow();
      row.append(element("td", room.word), element("td", room.name), element("td", room.floor || "—"), element("td", sourceNames[room.source] || room.source));
      const cell = row.insertCell();
      const box = document.createElement("input");
      box.type = "checkbox";
      box.setAttribute("aria-label", `${room.name}を図面で確かめた`);
      box.checked = App.confirmed.includes(room.kind);
      box.addEventListener("change", () => App.setConfirmed(room.kind, box.checked));
      const wrap = element("label", undefined, "confirm-box");
      wrap.append(box, "確かめた");
      cell.append(wrap);
    });
    roomsBox.append(
      element("p", "読み取りのあとに人が「確かめた」を押すまで、判定では図面で確かめたことになりません。描かれていないことは「なし」にしません。", "hint"),
      table,
      element("p", "部屋や設備を「なし」にできるのは、下の「設備図で確かめる」で写しにある設備図に印を付け、その図に描かれていないと人が押したときだけです。", "hint"),
    );
    if (shownDocKind === "sales") {
      roomsBox.append(element("p", "販売時の配置図から読んだ部屋です。「確かめた」を押すまで判定に入れません。配置図は設備図ではないので、描かれていないことの根拠にはしません。", "hint"));
    }
    if (result.unreadable && result.unreadable.length) {
      roomsBox.append(element("p", `読めなかった所：${result.unreadable.join("、")}`, "hint"));
    }
  }

  function bufferToBase64(buffer) {
    let binary = "";
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.length; i += 32768) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    }
    return btoa(binary);
  }

  async function renderPdf(buffer) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";
    const pdf = await pdfjsLib.getDocument({ data: buffer.slice(0) }).promise;
    const page = await pdf.getPage(1);
    const viewport = page.getViewport({ scale: 1.6 });
    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    // 画面が裏にあるときも止まらないよう、印刷の描き方を使う。
    await page.render({ canvasContext: canvas.getContext("2d"), viewport, intent: "print" }).promise;
    const content = await page.getTextContent();
    const base = page.getViewport({ scale: 1 });
    const pieces = content.items
      .filter((item) => item.str && item.str.trim())
      .map((item) => {
        const [x, y] = base.convertToViewportPoint(item.transform[4], item.transform[5]);
        // 「⾞」のような康熙部首で返ることがあるので、普通の字にそろえる。
        return { str: item.str.normalize("NFKC"), left: x, right: x + (item.width || 0), y, size: Math.abs(item.transform[3]) || 10 };
      })
      .sort((a, b) => a.y - b.y || a.left - b.left);
    // 文字ごとに分かれて返ることがあるので、同じ行で隣り合うものをつなぐ。
    const lines = [];
    pieces.forEach((piece) => {
      const line = lines.find(
        (item) => Math.abs(item.y - piece.y) < 2 && piece.left >= item.left - 1 && piece.left - item.right < piece.size * 0.8,
      );
      if (line) {
        line.str += piece.str;
        line.right = Math.max(line.right, piece.right);
      } else {
        lines.push({ ...piece });
      }
    });
    const words = lines.map((line) => ({ str: line.str, x: (line.left + line.right) / 2 / base.width, y: line.y / base.height }));
    return { url: canvas.toDataURL("image/png"), words };
  }

  async function load(buffer, mediaType, sampleId, kind = "plan") {
    fromReading = true;
    shownDocKind = kind;
    message.textContent = "図面を読み取っています。";
    pinCard.hidden = true;
    try {
      let shown;
      let words = [];
      if (mediaType === "application/pdf") {
        const rendered = await renderPdf(buffer);
        shown = rendered.url;
        words = rendered.words;
      } else {
        shown = URL.createObjectURL(new Blob([buffer], { type: mediaType }));
      }
      shownPlan = shown;
      image.src = shown;
      pinsLayer.hidden = false;
      stage.hidden = false;
      const response = await fetch("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample_id: sampleId, media_type: mediaType, data: bufferToBase64(buffer), words }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      message.textContent = kind === "sales" ? `販売時の配置図として受けました。${result.message}` : result.message;
      pins = withFloors(result.pins, result.rooms);
      renderPins();
      renderRooms(result);
      renderAbsent();
    } catch (error) {
      message.textContent = `図面を読めませんでした：${error.message}`;
    }
  }

  // 読めた階を説明の頭に添える。API は呼ばない。
  function withFloors(found, rooms) {
    const floors = Object.fromEntries(rooms.map((room) => [room.kind, room.floor]));
    return found.map((pin) => ({ ...pin, how_water: floors[pin.target] ? `（${floors[pin.target]}）${pin.how_water}` : pin.how_water }));
  }

  // 平面図、水の入り道の断面図、電気と給水の系統図を切り替える。ピンは平面図にだけ立てる。
  function showDrawing(sample, kind) {
    const plan = kind === "plan";
    image.src = plan ? shownPlan || sample.plan.png : sample.plan[`${kind}_png`];
    pinsLayer.hidden = !plan;
    if (!plan) pinCard.hidden = true;
    shownKind = kind;
    renderDirection();
    tabs.querySelectorAll("button").forEach((button) => button.classList.toggle("active", button.dataset.drawing === kind));
    tabs.querySelector(".plan-open").href = plan ? sample.plan.pdf : sample.plan[`${kind}_pdf`];
    tabs.querySelector(".plan-cad").href = sample.plan.dxf[kind];
    // 断面図のときだけ、時間の再生の重ね絵（水の面と入り道の矢印）を出す（web/section-anim.js）。
    if (typeof SectionAnim !== "undefined") SectionAnim.showDrawing(kind, sample);
  }

  function offerDrawings(sample) {
    const named = (label, kind) => {
      const button = element("button", label);
      button.type = "button";
      button.dataset.drawing = kind;
      button.addEventListener("click", () => showDrawing(sample, kind));
      return button;
    };
    const cad = element("a", "CADデータ（DXF）", "plan-cad");
    cad.download = "";
    const full = element("a", "PDFで拡大", "plan-open");
    full.target = "_blank";
    full.rel = "noopener";
    tabs.replaceChildren(named("平面図", "plan"), named("断面図（水の入り道）", "section"), named("系統図（電気と給水）", "system"), full, cad);
    showDrawing(sample, "plan");
  }

  function offerSample() {
    const sample = App.building.sample;
    actions.replaceChildren();
    if (!fromReading || stage.hidden) {
      shownPlan = "";
      showSamplePlan(sample);
    }
    offerDrawings(sample);
    const pdf = element("button", "この図面を読み取る（PDF）");
    pdf.type = "button";
    pdf.addEventListener("click", async () => {
      const response = await fetch(sample.plan.pdf);
      load(await response.arrayBuffer(), "application/pdf", sample.id);
    });
    const png = element("button", "画像で読み取る");
    png.type = "button";
    png.addEventListener("click", async () => {
      const response = await fetch(sample.plan.png);
      load(await response.arrayBuffer(), "image/png", sample.id);
    });
    const file = document.createElement("input");
    file.type = "file";
    file.accept = "application/pdf,image/png,image/jpeg";
    file.id = "plan-file";
    file.addEventListener("change", async () => {
      const chosen = file.files[0];
      if (!chosen) return;
      if (!window.confirm("この図面は回答を作るために Anthropic の API へ送ります（API キーを設定しているとき）。学習には使われない既定で、30日以内に削除されると同社は説明しています。実在の建物の図面は、著作権と建物の情報に注意してください。送りますか。")) return;
      load(await chosen.arrayBuffer(), chosen.type, null, docKind);
    });
    const fileLabel = element("label", "自分の図面を入れる（PDFか画像）", "plan-file-label");
    fileLabel.htmlFor = "plan-file";
    const kindBox = element("label", "入れる図面の種類：", "plan-doc-kind");
    const kindSelect = document.createElement("select");
    kindSelect.id = "plan-doc-kind";
    kindSelect.append(...DOC_KINDS.map(([value, text]) => new Option(text, value)));
    kindSelect.value = docKind;
    kindSelect.addEventListener("change", () => {
      docKind = kindSelect.value;
    });
    kindBox.append(kindSelect);
    actions.append(pdf, png, kindBox, fileLabel, file);
  }

  // 今の建物で、その種類に出すボタン。行がない設備や、図面に描かれていると読めた設備には「描かれていない」を出さない。
  function choicesFor(kind, sample, rows, current) {
    const row = rows.find((item) => item.key === KIND_ROWS[kind]);
    if (!row) return null;
    const unsure = Boolean(sample.engineer_unsure);
    // 電気の部屋は、主任技術者のいる建物は電気室、いない建物は盤の部屋。どちらか分からない建物は両方。
    if (kind === "elec" && !sample.has_chief_engineer) return null;
    if (kind === "panel_room" && sample.has_chief_engineer && !unsure) return null;
    // 見本の図面は見本の写しそのものなので、描かれている設備はボタンを出さない（階は図面のとおり）。
    if (!sample.custom && (sample.rooms || []).includes(kind) && !current) return null;
    const options = [];
    if (!readKinds.has(kind) || current === "absent") options.push("absent");
    // 主任技術者の有無が分からない建物の電気の行は、サーバーが「2階以上」で変えないので出さない。
    if (UPPER_KINDS.includes(kind) && !(unsure && KIND_ROWS[kind] === "power")) options.push("upper");
    return options.length ? { row, options } : null;
  }

  function currentChoice(kind) {
    if (App.confirmed.includes(`absent:${kind}`)) return "absent";
    if (App.confirmed.includes(`upper:${kind}`)) return "upper";
    return null;
  }

  function renderAbsent() {
    if (!absentBox) return;
    const building = App.building;
    if (!building) {
      absentBox.replaceChildren();
      return;
    }
    const { sample, equipment } = building;
    const more = element("details", undefined, "fold plan-absent");
    more.open = absentOpen;
    more.addEventListener("toggle", () => {
      absentOpen = more.open;
    });
    const marked = DRAWINGS.flatMap(([, , kinds]) => kinds).filter((kind) => currentChoice(kind)).length;
    more.append(element("summary", `設備図で確かめる（描かれていない／2階以上）${marked ? `：${marked}件` : ""}`));
    more.append(element("p", "竣工図の写しにある設備図に印を付けると、その図で確かめた結果を入れられます。建築の平面図や販売時の配置図だけでは「なし」にしません。", "hint"));
    const copyLine = element("div", undefined, "absent-copies");
    copyLine.append(element("span", "写しにある設備図：", "absent-copies-title"));
    DRAWINGS.forEach(([key, name, kinds]) => {
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = copies.has(key);
      box.addEventListener("change", async () => {
        if (box.checked) {
          copies.add(key);
          renderAbsent();
          return;
        }
        copies.delete(key);
        // 図面の印を外したら、その図で確かめた結果も外す。
        const remove = kinds.flatMap((kind) => [`absent:${kind}`, `upper:${kind}`]);
        if (remove.some((item) => App.confirmed.includes(item))) await App.setConfirmedKeys(remove, []);
        else renderAbsent();
      });
      const wrap = element("label", undefined, "confirm-box absent-copy");
      wrap.append(box, name);
      copyLine.append(wrap);
    });
    more.append(copyLine);
    DRAWINGS.filter(([key]) => copies.has(key)).forEach(([, name, kinds]) => {
      const lines = kinds
        .map((kind) => {
          const current = currentChoice(kind);
          const found = choicesFor(kind, sample, equipment, current);
          if (!found) return null;
          const line = element("div", undefined, "absent-row");
          line.append(verdictTag(found.row.verdict, found.row.verdict_label), element("span", KIND_NAMES[kind], "absent-name"));
          found.options.forEach((option) => {
            const button = element("button", CHOICE_NAMES[option], "absent-choice");
            button.type = "button";
            button.dataset.kind = kind;
            button.dataset.choice = option;
            button.setAttribute("aria-pressed", String(current === option));
            button.addEventListener("click", () => {
              const next = current === option ? null : option;
              App.setConfirmedKeys([`absent:${kind}`, `upper:${kind}`], next ? [`${next}:${kind}`] : []);
            });
            line.append(button);
          });
          return line;
        })
        .filter(Boolean);
      const section = element("div", undefined, "absent-drawing");
      section.append(element("h4", name));
      if (lines.length) section.append(...lines);
      else section.append(element("p", "この建物では、この図で確かめる行がありません（図面に描かれていると読めた設備も外しています）。", "hint"));
      more.append(section);
    });
    absentBox.replaceChildren(more);
  }

  function reset() {
    copies = new Set();
    readKinds = new Set();
    absentOpen = false;
    shownDocKind = "plan";
  }

  // 平面図の下に「土地の低い向き × 入口」の一文を出す（F-039）。文はサーバーの direction_line のまま変えない。
  function renderDirection() {
    if (!direction) return;
    const line = App.building?.direction_line || "";
    direction.hidden = !line || shownKind !== "plan";
    direction.replaceChildren();
    if (!line) return;
    direction.append(element("span", line, "strong"), element("span", "（向きは答えと地図の目安で、測ったものではありません）", "plan-direction-note"));
  }

  return { offerSample, showPin, load, renderDirection, renderAbsent, reset, WHO_LABELS, get pins() { return pins; } };
})();
