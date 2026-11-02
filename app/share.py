"""共有リンクの置き場。サーバーは暗号文と期限だけを持ち、中身は読めない。

暗号にするのも戻すのもブラウザの中で行う。鍵の半分はリンクの # の後ろにあり、サーバーへ届かない。
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "shares")
ALLOWED_DAYS = (7, 30, 90)
MAX_CIPHERTEXT_CHARS = 4 * 1024 * 1024
_ID = re.compile(r"^[0-9a-f]{32}$")
_BASE64 = re.compile(r"^[A-Za-z0-9+/=]+$")


class ShareError(ValueError):
    pass


def _path(share_id: str, base: str) -> str:
    return os.path.join(base, f"{share_id}.json")


def create(body: dict, base: str = DATA_DIR, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    days = body.get("days")
    if days not in ALLOWED_DAYS:
        raise ShareError("有効期限は 1 週間、1 か月、3 か月から選んでください。")
    fields = {key: body.get(key) for key in ("ciphertext", "iv", "salt")}
    for value in fields.values():
        if not isinstance(value, str) or not value or not _BASE64.match(value):
            raise ShareError("暗号の形が正しくありません。")
    if len(fields["ciphertext"]) > MAX_CIPHERTEXT_CHARS:
        raise ShareError("共有する内容が大きすぎます。")
    sweep(base, now)
    os.makedirs(base, exist_ok=True)
    share_id = secrets.token_hex(16)
    expires_at = now + days * 86400
    with open(_path(share_id, base), "w", encoding="utf-8") as handle:
        json.dump({**fields, "expires_at": expires_at}, handle)
    return {"id": share_id, "expires_at": expires_at}


def read(share_id: str, base: str = DATA_DIR, now: Optional[float] = None) -> Optional[dict]:
    """期限切れはここで消す。見つからないときと区別しない。"""
    now = time.time() if now is None else now
    if not _ID.match(share_id or ""):
        return None
    path = _path(share_id, base)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if data["expires_at"] <= now:
        os.remove(path)
        return None
    return data


def sweep(base: str = DATA_DIR, now: Optional[float] = None) -> int:
    now = time.time() if now is None else now
    removed = 0
    if not os.path.isdir(base):
        return 0
    for name in os.listdir(base):
        path = os.path.join(base, name)
        try:
            with open(path, encoding="utf-8") as handle:
                expired = json.load(handle)["expires_at"] <= now
        except (OSError, ValueError, KeyError):
            continue
        if expired:
            os.remove(path)
            removed += 1
    return removed
