# 実ブラウザ・AWS API・Builder ID サインインは自動テストで利用できないため、
# __main__ が引数で受け取る偽物に差し替え、呼び出し順と再試行回数を検証する。
from session_planner import __main__ as app
from session_planner import auth, client


def test_保存済みトークンが使えるときはサインインしない():
    calls: list[str] = []
    opened: list[str] = []

    def sign_in():
        calls.append("sign_in")

    result = app.main(
        [],
        get_access_token=lambda: "saved-token",
        sign_in=sign_in,
        fetch_all=lambda: calls.append("fetch") or {"sessions": [{"sessionId": "a"}]},
        build=lambda: calls.append("build") or {"total": 1},
        open_browser=opened.append,
    )

    assert result == 0
    assert calls == ["fetch", "build"]
    dashboard_url = app.file_uri((app.build_dashboard.DATA_DIR / "dashboard.html").resolve())
    assert opened == [dashboard_url]


def test_保存済みトークンが無いときはサインインしてから取得する():
    calls: list[str] = []

    def missing_token():
        calls.append("token")
        raise auth.AuthError("トークンが無い")

    result = app.main(
        ["--no-open"],
        get_access_token=missing_token,
        sign_in=lambda: calls.append("sign_in"),
        fetch_all=lambda: calls.append("fetch") or {"sessions": []},
        build=lambda: calls.append("build") or {"total": 0},
        open_browser=lambda url: calls.append("open"),
    )

    assert result == 0
    assert calls == ["token", "sign_in", "fetch", "build"]


def test_取得中にトークンを更新できなければサインインして1回だけ再取得する():
    calls: list[str] = []

    def fetch_all():
        calls.append("fetch")
        if calls.count("fetch") == 1:
            raise auth.AuthError("refresh_token を利用できない")
        return {"sessions": []}

    result = app.main(
        ["--no-open"],
        get_access_token=lambda: "saved-token",
        sign_in=lambda: calls.append("sign_in"),
        fetch_all=fetch_all,
        build=lambda: calls.append("build") or {"total": 0},
    )

    assert result == 0
    assert calls == ["fetch", "sign_in", "fetch", "build"]


def test_再取得も認証エラーなら3回目は取得しない():
    calls: list[str] = []

    def fetch_all():
        calls.append("fetch")
        raise client.ReloginRequired("再ログインが必要")

    result = app.main(
        ["--no-open"],
        get_access_token=lambda: "saved-token",
        sign_in=lambda: calls.append("sign_in"),
        fetch_all=fetch_all,
        build=lambda: calls.append("build") or {"total": 0},
    )

    assert result == 1
    assert calls == ["fetch", "sign_in", "fetch"]


def test_no_openならダッシュボードをブラウザで開かない():
    opened: list[str] = []

    result = app.main(
        ["--no-open"],
        get_access_token=lambda: "saved-token",
        sign_in=lambda: None,
        fetch_all=lambda: {"sessions": []},
        build=lambda: {"total": 0},
        open_browser=opened.append,
    )

    assert result == 0
    assert opened == []


def test_WSLではWindowsのブラウザから開けるUNCパスのURIを渡す():
    from pathlib import Path

    uri = app.file_uri(
        Path("/home/u/data/dashboard.html"),
        environ={"WSL_DISTRO_NAME": "Ubuntu"},
        to_windows_path=lambda p: r"\\wsl.localhost\Ubuntu\home\u\data\dashboard.html",
    )
    assert uri == "file://wsl.localhost/Ubuntu/home/u/data/dashboard.html"


def test_WSL以外ではLinuxのパスのURIをそのまま渡す():
    from pathlib import Path

    path = Path("/home/u/data/dashboard.html")
    assert app.file_uri(path, environ={}) == path.as_uri()
