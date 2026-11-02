"""Claude の API を、標準ライブラリだけで呼ぶ。追加のインストールを避けるため。

キーがないときや失敗したときは ClaudeUnavailable を投げる。呼ぶ側は、見本の答えやルールの文へ
戻り、その旨を画面に出す。キーを画面やログに出さない。

キーは環境変数を先に見て、なければ画面から保存したホームのファイルを読む。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from typing import List, Optional

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODEL = "claude-opus-5-5"
TIMEOUT_SECONDS = 180
KEY_FILE = os.path.join(os.path.expanduser("~"), ".anthropic_api_key")
_KEY_FORM = re.compile(r"[\x21-\x7e]{20,512}")


class ClaudeUnavailable(Exception):
    """キーがない、接続できない、または答えを返せなかったとき。理由は画面に出せる言葉にする。"""


class KeyRejected(Exception):
    """保存できないキー。理由の文にキーの文字を入れない。"""


def _file_key() -> str:
    try:
        with open(KEY_FILE, encoding="ascii") as file:
            return file.read().strip()
    except (OSError, ValueError):
        return ""


def _key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY") or _file_key()


def available() -> bool:
    return bool(_key())


def key_source() -> Optional[str]:
    """どこのキーを使っているかだけを返す。キーそのものは返さない。"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "env"
    return "file" if _file_key() else None


def save_key(key: str) -> None:
    """権限 600 の一時ファイルに書いてから置き換える。途中で読まれても、古い権限が残っても困らないように。"""
    key = key.strip() if isinstance(key, str) else ""
    if not _KEY_FORM.fullmatch(key):
        raise KeyRejected("API キーの形ではないようです。保存していません。")
    temporary = None
    try:
        handle, temporary = tempfile.mkstemp(dir=os.path.dirname(KEY_FILE), prefix=".anthropic_api_key.")
        with os.fdopen(handle, "w", encoding="ascii") as file:
            file.write(key)
        os.chmod(temporary, 0o600)
        os.replace(temporary, KEY_FILE)
    except OSError as error:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
        raise KeyRejected("キーをファイルに保存できませんでした。") from error


def create(
    messages: List[dict],
    system: str,
    tools: Optional[List[dict]] = None,
    max_tokens: int = 16000,
    effort: str = "medium",
    schema: Optional[dict] = None,
) -> dict:
    key = _key()
    if not key:
        raise ClaudeUnavailable("API キーが設定されていません。")
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    body = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "output_config": output_config,
        "thinking": {"type": "adaptive"},
        "fallbacks": "default",
    }
    if tools:
        body["tools"] = tools
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": API_VERSION,
            "anthropic-beta": FALLBACK_BETA,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise ClaudeUnavailable(f"Claude の API がエラーを返しました（{error.code}）。") from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise ClaudeUnavailable("Claude の API に接続できませんでした。") from error
    if data.get("stop_reason") == "refusal":
        raise ClaudeUnavailable("Claude がこの内容には答えられませんでした。")
    return data


def text_of(response: dict) -> str:
    return "".join(block.get("text", "") for block in response.get("content", []) if block.get("type") == "text")


def json_of(response: dict) -> dict:
    try:
        return json.loads(text_of(response))
    except ValueError as error:
        raise ClaudeUnavailable("Claude の答えを読み取れませんでした。") from error
