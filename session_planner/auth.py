"""AWS Events API の OAuth 2.0（認可コード + PKCE）とトークン保存を扱う。

トークン値はどの経路でも print / ログ / 例外メッセージに出さない。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

CLIENT_ID = "7vmom55m1qstvq8i71ph127bfq"
REDIRECT_URI = "http://localhost:8484/callback"
SCOPE = "openid email events/access"
IDENTITY_PROVIDER = "AWSBuilderID"
AUTHORIZE_ENDPOINT = "https://oauth.awsevents.com/oauth2/authorize"
TOKEN_ENDPOINT = "https://oauth.awsevents.com/oauth2/token"

# 期限の何秒前からリフレッシュ対象にするか
REFRESH_MARGIN_SECONDS = 60

# RFC 7636 の unreserved 文字（ALPHA / DIGIT / "-" / "." / "_" / "~"）
UNRESERVED_CHARS = string.ascii_letters + string.digits + "-._~"

# transport の型: (method, url, headers, body) -> (status, response_headers, body)
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], bytes]]


class AuthError(Exception):
    """認証まわりの失敗。メッセージにトークン値は含めない。"""


def default_token_path() -> Path:
    """トークンの既定の保存先。"""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base_dir = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base_dir / "session-planner-dashboard" / "token.json"


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, dict[str, str], bytes]:
    """urllib による実際の HTTP 呼び出し。4xx/5xx も例外にせずステータスで返す。"""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()) if e.headers else {}, e.read()


def generate_code_verifier(length: int = 64) -> str:
    """PKCE の code_verifier を生成する（43〜128 文字の unreserved 文字）。"""
    if not 43 <= length <= 128:
        raise ValueError("code_verifier の長さは 43〜128 文字にする必要がある")
    return "".join(secrets.choice(UNRESERVED_CHARS) for _ in range(length))


def code_challenge(verifier: str) -> str:
    """code_challenge = base64url(sha256(verifier))、パディング無し。"""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state() -> str:
    """CSRF 対策の state を生成する。"""
    return secrets.token_urlsafe(32)


def build_authorize_url(challenge: str, state: str) -> str:
    """ブラウザで開く authorize URL を組み立てる。"""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "identity_provider": IDENTITY_PROVIDER,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return AUTHORIZE_ENDPOINT + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def _post_token(form: dict[str, str], transport: Transport) -> dict:
    """トークンエンドポイントに POST し、JSON を返す。"""
    body = urllib.parse.urlencode(form).encode("ascii")
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    status, _, raw = transport("POST", TOKEN_ENDPOINT, headers, body)
    if status != 200:
        # 応答本文にトークン等が混じる可能性があるため、error コードだけを取り出して出す
        error_code = ""
        try:
            error_code = str(json.loads(raw).get("error", ""))
        except (ValueError, AttributeError):
            pass
        raise AuthError(f"トークンエンドポイントがステータス {status} を返した ({error_code})")
    try:
        data = json.loads(raw)
    except ValueError:
        raise AuthError("トークンエンドポイントの応答が JSON ではない") from None
    if not isinstance(data, dict) or "access_token" not in data:
        raise AuthError("トークンエンドポイントの応答に access_token が無い")
    return data


def _expires_at(data: dict, now: float) -> float:
    """expires_in から期限の絶対時刻を計算する。"""
    if "expires_in" not in data:
        raise AuthError("トークンエンドポイントの応答に expires_in が無い")
    return now + float(data["expires_in"])


def exchange_code(
    code: str,
    verifier: str,
    *,
    transport: Transport = urllib_transport,
    now: Callable[[], float] = time.time,
) -> dict:
    """認可コードをトークンに交換し、保存用の dict を返す。"""
    data = _post_token(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code": code,
            "code_verifier": verifier,
        },
        transport,
    )
    if "refresh_token" not in data:
        raise AuthError("トークンエンドポイントの応答に refresh_token が無い")
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": _expires_at(data, now()),
    }


def refresh_tokens(
    tokens: dict,
    *,
    transport: Transport = urllib_transport,
    now: Callable[[], float] = time.time,
) -> dict:
    """refresh_token で更新する。新しい refresh_token が無ければ旧値を保持する。"""
    old_refresh = tokens.get("refresh_token")
    if not old_refresh:
        raise AuthError("refresh_token が保存されていない。`uv run python -m session_planner.login` をやり直して")
    data = _post_token(
        {"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": old_refresh},
        transport,
    )
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token") or old_refresh,
        "expires_at": _expires_at(data, now()),
    }


def save_tokens(tokens: dict, path: Path | None = None) -> Path:
    """トークンを 0o600 で保存する。ディレクトリが無ければ 0o700 で作る。"""
    path = path or default_token_path()
    if not path.parent.exists():
        path.parent.mkdir(mode=0o700, parents=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    # 既存ファイルに緩いパーミッションが付いていた場合も 600 に揃える
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    return path


def load_tokens(path: Path | None = None) -> dict:
    """保存済みトークンを読む。"""
    path = path or default_token_path()
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise AuthError(
            f"トークンファイルが無い（{path}）。`uv run python -m session_planner.login` を実行して"
        ) from None
    except ValueError:
        raise AuthError(f"トークンファイルが壊れている（{path}）") from None


def get_access_token(
    path: Path | None = None,
    *,
    force_refresh: bool = False,
    transport: Transport = urllib_transport,
    now: Callable[[], float] = time.time,
) -> str:
    """有効なアクセストークンを返す。期限 60 秒前を切っていればリフレッシュして保存し直す。"""
    tokens = load_tokens(path)
    expires_at = float(tokens.get("expires_at", 0))
    if force_refresh or now() >= expires_at - REFRESH_MARGIN_SECONDS:
        tokens = refresh_tokens(tokens, transport=transport, now=now)
        save_tokens(tokens, path)
    return tokens["access_token"]
