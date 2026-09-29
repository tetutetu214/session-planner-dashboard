"""認証、セッション取得、ダッシュボード生成を順に実行する。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import webbrowser
from collections.abc import Callable

from session_planner import auth, build_dashboard, client, fetch_sessions, login


def file_uri(path, *, environ=None, to_windows_path=None) -> str:
    """ブラウザに渡す file URI を返す。

    WSL では Windows 側のブラウザが開くため、Linux のパス（file:///home/...）を
    Windows から見える UNC パス（file://wsl.localhost/<distro>/...）に変える。
    """
    environ = os.environ if environ is None else environ
    if not environ.get("WSL_DISTRO_NAME"):
        return path.as_uri()
    if to_windows_path is None:

        def to_windows_path(p):
            return subprocess.run(
                ["wslpath", "-w", str(p)], capture_output=True, text=True, check=True
            ).stdout.strip()

    try:
        unc = to_windows_path(path)
    except (OSError, subprocess.CalledProcessError):
        return path.as_uri()
    if not unc.startswith("\\\\"):
        return path.as_uri()
    return "file:" + unc.replace("\\", "/")


def run(
    *,
    no_open: bool = False,
    get_access_token: Callable[[], str] | None = None,
    sign_in: Callable[[], object] | None = None,
    fetch_all: Callable[[], dict] | None = None,
    build: Callable[[], dict] | None = None,
    open_browser: Callable[[str], object] | None = None,
) -> None:
    """一連の処理を実行する。外部作用はテスト用に差し替えられる。"""
    token_getter = (
        get_access_token if get_access_token is not None else auth.get_access_token
    )
    browser_opener = open_browser if open_browser is not None else webbrowser.open
    sign_in_action = (
        sign_in
        if sign_in is not None
        else lambda: login.sign_in(open_browser=browser_opener)
    )
    fetch_action = fetch_all if fetch_all is not None else fetch_sessions.fetch_all
    build_action = build if build is not None else build_dashboard.build

    try:
        token_getter()
    except auth.AuthError:
        print("認証: 保存済みトークンを利用できないため、サインインを開始します。")
        sign_in_action()
        print("認証: サインインしてトークンを保存しました。")
    else:
        print("認証: 保存済みトークンを使用します。")

    print("取得: セッション一覧を取得します。")
    try:
        result = fetch_action()
    except (auth.AuthError, client.ReloginRequired):
        print("認証: トークンを更新できないため、サインインをやり直します。")
        sign_in_action()
        print("取得: セッション一覧の取得を再実行します。")
        result = fetch_action()
    print(
        f"取得: {len(result['sessions'])} 件を "
        f"{fetch_sessions.DATA_DIR / 'sessions.json'} に保存しました。"
    )

    print("生成: ダッシュボードを生成します。")
    build_action()
    dashboard_path = build_dashboard.DATA_DIR / "dashboard.html"
    print(f"生成: {dashboard_path} を生成しました。")

    if no_open:
        print("表示: --no-open のためブラウザを開きません。")
        return
    print("表示: ブラウザでダッシュボードを開きます。")
    browser_opener(file_uri(dashboard_path.resolve()))


def main(
    argv: list[str] | None = None,
    *,
    get_access_token: Callable[[], str] | None = None,
    sign_in: Callable[[], object] | None = None,
    fetch_all: Callable[[], dict] | None = None,
    build: Callable[[], dict] | None = None,
    open_browser: Callable[[str], object] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="re:Invent 2026 のセッションを取得してダッシュボードを生成する"
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="生成したダッシュボードをブラウザで開かない",
    )
    args = parser.parse_args(argv)

    try:
        run(
            no_open=args.no_open,
            get_access_token=get_access_token,
            sign_in=sign_in,
            fetch_all=fetch_all,
            build=build,
            open_browser=open_browser,
        )
    except (
        auth.AuthError,
        login.LoginError,
        fetch_sessions.FetchError,
        client.ApiError,
        OSError,
        ValueError,
        webbrowser.Error,
    ) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
