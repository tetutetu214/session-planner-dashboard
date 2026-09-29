"""re:Invent 2026 のセッション一覧を全件取得して data/ に保存する。

実行: uv run python -m session_planner.fetch_sessions
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from session_planner import client

EVENT_ID = "reinvent2026"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# ページごとのセッション配列のキー（2026-09-26 実測では items）
ITEMS_KEY = "items"


class FetchError(Exception):
    """全件取得の失敗。"""


class FetchCountMismatchError(FetchError):
    """取得件数と totalCount が一致しない。"""

    def __init__(self, fetched: int, total: object, *, partial_saved: bool):
        self.fetched = fetched
        self.total = total
        suffix = "（partial を保存した）" if partial_saved else ""
        super().__init__(f"件数が合わない: 取得 {fetched} 件 / totalCount {total}{suffix}")


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_all(
    get: Callable[[str, dict], dict] = client.api_get,
    data_dir: Path | None = DATA_DIR,
) -> dict:
    """nextToken が無くなるまでたどり、件数を照合する。data_dir=None なら保存しない。"""
    path = f"/events/{EVENT_ID}/sessions"
    params: dict[str, str] = {"includeAbstracts": "true"}
    sessions: list[dict] = []
    total: int | None = None
    page_no = 0

    while True:
        page = get(path, params)
        page_no += 1
        if page_no == 1:
            # 形の確認用に 1 ページ目の生 JSON を残す
            if data_dir is not None:
                _write_json(data_dir / "page1.raw.json", page)
            total = page.get("totalCount")
        if ITEMS_KEY not in page:
            raise FetchError(
                f"応答に {ITEMS_KEY} が無い。トップレベルのキー: {sorted(page.keys())}"
            )
        sessions.extend(page[ITEMS_KEY])
        next_token = page.get("nextToken")
        # 短いページでも最後とは限らないので、nextToken の有無だけで止める
        if not next_token:
            break
        params = {"includeAbstracts": "true", "nextToken": next_token}

    result = {
        "fetchedAt": datetime.now(UTC).isoformat(),
        "totalCount": total,
        "sessions": sessions,
    }
    if total is None or len(sessions) != total:
        if data_dir is not None:
            _write_json(data_dir / "sessions.partial.json", result)
        raise FetchCountMismatchError(
            len(sessions),
            total,
            partial_saved=data_dir is not None,
        )
    if data_dir is not None:
        _write_json(data_dir / "sessions.json", result)
    return result


def main() -> int:
    try:
        result = fetch_all()
    except (FetchError, client.ApiError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    print(f"{len(result['sessions'])} 件を保存した: {DATA_DIR / 'sessions.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
