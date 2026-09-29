# 本物の API はサインイン必須で結果も変わるため、ページを返す偽の get を注入して振る舞いを確かめる
import json

import pytest

from session_planner.fetch_sessions import FetchError, fetch_all


def make_get(pages):
    """呼ばれた params を記録しつつ pages を順に返す偽の get。"""
    calls = []

    def get(path, params):
        calls.append(dict(params))
        return pages[len(calls) - 1]

    return get, calls


def test_短いページでもnextTokenがあれば次のページを取りに行く(tmp_path):
    get, calls = make_get(
        [
            {"items": [{"sessionId": "a"}], "nextToken": "t1", "totalCount": 3},
            {"items": [{"sessionId": "b"}, {"sessionId": "c"}]},
        ]
    )
    result = fetch_all(get, tmp_path)
    assert [s["sessionId"] for s in result["sessions"]] == ["a", "b", "c"]
    assert calls[1]["nextToken"] == "t1"


def test_nextTokenが無ければそこで止まる(tmp_path):
    get, calls = make_get([{"items": [{"sessionId": "a"}], "totalCount": 1}])
    fetch_all(get, tmp_path)
    assert len(calls) == 1


def test_件数が合えばsessions_jsonに保存される(tmp_path):
    get, _ = make_get([{"items": [{"sessionId": "a"}], "totalCount": 1}])
    fetch_all(get, tmp_path)
    saved = json.loads((tmp_path / "sessions.json").read_text(encoding="utf-8"))
    assert saved["totalCount"] == 1
    assert saved["sessions"] == [{"sessionId": "a"}]


def test_件数がtotalCountと食い違うとエラーになりpartialが残る(tmp_path):
    get, _ = make_get([{"items": [{"sessionId": "a"}], "totalCount": 2}])
    with pytest.raises(FetchError):
        fetch_all(get, tmp_path)
    assert (tmp_path / "sessions.partial.json").exists()
    assert not (tmp_path / "sessions.json").exists()


def test_itemsキーが無い応答はキー一覧つきのエラーになる(tmp_path):
    get, _ = make_get([{"sessions": [], "totalCount": 0}])
    with pytest.raises(FetchError, match="sessions"):
        fetch_all(get, tmp_path)
