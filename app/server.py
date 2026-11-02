"""画面と、立地の値を返す API を出す小さなサーバー。python3 -m app.server で起動する。"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import assistant, building, claude, judge, location, records, samples, search, share, state

MAX_BODY_BYTES = 45 * 1024 * 1024  # 32MB の PDF を base64 にした大きさ
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

# デモの 3 地点。画面に区名を出さないため、住所検索を通さず町丁の代表点の座標を持つ。
DEMO_POINTS = {
    "saiwaicho": {"label": "千葉市 幸町2丁目", "longitude": 140.091583, "latitude": 35.621826, "sample": "a"},
    "ryokuen": {"label": "横浜市 緑園3丁目", "longitude": 139.519836, "latitude": 35.441181, "sample": "b"},
    "oshima": {"label": "東京都 江東区大島2丁目", "longitude": 139.822372, "latitude": 35.691696, "sample": "c"},
}


def parse_pin(query: dict) -> dict:
    """利用者が動かしたピンの位置を読む。国内の範囲だけを受ける。"""
    try:
        longitude = float(query["longitude"][0])
        latitude = float(query["latitude"][0])
    except (KeyError, ValueError) as error:
        raise location.AddressError("ピンの位置を読めませんでした。") from error
    if not (122 <= longitude <= 154 and 20 <= latitude <= 46):
        raise location.AddressError("ピンの位置が国内の範囲の外です。")
    return {"longitude": longitude, "latitude": latitude}


def build_state(label: str, longitude: float, latitude: float, basis: str, is_demo: bool) -> dict:
    reading = location.read_location(longitude, latitude)
    rows = judge.judge_location(reading, basis, records.find(label))
    site = state.Site(label, longitude, latitude, basis, is_demo)
    return state.new_state(site, reading, rows, basis_note=judge.basis_note(basis))


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format, *args):
        # 共有の番号と検索の言葉を記録に残さない。
        if args and re.search(r"/api/(share|search|reverse)", str(args[0])):
            return
        super().log_message(format, *args)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/location":
            self._location(urllib.parse.parse_qs(parsed.query))
        elif parsed.path == "/api/demo-points":
            self._send_json(
                200,
                [
                    {"id": key, "label": samples.SAMPLES[p["sample"]]["button"], "sample": p["sample"], "kind": samples.SAMPLES[p["sample"]]["kind"]}
                    for key, p in DEMO_POINTS.items()
                ],
            )
        elif parsed.path == "/api/status":
            self._send_json(200, {"claude": claude.available()})
        elif parsed.path == "/api/search":
            self._search(urllib.parse.parse_qs(parsed.query))
        elif parsed.path == "/api/reverse":
            self._reverse(urllib.parse.parse_qs(parsed.query))
        elif parsed.path.startswith("/api/share/"):
            data = share.read(parsed.path.rsplit("/", 1)[-1])
            if data:
                self._send_json(200, data)
            else:
                self._send_json(410, {"error": "このリンクは期限が過ぎたか、見つかりません。"})
        else:
            super().do_GET()

    def _location(self, query: dict):
        demo = DEMO_POINTS.get(query.get("demo", [""])[0])
        address = query.get("address", [""])[0].strip()
        basis = state.REPRESENTATIVE
        try:
            if demo:
                label, point = demo["label"], demo
            elif "longitude" in query:
                label, point = address, parse_pin(query)
                if query.get("pin", [""])[0] == "1":
                    basis = state.BUILDING
            elif address:
                label, point = address, location.geocode(address)
            else:
                raise location.AddressError("住所を入れてください。")
        except location.AddressError as error:
            self._send_json(422, {"error": str(error)})
            return
        self._send_json(200, build_state(label, point["longitude"], point["latitude"], basis, bool(demo)))

    def _search(self, query: dict):
        try:
            self._send_json(200, search.search(query.get("q", [""])[0]))
        except location.AddressError as error:
            self._send_json(422, {"error": str(error)})

    def _reverse(self, query: dict):
        try:
            point = parse_pin(query)
        except location.AddressError as error:
            self._send_json(422, {"error": str(error)})
            return
        self._send_json(200, {"label": search.reverse(point["longitude"], point["latitude"])})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "ファイルが大きすぎます。32MB 以下にしてください。"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send_json(400, {"error": "送られた内容を読めませんでした。"})
            return
        if path == "/api/building":
            label = body.get("label", "")
            sample = samples.apply_answers(body.get("sample_id"), body.get("answers"), label)
            if not sample:
                self._send_json(404, {"error": "見本が見つかりません。"})
                return
            payload = building.building_payload(
                sample,
                body.get("confirmed") or [],
                body.get("location_rows") or [],
                bool(body.get("document_read")),
                body.get("directions") or {},
                body.get("low_directions") or [],
                body.get("statements") or [],
            )
            payload["exits"] = assistant.exits(sample, label, payload)
            self._send_json(200, payload)
        elif path == "/api/share":
            try:
                self._send_json(200, share.create(body))
            except share.ShareError as error:
                self._send_json(422, {"error": str(error)})
        elif path == "/api/polish":
            self._send_json(200, assistant.polish(body.get("items") or [], body.get("context") or {}))
        elif path == "/api/pins":
            self._send_json(200, assistant.rephrase_pins(body.get("pins") or [], body.get("context") or {}))
        elif path == "/api/plan":
            self._send_json(200, assistant.read_plan(body))
        elif path == "/api/report":
            self._send_json(200, assistant.read_report(body.get("text", "")))
        elif path == "/api/chat":
            self._send_json(200, assistant.chat(body.get("message", ""), body.get("history") or [], body.get("context") or {}))
        elif path == "/api/consult":
            self._send_json(200, assistant.consult(body))
        else:
            self._send_json(404, {"error": "見つかりません。"})

    def _send_json(self, status: int, body) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    share.sweep()
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=WEB_DIR))
    print(f"http://localhost:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
