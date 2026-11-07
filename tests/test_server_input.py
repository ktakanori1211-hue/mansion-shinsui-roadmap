"""公開前の点検（2026-11-07 セッション5弾）：形の違う入力でもサーバーが落ちず、キーや内部の情報を返さないこと。

本物のサーバーを空いているポートで起動して確かめる。API キーは読まない（HOME を空の場所にする）。
"""

import json
import os
import pathlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from unittest import mock

from app import server

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ServerInputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._home = tempfile.TemporaryDirectory()
        cls._env = mock.patch.dict(os.environ, {"HOME": cls._home.name, "ANTHROPIC_NO_CACHE": "1"})
        cls._env.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=server.WEB_DIR))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._env.stop()
        cls._home.cleanup()

    def call(self, path, body=None, headers=None, method=None):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
        request = urllib.request.Request(self.base + path, data=data, method=method or ("POST" if data is not None else "GET"))
        for name, value in (headers or {"Content-Type": "application/json"}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")

    def test_status_says_where_the_key_comes_from_but_never_the_key(self):
        with mock.patch.object(server.Handler, "log_message"):
            status, text = self.call("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(text), {"claude": False, "key_source": None})

    def test_wrong_shapes_get_a_short_400_not_a_dropped_connection(self):
        cases = [
            ("/api/building", {"sample_id": "a", "answers": "oops"}),
            ("/api/building", {"sample_id": "a", "confirmed": 5}),
            ("/api/chat", {"message": ["list"], "history": "x"}),
            ("/api/plan", {"images": "not-a-list"}),
            ("/api/consult", []),
            ("/api/polish", {"items": 3}),
        ]
        seen = set()
        for path, body in cases:
            with self.subTest(path=path):
                with mock.patch.object(server.Handler, "log_message"):
                    status, text = self.call(path, body)
                self.assertIn(status, (200, 400, 404, 422), text[:200])
                seen.add(status)
                parsed = json.loads(text)
                if status == 400:
                    self.assertEqual(parsed, {"error": "送られた内容の形が違います。"})
                for word in ("Traceback", "File \"", ".py", "line "):
                    self.assertNotIn(word, text)
        self.assertIn(400, seen, "形の違う入力が 400 にならず、守りが効いていない")

    def test_non_object_json_and_broken_json_are_refused(self):
        with mock.patch.object(server.Handler, "log_message"):
            status, text = self.call("/api/chat", b"[1, 2]")
            self.assertEqual(status, 400)
            status2, text2 = self.call("/api/chat", b"{bad")
        self.assertEqual(status2, 400)
        self.assertIn("error", json.loads(text))
        self.assertIn("error", json.loads(text2))

    def test_key_is_refused_from_another_origin_and_in_the_wrong_form(self):
        with mock.patch.object(server.Handler, "log_message"):
            status, text = self.call("/api/key", {"key": "x" * 40}, {"Content-Type": "application/json", "Origin": "http://evil.example"})
            self.assertEqual(status, 403)
            self.assertNotIn("x" * 40, text)
            host = self.base.split("//", 1)[1]
            status2, text2 = self.call("/api/key", {"key": "short"}, {"Content-Type": "application/json", "Origin": f"http://{host}", "Host": host})
        self.assertEqual(status2, 422)
        self.assertNotIn("short", text2)

    def test_posts_from_other_sites_are_refused(self):
        with mock.patch.object(server.Handler, "log_message"):
            plain = self.call("/api/chat", b'{"message":"x"}', {"Content-Type": "text/plain"})
            other = self.call("/api/chat", {"message": "x"}, {"Content-Type": "application/json", "Origin": "http://evil.example"})
            same = self.call("/api/demo-points")
            bad_length = self.call("/api/chat", b"{}", {"Content-Type": "application/json", "Content-Length": "abc"})
        self.assertEqual(plain[0], 403)
        self.assertEqual(other[0], 403)
        self.assertEqual(same[0], 200)
        self.assertEqual(bad_length[0], 400)

    def test_directories_are_not_listed(self):
        with mock.patch.object(server.Handler, "log_message"):
            status, text = self.call("/samples/")
        self.assertEqual(status, 404)
        self.assertNotIn("plan_a", text)

    def test_share_store_has_a_ceiling(self):
        from app import share

        with tempfile.TemporaryDirectory() as base:
            with mock.patch.object(share, "MAX_SHARES", 2):
                body = {"days": 7, "ciphertext": "QUJD", "iv": "QUJD", "salt": "QUJD"}
                share.create(body, base)
                share.create(body, base)
                with self.assertRaises(share.ShareError):
                    share.create(body, base)

    def test_static_files_stay_inside_web(self):
        with mock.patch.object(server.Handler, "log_message"):
            for path in ("/../app/server.py", "/%2e%2e/app/server.py", "/..%2fapp%2fserver.py", "/api/nothing"):
                with self.subTest(path=path):
                    status, text = self.call(path)
                    self.assertIn(status, (404, 400))
                    self.assertNotIn("import", text)

    def test_server_binds_to_loopback_only(self):
        source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        self.assertIn('ThreadingHTTPServer(("127.0.0.1", port)', source)
        self.assertNotIn("0.0.0.0", source)
