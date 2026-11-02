"use strict";

// 共有リンクの発行。送る前にブラウザの中で暗号にする。
(() => {
  const result = document.getElementById("share-result");

  function show(message, isError) {
    result.hidden = false;
    result.replaceChildren(element("p", message, isError ? "error" : "hint"));
  }

  document.getElementById("share-button").addEventListener("click", async () => {
    const password = document.getElementById("share-password").value;
    const days = Number(document.getElementById("share-days").value);
    if (!App.building) {
      show("①で場所を選ぶと発行できます。", true);
      return;
    }
    if (password.length < 8) {
      show("パスワードは8文字以上にしてください。", true);
      return;
    }
    if (!ShareCrypto.available()) {
      show("暗号の機能が使えない接続です。localhost か HTTPS で開いてください。", true);
      return;
    }
    show("暗号にしています。");
    let sealed;
    let response;
    let body;
    try {
      sealed = await ShareCrypto.encrypt(SheetPanel.shareData(), password);
      response = await fetch("/api/share", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ciphertext: sealed.ciphertext, iv: sealed.iv, salt: sealed.salt, days }),
      });
      body = await response.json();
    } catch (error) {
      show("発行できませんでした。もう一度試してください。", true);
      return;
    }
    if (!response.ok) {
      show(body.error, true);
      return;
    }
    const link = `${location.origin}/view.html#id=${body.id}&k=${sealed.linkKey}`;
    const until = new Date(body.expires_at * 1000).toLocaleDateString("ja-JP");
    const input = document.createElement("input");
    input.type = "text";
    input.readOnly = true;
    input.value = link;
    input.id = "share-link";
    input.setAttribute("aria-label", "共有リンク");
    const copy = element("button", "コピー");
    copy.type = "button";
    copy.addEventListener("click", () => navigator.clipboard?.writeText(link));
    const open = element("a", "開いて確かめる");
    open.href = link;
    open.target = "_blank";
    open.rel = "noopener";
    result.replaceChildren(
      element("p", `リンクを発行しました。${until} まで開けます。リンクとパスワードは別々に伝えてください。今は手元のサーバーに置いているので、同じパソコンでだけ開けます。`, "hint"),
      input,
      copy,
      open,
    );
  });
})();
