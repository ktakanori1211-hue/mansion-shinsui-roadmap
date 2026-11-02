"""Claude の API を、標準ライブラリだけで呼ぶ。追加のインストールを避けるため。

キーがないときや失敗したときは ClaudeUnavailable を投げる。呼ぶ側は、見本の答えやルールの文へ
戻り、その旨を画面に出す。キーを画面やログに出さない。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import List, Optional

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODEL = "claude-opus-5-5"
TIMEOUT_SECONDS = 180


class ClaudeUnavailable(Exception):
    """キーがない、接続できない、または答えを返せなかったとき。理由は画面に出せる言葉にする。"""


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def create(
    messages: List[dict],
    system: str,
    tools: Optional[List[dict]] = None,
    max_tokens: int = 16000,
    effort: str = "medium",
    schema: Optional[dict] = None,
) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY")
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
