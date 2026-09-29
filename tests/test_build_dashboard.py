import json
import re
from pathlib import Path

from session_planner.build_dashboard import TEMPLATE_PATH, build

TEMPLATE = (
    "<html><body><script id=\"data\" type=\"application/json\">/*__DATA__*/</script>"
    "<script>ok()</script></body></html>"
)


def write_inputs(tmp_path, sessions):
    """tmp_path に架空の入力を置き、build に渡すパスを返す。"""
    paths = {
        "sessions_path": tmp_path / "sessions.json",
        "template_path": tmp_path / "template.html",
        "out_path": tmp_path / "out" / "dashboard.html",
    }
    paths["sessions_path"].write_text(json.dumps({"sessions": sessions}), encoding="utf-8")
    paths["template_path"].write_text(TEMPLATE, encoding="utf-8")
    return paths


def embedded_data(html):
    """出力 HTML の data script の中身を JSON として読む。"""
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert m is not None
    return json.loads(m.group(1))


def test_sessions_jsonだけで生成でき英語タイトルと概要が出力される(tmp_path):
    paths = write_inputs(
        tmp_path,
        [{"sessionId": "a1", "title": "Fictional session", "abstract": "Fictional abstract"}],
    )
    report = build(**paths)
    data = embedded_data(paths["out_path"].read_text(encoding="utf-8"))
    assert data["sessions"][0]["title"] == "Fictional session"
    assert data["sessions"][0]["abstract"] == "Fictional abstract"
    assert report == {"total": 1}


def test_タイトルや概要にscript終了タグがあってもscriptが途中で閉じない(tmp_path):
    evil = "x</script><script>alert(1)</script>"
    paths = write_inputs(
        tmp_path,
        [{"sessionId": "a1", "title": evil, "abstract": "<!-- " + evil}],
    )
    build(**paths)
    html = paths["out_path"].read_text(encoding="utf-8")
    # テンプレート由来の script 終了タグ 2 つ以外は増えていない
    assert html.count("</script>") == 2
    data = embedded_data(html)
    assert data["sessions"][0]["title"] == evil
    assert data["sessions"][0]["abstract"] == "<!-- " + evil


def test_venueがあるセッションの会場名はvenueになる(tmp_path):
    paths = write_inputs(
        tmp_path,
        [{"sessionId": "a1", "title": "A", "venue": "MGM Grand", "room": "Caesars Palace | Octavius 4"}],
    )
    build(**paths)
    assert embedded_data(paths["out_path"].read_text(encoding="utf-8"))["sessions"][0]["venueName"] == "MGM Grand"


def test_venueが無いセッションの会場名はroomの先頭区切りになる(tmp_path):
    paths = write_inputs(
        tmp_path,
        [{"sessionId": "a1", "title": "A", "room": " Wynn/Encore | Level 1 | Content Hub "}],
    )
    build(**paths)
    assert embedded_data(paths["out_path"].read_text(encoding="utf-8"))["sessions"][0]["venueName"] == "Wynn/Encore"


def test_venueもroomも無いセッションの会場名は空になる(tmp_path):
    paths = write_inputs(tmp_path, [{"sessionId": "a1", "title": "A"}])
    build(**paths)
    assert embedded_data(paths["out_path"].read_text(encoding="utf-8"))["sessions"][0]["venueName"] == ""


def test_生成したHTMLにサーバー同期や作者固有の保存先が含まれない(tmp_path):
    paths = write_inputs(tmp_path, [{"sessionId": "a1", "title": "Fictional session"}])
    paths["template_path"] = TEMPLATE_PATH
    build(**paths)
    html = paths["out_path"].read_text(encoding="utf-8")
    forbidden = ("/api/" + "favs", "session_planner." + "tetute" + "tu214" + ".com", ".se" + "crets")
    assert all(value not in html for value in forbidden)
    assert "localStorage" in html


def test_リポジトリに作者固有の値が残っていない():
    root = Path(__file__).resolve().parent.parent
    skipped = {".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__", "data"}
    author = "tetute" + "tu214"
    forbidden = (
        ".se" + "crets",
        "reinvent-" + "planner",
        author + ".com",
        "@" + "gmail.com",
        author,
    )
    violations = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in skipped for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found = [
            value
            for value in forbidden
            if value in text and not (path.name == "LICENSE" and value == author)
        ]
        if found:
            violations.append(str(path.relative_to(root)))
    assert violations == []
