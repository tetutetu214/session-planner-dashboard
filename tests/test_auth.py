# 実 API（oauth.awsevents.com）は Builder ID のブラウザサインインが必須でテストから叩けないため、
# トークンエンドポイントは偽 transport で代替する。ファイル保存は tmp_path の実ファイルで検証する。
import json
import re
import stat
import urllib.parse

import pytest

from session_planner import auth


class FakeTokenEndpoint:
    """トークンエンドポイントの偽物。受け取った form を記録し、用意した応答を返す。"""

    def __init__(self, response: dict, status: int = 200):
        self.response = response
        self.status = status
        self.forms: list[dict] = []

    def __call__(self, method, url, headers, body):
        assert url == auth.TOKEN_ENDPOINT
        self.forms.append(dict(urllib.parse.parse_qsl(body.decode())))
        return self.status, {}, json.dumps(self.response).encode()


def test_code_challenge_matches_rfc7636_appendix_b_vector():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert auth.code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_code_verifier_is_43_to_128_unreserved_chars():
    verifier = auth.generate_code_verifier()
    assert 43 <= len(verifier) <= 128
    assert re.fullmatch(r"[A-Za-z0-9\-._~]+", verifier)


def test_code_verifier_differs_on_each_call():
    assert len({auth.generate_code_verifier() for _ in range(5)}) == 5


def test_authorize_url_contains_all_required_parameters():
    url = auth.build_authorize_url("CHALLENGE", "STATE")
    parts = urllib.parse.urlsplit(url)
    qs = dict(urllib.parse.parse_qsl(parts.query))
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == auth.AUTHORIZE_ENDPOINT
    assert qs == {
        "response_type": "code",
        "client_id": "7vmom55m1qstvq8i71ph127bfq",
        "redirect_uri": "http://localhost:8484/callback",
        "scope": "openid email events/access",
        "identity_provider": "AWSBuilderID",
        "code_challenge": "CHALLENGE",
        "code_challenge_method": "S256",
        "state": "STATE",
    }


def test_redirect_uri_in_code_exchange_matches_authorize_url():
    url = auth.build_authorize_url("CHALLENGE", "STATE")
    authorize_redirect = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))[
        "redirect_uri"
    ]
    fake = FakeTokenEndpoint({"access_token": "a", "refresh_token": "r", "expires_in": 3600})
    auth.exchange_code("CODE", "VERIFIER", transport=fake, now=lambda: 0.0)
    assert fake.forms[0]["redirect_uri"] == authorize_redirect


def test_code_exchange_stores_expiry_from_expires_in():
    fake = FakeTokenEndpoint({"access_token": "a", "refresh_token": "r", "expires_in": 1234})
    tokens = auth.exchange_code("CODE", "VERIFIER", transport=fake, now=lambda: 1000.0)
    assert tokens["expires_at"] == 2234.0


def test_saved_token_file_has_mode_600(tmp_path):
    path = tmp_path / "secrets" / "tokens.json"
    auth.save_tokens({"access_token": "a", "refresh_token": "r", "expires_at": 0}, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_missing_token_directory_is_created_with_mode_700(tmp_path):
    path = tmp_path / "secrets" / "tokens.json"
    auth.save_tokens({"access_token": "a", "refresh_token": "r", "expires_at": 0}, path)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_XDG_CONFIG_HOMEが未設定ならconfig配下を保存先にする(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert auth.default_token_path() == (
        tmp_path / ".config" / "session-planner-dashboard" / "token.json"
    )


def test_XDG_CONFIG_HOMEが設定済みならその配下を保存先にする(tmp_path, monkeypatch):
    config_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    assert auth.default_token_path() == config_home / "session-planner-dashboard" / "token.json"


def test_near_expiry_token_is_refreshed_and_new_refresh_token_saved(tmp_path):
    path = tmp_path / "tokens.json"
    auth.save_tokens({"access_token": "old-a", "refresh_token": "old-r", "expires_at": 1030}, path)
    fake = FakeTokenEndpoint({"access_token": "new-a", "refresh_token": "new-r", "expires_in": 3600})
    token = auth.get_access_token(path, transport=fake, now=lambda: 1000.0)
    assert token == "new-a"
    assert auth.load_tokens(path) == {
        "access_token": "new-a",
        "refresh_token": "new-r",
        "expires_at": 4600.0,
    }


def test_old_refresh_token_is_kept_when_refresh_response_has_none(tmp_path):
    path = tmp_path / "tokens.json"
    auth.save_tokens({"access_token": "old-a", "refresh_token": "old-r", "expires_at": 1030}, path)
    fake = FakeTokenEndpoint({"access_token": "new-a", "expires_in": 3600})
    auth.get_access_token(path, transport=fake, now=lambda: 1000.0)
    assert auth.load_tokens(path)["refresh_token"] == "old-r"


def test_token_with_enough_lifetime_is_returned_without_refresh(tmp_path):
    path = tmp_path / "tokens.json"
    auth.save_tokens({"access_token": "a", "refresh_token": "r", "expires_at": 5000}, path)
    fake = FakeTokenEndpoint({})
    assert auth.get_access_token(path, transport=fake, now=lambda: 1000.0) == "a"
    assert fake.forms == []


def test_refresh_failure_message_does_not_contain_token_values(tmp_path):
    path = tmp_path / "tokens.json"
    auth.save_tokens({"access_token": "SECRET-A", "refresh_token": "SECRET-R", "expires_at": 0}, path)
    fake = FakeTokenEndpoint({"error": "invalid_grant", "leak": "SECRET-R"}, status=400)
    with pytest.raises(auth.AuthError) as excinfo:
        auth.get_access_token(path, transport=fake, now=lambda: 1000.0)
    assert "SECRET" not in str(excinfo.value)
    assert "invalid_grant" in str(excinfo.value)
