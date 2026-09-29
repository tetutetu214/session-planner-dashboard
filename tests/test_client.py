# 実 API（api.awsevents.com）は Builder ID のサインインが必須でテストから叩けないため、
# HTTP は偽 transport、sleep は呼ばれた秒数を記録する偽物で代替する（実際には待たない）。
# トークンファイルは tmp_path の実ファイルを使い、auth の実処理を通す。
import json

import pytest

from session_planner import auth, client


class FakeServer:
    """URL ごとに用意した応答を順に返す偽 transport。"""

    def __init__(self, api_responses, token_response=None):
        self.api_responses = list(api_responses)
        self.token_response = token_response or {"access_token": "fresh", "expires_in": 3600}
        self.api_auth_headers: list[str] = []
        self.token_calls = 0

    def __call__(self, method, url, headers, body):
        if url == auth.TOKEN_ENDPOINT:
            self.token_calls += 1
            return 200, {}, json.dumps(self.token_response).encode()
        self.api_auth_headers.append(headers["Authorization"])
        status, resp_headers, payload = self.api_responses.pop(0)
        return status, resp_headers, json.dumps(payload).encode()


@pytest.fixture
def token_path(tmp_path):
    path = tmp_path / "tokens.json"
    auth.save_tokens({"access_token": "stale", "refresh_token": "r", "expires_at": 10_000}, path)
    return path


def call(server, token_path, sleeps=None):
    sleep = (sleeps.append if sleeps is not None else lambda s: None)
    return client.api_get(
        "/events/x", {"a": "1"}, transport=server, sleep=sleep, token_path=token_path,
        now=lambda: 1000.0,
    )


def test_401_then_success_after_one_refresh_returns_result(token_path):
    server = FakeServer([(401, {}, {}), (200, {}, {"ok": True})])
    assert call(server, token_path) == {"ok": True}
    assert server.token_calls == 1
    assert server.api_auth_headers == ["Bearer stale", "Bearer fresh"]


def test_second_401_raises_relogin_required(token_path):
    server = FakeServer([(401, {}, {}), (401, {}, {})])
    with pytest.raises(client.ReloginRequired, match="session_planner.login"):
        call(server, token_path)
    assert server.token_calls == 1


def test_429_sleeps_for_retry_after_seconds_then_retries(token_path):
    server = FakeServer([(429, {"Retry-After": "7"}, {}), (200, {}, {"ok": True})])
    sleeps: list[float] = []
    assert call(server, token_path, sleeps) == {"ok": True}
    assert sleeps == [7.0]


def test_429_more_than_five_times_gives_up(token_path):
    server = FakeServer([(429, {"Retry-After": "1"}, {})] * 6)
    sleeps: list[float] = []
    with pytest.raises(client.ApiError, match="429"):
        call(server, token_path, sleeps)
    assert len(sleeps) == 5


def test_403_raises_not_registered(token_path):
    server = FakeServer([(403, {}, {})])
    with pytest.raises(client.NotRegistered, match="登録されていない"):
        call(server, token_path)


def test_error_messages_do_not_contain_token_values(token_path):
    server = FakeServer([(401, {}, {}), (401, {}, {})])
    with pytest.raises(client.ReloginRequired) as excinfo:
        call(server, token_path)
    assert "stale" not in str(excinfo.value)
    assert "fresh" not in str(excinfo.value)
