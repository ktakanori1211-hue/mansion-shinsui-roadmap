"""画面と、立地の値を返す API を出す小さなサーバー。python3 -m app.server で起動する。"""

from __future__ import annotations

import json
import os
import urllib.parse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import judge, location, records, state

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

# デモの 2 地点。画面に区名を出さないため、住所検索を通さず町丁の代表点の座標を持つ。
DEMO_POINTS = {
    "saiwaicho": {"label": "千葉市 幸町2丁目", "longitude": 140.091583, "latitude": 35.621826},
    "ryokuen": {"label": "横浜市 緑園3丁目", "longitude": 139.519836, "latitude": 35.441181},
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
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/location":
            self._location(urllib.parse.parse_qs(parsed.query))
        elif parsed.path == "/api/demo-points":
            self._send_json(200, [{"id": key, "label": p["label"]} for key, p in DEMO_POINTS.items()])
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
                basis = state.BUILDING
            elif address:
                label, point = address, location.geocode(address)
            else:
                raise location.AddressError("住所を入れてください。")
        except location.AddressError as error:
            self._send_json(422, {"error": str(error)})
            return
        self._send_json(200, build_state(label, point["longitude"], point["latitude"], basis, bool(demo)))

    def _send_json(self, status: int, body) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=WEB_DIR))
    print(f"http://localhost:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
