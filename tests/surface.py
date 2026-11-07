"""各画面の「表面」（折りたたみを開かずに見える文字）を数える。

ブラウザは使わず、macOS の JavaScriptCore（osascript -l JavaScript）で web/start.js の画面の関数を呼び、
出てきた HTML から、折りたたみの中身（summary の文字は残す）・平面図の絵・入力欄を除いて、空白以外の文字を数える。
見本A（千葉市 幸町2丁目、架空の建物）で、場所の値は tests/fixtures/place_a.json（実行時に地図のサービスを呼ばない）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from app import building, samples

ROOT = Path(__file__).resolve().parent.parent

STUBS = r"""
var El = function () { return { addEventListener: function () {}, classList: { add: function () {}, remove: function () {}, toggle: function () {} },
  setAttribute: function () {}, querySelectorAll: function () { return []; }, querySelector: function () { return null; }, append: function () {},
  appendChild: function () {}, remove: function () {}, style: {}, dataset: {}, textContent: "", hidden: false, innerHTML: "" }; };
var document = { getElementById: function () { return El(); }, querySelectorAll: function () { return []; }, querySelector: function () { return null; },
  createElement: function () { return El(); }, addEventListener: function () {}, body: El() };
var window = this;
var location = { search: "", hash: "", origin: "http://localhost", pathname: "/" };
var history = { replaceState: function () {} };
var navigator = {};
var fetch = function () { return new Promise(function () {}); };
var setTimeout = function () { return 0; }, setInterval = function () { return 0; }, clearTimeout = function () {}, clearInterval = function () {};
if (typeof URLSearchParams === "undefined") { var URLSearchParams = function () { this.get = function () { return null; }; }; }
"""

RENDER = r"""
function surface(html) {
  var text = html
    .replace(/<svg[\s\S]*?<\/svg>/g, " ")
    .replace(/<textarea[\s\S]*?<\/textarea>/g, " ")
    .replace(/<details[^>]*>\s*<summary[^>]*>([\s\S]*?)<\/summary>[\s\S]*?<\/details>/g, " $1 ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&[a-z#0-9]+;/g, "x");
  return text.replace(/\s+/g, "").length;
}
S.place = DATA.place; S.sampleId = "a"; S.demoId = "saiwaicho"; S.floor = "8"; S.building = DATA.building; S.reached = 4;
var out = {};
S.screen = 1; out["1 場所"] = surface(screenOne());
out["2 確かめる"] = surface(screenThree());
S.play = 0; out["3 止まるもの"] = surface(screenTwo());
S.play = 3; out["3 止まるもの（③）"] = surface(screenTwo());
["memo", "a4", "cost"].forEach(function (tab) { S.tab = tab; out["4 渡す：" + tab] = surface(screenFour()); });
JSON.stringify(out);
"""


def sample_a_payload() -> dict:
    place = json.loads((ROOT / "tests" / "fixtures" / "place_a.json").read_text(encoding="utf-8"))
    rows = place["location"]["rows"]
    reading = place["location"]["reading"]
    sample = samples.apply_answers("a", {}, place["site"]["label"])
    body = building.building_payload(sample, [], rows, False, {}, reading.get("low_directions") or [], [], reading.get("high_directions") or [], bool(reading.get("basin")))
    return {"place": place, "building": body}


def surface_counts() -> dict | None:
    """画面ごとの表面の文字数。osascript がない環境では None。"""
    if not shutil.which("osascript"):
        return None
    data = json.dumps(sample_a_payload(), ensure_ascii=False)
    script = STUBS + (ROOT / "web" / "cad.js").read_text(encoding="utf-8") + "\n" + (ROOT / "web" / "start.js").read_text(encoding="utf-8") + "\nvar DATA = " + data + ";\n" + RENDER
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run(["osascript", "-l", "JavaScript", path], capture_output=True, text=True, timeout=60)
    Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-800:])
    return json.loads(result.stdout.strip())
