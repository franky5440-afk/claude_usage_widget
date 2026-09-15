"""Mac 移植：憑證讀取 Keychain 優先、檔案 fallback（Frank 2026-09-15 拍板）。

測試一律假造 subprocess，絕不碰真的 Keychain。
"""
import json
import subprocess

from collector import usage_api


def _creds(token):
    return json.dumps({"claudeAiOauth": {"accessToken": token}})


class FakeRun:
    """記錄呼叫參數，回傳指定結果或拋指定例外。"""

    def __init__(self, stdout="", returncode=0, exc=None):
        self.calls = []
        self.stdout, self.returncode, self.exc = stdout, returncode, exc

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(args, self.returncode, stdout=self.stdout, stderr="")


def _setup(monkeypatch, tmp_path, fake, platform="darwin", file_token="file-token"):
    monkeypatch.setattr(usage_api.subprocess, "run", fake)
    monkeypatch.setattr(usage_api.sys, "platform", platform)
    monkeypatch.setattr(usage_api.Path, "home", lambda: tmp_path)
    if file_token is not None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / ".credentials.json").write_text(_creds(file_token))


def test_mac_上_keychain_有值就用它不看檔案(monkeypatch, tmp_path):
    fake = FakeRun(stdout=_creds("kc-token") + "\n")
    _setup(monkeypatch, tmp_path, fake)
    assert usage_api.read_access_token() == "kc-token"


def test_keychain_查詢要用正確的服務名且有逾時(monkeypatch, tmp_path):
    fake = FakeRun(stdout=_creds("kc-token"))
    _setup(monkeypatch, tmp_path, fake)
    usage_api.read_access_token()
    args, kwargs = fake.calls[0]
    assert args == ["/usr/bin/security", "find-generic-password", "-s", "Claude Code-credentials", "-w"]
    assert kwargs.get("timeout"), "Keychain 可能跳授權視窗卡住，必須有逾時"
    assert kwargs.get("check") is not True


def test_keychain_找不到項目時退回檔案(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, FakeRun(returncode=44))
    assert usage_api.read_access_token() == "file-token"


def test_keychain_逾時時退回檔案(monkeypatch, tmp_path):
    exc = subprocess.TimeoutExpired(cmd="security", timeout=10)
    _setup(monkeypatch, tmp_path, FakeRun(exc=exc))
    assert usage_api.read_access_token() == "file-token"


def test_沒有_security_指令時退回檔案(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, FakeRun(exc=FileNotFoundError("security")))
    assert usage_api.read_access_token() == "file-token"


def test_keychain_內容壞掉或缺欄位時退回檔案(monkeypatch, tmp_path):
    for bad in ["not json", json.dumps({"other": 1}), json.dumps({"claudeAiOauth": {}}), "[]"]:
        _setup(monkeypatch, tmp_path, FakeRun(stdout=bad), file_token=None)
        cred = tmp_path / ".claude" / ".credentials.json"
        cred.parent.mkdir(exist_ok=True)
        cred.write_text(_creds("file-token"))
        assert usage_api.read_access_token() == "file-token", bad


def test_兩邊都讀不到回傳_None_不拋例外(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, FakeRun(returncode=44), file_token=None)
    assert usage_api.read_access_token() is None


def test_非_mac_不呼叫_keychain(monkeypatch, tmp_path):
    fake = FakeRun(stdout=_creds("kc-token"))
    _setup(monkeypatch, tmp_path, fake, platform="linux")
    assert usage_api.read_access_token() == "file-token"
    assert fake.calls == []


def test_明確指定檔案路徑時只讀該檔(monkeypatch, tmp_path):
    fake = FakeRun(stdout=_creds("kc-token"))
    _setup(monkeypatch, tmp_path, fake)
    other = tmp_path / "explicit.json"
    other.write_text(_creds("explicit-token"))
    assert usage_api.read_access_token(other) == "explicit-token"
    assert fake.calls == []
