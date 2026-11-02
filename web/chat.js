"use strict";

// 第3段階の相談。答えのたびに、どこから答えたかを出す。
(() => {
  const panel = document.getElementById("chat");
  const toggle = document.getElementById("chat-toggle");
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const history = [];
  const SOURCE_NAMES = { claude: "Claude", fixed: "固定の文（AIを通していません）", fallback: "説明カード（AIを通していません）" };

  function add(role, text, note) {
    const message = element("div", undefined, `chat-message chat-${role}`);
    message.append(element("p", text));
    if (note) message.append(element("small", note));
    log.append(message);
    log.scrollTop = log.scrollHeight;
  }

  toggle.addEventListener("click", () => {
    panel.hidden = false;
    toggle.hidden = true;
    input.focus();
  });
  document.getElementById("chat-close").addEventListener("click", () => {
    panel.hidden = true;
    toggle.hidden = false;
  });

  let waiting = null;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    // 答えの順番が入れ替わらないよう、答えが返るまで次を受けない。
    if (!text || waiting) return;
    input.value = "";
    add("user", text);
    waiting = element("div", "考えています。", "chat-message chat-wait");
    log.append(waiting);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history, context: App.chatContext() }),
      });
      const result = await response.json();
      waiting.remove();
      waiting = null;
      add("assistant", result.text, [SOURCE_NAMES[result.source], result.notice].filter(Boolean).join("　"));
      history.push({ role: "user", content: text }, { role: "assistant", content: result.text });
      (result.actions || []).forEach((action) => App.applyAction(action));
    } catch (error) {
      waiting.remove();
      waiting = null;
      add("assistant", "接続できませんでした。");
    }
  });
})();
