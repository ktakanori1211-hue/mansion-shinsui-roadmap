"use strict";

// 共有の暗号。ブラウザの中だけで暗号にし、元に戻す。鍵はパスワードとリンクの # の後ろの値から作る。
const ShareCrypto = (() => {
  const ITERATIONS = 200000;

  function toBase64(buffer) {
    let binary = "";
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.length; i += 32768) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    }
    return btoa(binary);
  }

  function fromBase64(text) {
    return Uint8Array.from(atob(text), (char) => char.charCodeAt(0));
  }

  async function deriveKey(password, linkKey, salt) {
    const material = await crypto.subtle.importKey("raw", new TextEncoder().encode(`${password}.${linkKey}`), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey(
      { name: "PBKDF2", salt, iterations: ITERATIONS, hash: "SHA-256" },
      material,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"],
    );
  }

  function available() {
    return Boolean(window.crypto && crypto.subtle);
  }

  async function encrypt(data, password) {
    const linkKey = toBase64(crypto.getRandomValues(new Uint8Array(24))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const key = await deriveKey(password, linkKey, salt);
    const plain = new TextEncoder().encode(JSON.stringify(data));
    const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, plain);
    return { linkKey, ciphertext: toBase64(cipher), iv: toBase64(iv), salt: toBase64(salt) };
  }

  async function decrypt(stored, password, linkKey) {
    const key = await deriveKey(password, linkKey, fromBase64(stored.salt));
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: fromBase64(stored.iv) }, key, fromBase64(stored.ciphertext));
    return JSON.parse(new TextDecoder().decode(plain));
  }

  return { available, encrypt, decrypt };
})();
