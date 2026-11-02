"""API キーの保存と読み込みを確かめる。キーが画面やログに出ないことも見る。"""

import http.client
import io
import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from unittest import mock

from app import claude, server

FAKE_KEY = "fake-key-for-tests-0123456789abcdef"


class KeyFileTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        path = os.path.join(self.directory, ".anthropic_api_key")
        patcher = mock.patch.object(claude, "KEY_FILE", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        environ = mock.patch.dict("os.environ")
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_saved_key_has_owner_only_permission(self):
        claude.save_key(FAKE_KEY)
        self.assertEqual(stat.S_IMODE(os.stat(claude.KEY_FILE).st_mode), 0o600)
        self.assertEqual(os.listdir(self.directory), [".anthropic_api_key"])

    def test_loose_permission_is_replaced(self):
        with open(claude.KEY_FILE, "w") as file:
            file.write("old")
        os.chmod(claude.KEY_FILE, 0o644)
        claude.save_key(FAKE_KEY)
        self.assertEqual(stat.S_IMODE(os.stat(claude.KEY_FILE).st_mode), 0o600)

    def test_no_key_means_unavailable(self):
        self.assertFalse(claude.available())
        self.assertIsNone(claude.key_source())
        with self.assertRaises(claude.ClaudeUnavailable):
            claude.create([], "s")

    def test_file_is_read_when_environment_is_empty(self):
        claude.save_key(FAKE_KEY)
        self.assertTrue(claude.available())
        self.assertEqual(claude.key_source(), "file")

    def test_environment_comes_first(self):
        claude.save_key(FAKE_KEY)
        os.environ["ANTHROPIC_API_KEY"] = "from-environment"
        self.assertEqual(claude.key_source(), "env")
        self.assertEqual(claude._key(), "from-environment")

    def test_request_uses_the_saved_key(self):
        claude.save_key(FAKE_KEY)
        reply = mock.MagicMock()
        reply.__enter__.return_value.read.return_value = b'{"content": [], "stop_reason": "end_turn"}'
        with mock.patch("urllib.request.urlopen", return_value=reply) as urlopen:
            claude.create([{"role": "user", "content": "x"}], "s")
        self.assertEqual(urlopen.call_args[0][0].get_header("X-api-key"), FAKE_KEY)

    def test_bad_key_is_rejected_without_echo(self):
        for bad in ("", "short", "with space " * 5, "日本語のキー" * 5, None, 123, "a\nb" * 10):
            with self.assertRaises(claude.KeyRejected) as caught:
                claude.save_key(bad)
            if bad:
                self.assertNotIn(str(bad), str(caught.exception))
        self.assertFalse(os.path.exists(claude.KEY_FILE))

    def test_save_failure_leaves_a_plain_message(self):
        with mock.patch.object(claude, "KEY_FILE", os.path.join(self.directory, "missing", "key")):
            with self.assertRaises(claude.KeyRejected) as caught:
                claude.save_key(FAKE_KEY)
        self.assertNotIn(FAKE_KEY, str(caught.exception))


class KeyGuardTest(unittest.TestCase):
    GOOD = {"Host": "localhost:8000", "Origin": "http://localhost:8000", "Content-Type": "application/json"}

    def allowed(self, client="127.0.0.1", **changes):
        return server.key_request_allowed(client, {**self.GOOD, **changes})

    def test_same_page_is_allowed(self):
        self.assertTrue(self.allowed())
        self.assertTrue(self.allowed(Host="127.0.0.1:8000", Origin="http://127.0.0.1:8000"))

    def test_other_site_is_refused(self):
        self.assertFalse(self.allowed(Origin="https://example.com"))
        self.assertFalse(self.allowed(Origin=None))
        self.assertFalse(self.allowed(Origin="null"))

    def test_rebound_host_is_refused(self):
        self.assertFalse(self.allowed(Host="evil.example:8000", Origin="http://evil.example:8000"))

    def test_form_post_is_refused(self):
        self.assertFalse(self.allowed(**{"Content-Type": "text/plain"}))

    def test_other_machine_is_refused(self):
        self.assertFalse(self.allowed(client="192.168.0.5"))


class KeyServerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        patcher = mock.patch.object(claude, "KEY_FILE", os.path.join(self.directory, ".anthropic_api_key"))
        patcher.start()
        self.addCleanup(patcher.stop)
        environ = mock.patch.dict("os.environ")
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.log = io.StringIO()
        logs = mock.patch("sys.stderr", self.log)
        logs.start()
        self.addCleanup(logs.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=server.WEB_DIR))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.host = f"localhost:{self.server.server_address[1]}"

    def post(self, key, origin=None):
        connection = http.client.HTTPConnection(self.host)
        self.addCleanup(connection.close)
        connection.request(
            "POST",
            "/api/key",
            json.dumps({"key": key}),
            {"Origin": origin or f"http://{self.host}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8")

    def test_saved_key_stays_out_of_response_and_log(self):
        status, body = self.post(FAKE_KEY)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"claude": True, "key_source": "file"})
        self.assertNotIn(FAKE_KEY, body)
        self.assertNotIn(FAKE_KEY, self.log.getvalue())

    def test_other_origin_does_not_save(self):
        status, _ = self.post(FAKE_KEY, origin="https://example.com")
        self.assertEqual(status, 403)
        self.assertFalse(os.path.exists(claude.KEY_FILE))

    def test_status_has_no_key(self):
        self.post(FAKE_KEY)
        connection = http.client.HTTPConnection(self.host)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/status")
        self.assertNotIn(FAKE_KEY, connection.getresponse().read().decode("utf-8"))



class CacheTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        cache = mock.patch.object(claude, "CACHE_DIR", os.path.join(self.directory, "cache"))
        cache.start()
        self.addCleanup(cache.stop)
        environ = mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": FAKE_KEY})
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop("ANTHROPIC_NO_CACHE", None)

    @staticmethod
    def reply(stop="end_turn"):
        answer = mock.MagicMock()
        answer.__enter__.return_value.read.return_value = json.dumps({"content": [{"type": "text", "text": "はい"}], "stop_reason": stop}).encode()
        return answer

    def call(self, text="x", **kw):
        return claude.create([{"role": "user", "content": text}], "s", **kw)

    def test_same_input_does_not_call_the_api_again(self):
        with mock.patch("urllib.request.urlopen", return_value=self.reply()) as urlopen:
            first = self.call()
            second = self.call()
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(first, second)

    def test_different_input_calls_the_api(self):
        with mock.patch("urllib.request.urlopen", return_value=self.reply()) as urlopen:
            self.call("x")
            self.call("y")
            self.call("x", effort="low")
            self.call("x", tools=[{"name": "t"}])
        self.assertEqual(urlopen.call_count, 4)

    def test_no_cache_setting_always_calls(self):
        with mock.patch("urllib.request.urlopen", return_value=self.reply()) as urlopen, mock.patch.dict("os.environ", {"ANTHROPIC_NO_CACHE": "1"}):
            self.call()
            self.call()
        self.assertEqual(urlopen.call_count, 2)
        self.assertFalse(os.path.exists(claude.CACHE_DIR))

    def test_cut_off_answer_is_not_kept(self):
        with mock.patch("urllib.request.urlopen", return_value=self.reply("max_tokens")) as urlopen:
            self.call()
            self.call()
        self.assertEqual(urlopen.call_count, 2)

    def test_key_is_not_written_and_file_is_private(self):
        with mock.patch("urllib.request.urlopen", return_value=self.reply()):
            self.call()
        name = os.listdir(claude.CACHE_DIR)[0]
        path = os.path.join(claude.CACHE_DIR, name)
        self.assertNotIn(FAKE_KEY, name)
        with open(path, encoding="utf-8") as file:
            self.assertNotIn(FAKE_KEY, file.read())
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_broken_cache_file_calls_the_api(self):
        with mock.patch("urllib.request.urlopen", return_value=self.reply()) as urlopen:
            self.call()
            name = os.listdir(claude.CACHE_DIR)[0]
            with open(os.path.join(claude.CACHE_DIR, name), "w") as file:
                file.write("壊れた")
            self.call()
        self.assertEqual(urlopen.call_count, 2)

    def test_system_is_marked_for_prompt_cache_only_when_asked(self):
        with mock.patch("urllib.request.urlopen", return_value=self.reply()) as urlopen:
            self.call("a")
            self.call("b", cache_system=True)
        plain, marked = [json.loads(call[0][0].data)["system"] for call in urlopen.call_args_list]
        self.assertEqual(plain, "s")
        self.assertEqual(marked, [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}])

    def test_default_max_tokens(self):
        with mock.patch("urllib.request.urlopen", return_value=self.reply()) as urlopen:
            self.call()
        self.assertEqual(json.loads(urlopen.call_args[0][0].data)["max_tokens"], 2048)


if __name__ == "__main__":
    unittest.main()
