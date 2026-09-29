"""セッション一覧を 1 枚の HTML ダッシュボードにまとめる。

実行: uv run python -m session_planner.build_dashboard
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TEMPLATE_PATH = ROOT / "dashboard" / "template.html"
PLACEHOLDER = "/*__DATA__*/"


def load_sessions(sessions_path: Path) -> list[dict]:
    """取得済みのセッション一覧を読む。"""
    if not sessions_path.exists():
        raise FileNotFoundError(f"セッションデータがありません: {sessions_path}")
    data = json.loads(sessions_path.read_text(encoding="utf-8"))
    return data.get("sessions", [])


def venue_name(session: dict) -> str:
    """会場名を返す。venue が無いセッションは room の先頭（`|` 区切りの 1 つ目）を会場とみなす。"""
    venue = session.get("venue")
    if venue:
        return str(venue)
    room = session.get("room")
    if room:
        return str(room).split("|")[0].strip()
    return ""


def build_payload(sessions: list[dict]) -> dict:
    """会場名を補完した埋め込み用データを返す。"""
    out: list[dict] = []
    for session in sessions:
        item = dict(session)
        item["venueName"] = venue_name(session)
        out.append(item)
    return {"sessions": out}


def embed(template: str, payload: dict) -> str:
    """JSON を埋め込む。`</` と `<!--` を潰し、script 要素が途中で閉じないようにする。"""
    if PLACEHOLDER not in template:
        raise ValueError(f"テンプレートにプレースホルダ {PLACEHOLDER} がありません")
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    text = (
        text.replace("</", "<\\/")
        .replace("<!--", "\\u003c!--")
        # JS 文字列では改行扱いになる文字を念のためエスケープ
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )
    return template.replace(PLACEHOLDER, text, 1)


def build(
    sessions_path: Path = DATA_DIR / "sessions.json",
    template_path: Path = TEMPLATE_PATH,
    out_path: Path = DATA_DIR / "dashboard.html",
) -> dict:
    sessions = load_sessions(sessions_path)
    payload = build_payload(sessions)
    html = embed(template_path.read_text(encoding="utf-8"), payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return {"total": len(sessions)}


def main() -> None:
    report = build()
    print(f"セッション: {report['total']} 件")
    print(f"出力: {DATA_DIR / 'dashboard.html'}")


if __name__ == "__main__":
    main()
