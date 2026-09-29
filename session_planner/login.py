"""Builder ID でサインインし、トークンを保存する。

実行: uv run python -m session_planner.login
"""

from __future__ import annotations

import argparse
import http.server
import sys
import urllib.parse
import webbrowser
from collections.abc import Callable
from pathlib import Path

from session_planner import auth

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8484


class LoginError(Exception):
    """サインインの失敗。"""


def parse_callback(query: str, expected_state: str) -> str:
    """コールバックのクエリ文字列を検証し、認可コードを返す。"""
    qs = urllib.parse.parse_qs(query)
    if "error" in qs:
        raise LoginError(f"認可サーバがエラーを返した: {qs['error'][0]}")
    if qs.get("state", [""])[0] != expected_state:
        raise LoginError("state が一致しない。やり直して")
    code = qs.get("code", [""])[0]
    if not code:
        raise LoginError("コールバックに code が無い")
    return code


def wait_for_callback() -> str:
    """/callback を 1 回だけ受け取り、クエリ文字列を返す。"""
    received: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urllib.parse.urlsplit(self.path)
            if parts.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            received["query"] = parts.query
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("サインインが完了しました。このタブは閉じて構いません。ダッシュボードは自動で開きます。".encode())

        def log_message(self, format: str, *args: object) -> None:
            # アクセスログに code が出ないよう黙らせる
            pass

    with http.server.HTTPServer((LISTEN_HOST, LISTEN_PORT), Handler) as server:
        while "query" not in received:
            server.handle_request()
    return received["query"]


def sign_in(
    *,
    open_browser: Callable[[str], object] | None = None,
    receive_callback: Callable[[], str] | None = None,
    exchange: Callable[[str, str], dict] | None = None,
    save: Callable[[dict], Path] | None = None,
) -> Path:
    """ブラウザサインインを完了し、トークンを保存して保存先を返す。"""
    browser_opener = open_browser if open_browser is not None else webbrowser.open
    callback_receiver = (
        receive_callback if receive_callback is not None else wait_for_callback
    )
    code_exchange = exchange if exchange is not None else auth.exchange_code
    token_saver = save if save is not None else auth.save_tokens

    verifier = auth.generate_code_verifier()
    state = auth.generate_state()
    url = auth.build_authorize_url(auth.code_challenge(verifier), state)
    print("次の URL をブラウザで開いてサインインして:")
    print(url)
    try:
        browser_opener(url)
    except webbrowser.Error:
        pass

    code = parse_callback(callback_receiver(), state)
    tokens = code_exchange(code, verifier)
    return token_saver(tokens)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="re:Invent 2026 用に Builder ID でサインインする"
    )
    parser.parse_args(argv)

    try:
        path = sign_in()
    except (LoginError, auth.AuthError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    print(f"サインイン成功。保存先: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
