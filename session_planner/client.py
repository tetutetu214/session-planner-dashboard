"""AWS Events API への GET を行う薄いクライアント。"""

from __future__ import annotations

import json
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path

from session_planner import auth

API_BASE = "https://api.awsevents.com/v1"
MAX_429_RETRIES = 5
# Retry-After が無い・数値でない場合に待つ秒数
DEFAULT_RETRY_AFTER_SECONDS = 1.0


class ApiError(Exception):
    """API 呼び出しの失敗。メッセージにトークン値は含めない。"""


class ReloginRequired(ApiError):
    """リフレッシュしても 401 のままで、再ログインが必要。"""


class NotRegistered(ApiError):
    """この Builder ID が re:Invent 2026 に登録されていない（403）。"""


def _retry_after_seconds(headers: dict[str, str]) -> float:
    """Retry-After ヘッダ（大文字小文字を問わない）を秒数として読む。"""
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                return max(0.0, float(value))
            except ValueError:
                return DEFAULT_RETRY_AFTER_SECONDS
    return DEFAULT_RETRY_AFTER_SECONDS


def api_get(
    path: str,
    params: dict | None = None,
    *,
    transport: auth.Transport = auth.urllib_transport,
    sleep: Callable[[float], None] = time.sleep,
    token_path: Path | None = None,
    now: Callable[[], float] = time.time,
) -> dict:
    """API_BASE + path に Bearer 付きで GET し、JSON を返す。"""
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    refreshed = False
    retries_429 = 0
    token = auth.get_access_token(
        token_path,
        transport=transport,
        now=now,
    )
    while True:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        status, resp_headers, body = transport("GET", url, headers, None)
        if status == 200:
            try:
                return json.loads(body)
            except ValueError:
                raise ApiError(f"{path} の応答が JSON ではない") from None
        if status == 401:
            if refreshed:
                raise ReloginRequired(
                    "リフレッシュ後も 401。`uv run python -m session_planner.login` をやり直して"
                )
            # 1 回だけ強制リフレッシュして再試行する
            token = auth.get_access_token(
                token_path,
                force_refresh=True,
                transport=transport,
                now=now,
            )
            refreshed = True
            continue
        if status == 403:
            raise NotRegistered("403: この Builder ID は re:Invent 2026 に登録されていない")
        if status == 429:
            if retries_429 >= MAX_429_RETRIES:
                raise ApiError(f"429 が {MAX_429_RETRIES} 回続いたため中止した")
            retries_429 += 1
            sleep(_retry_after_seconds(resp_headers))
            continue
        raise ApiError(f"{path} がステータス {status} を返した")
