"""介面契約測試 — 跨機讀取對方的 session context（SPEC §13）。

⚠️ builder 不得修改本檔的斷言。測試錯了請回報，不要自己改綠。
每個測試上方的註解說明「為什麼」這條契約存在。

介面：
    peer.load_config(path) -> dict | None
    peer.fetch_peer(config, runner=subprocess.run, now=None) -> dict
        回傳 {"label", "ok", "sessions", "error", "generated_at"}
    main.build_state(..., peer=None)  -> state["peer"]
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector import main, peer  # noqa: E402

TW = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 2, 22, 0, 0, tzinfo=TW)
CONFIG = {"ssh_target": "someone@somehost", "label": "M3"}


def _session(name, tokens):
    return {"project": name, "tokens": tokens, "context_window": 1000000,
            "percent": round(tokens / 10000, 1), "model": "claude-opus-5-5[1m]",
            "last_active_at": "2026-10-02T21:59:00+08:00"}


def _peer_state(sessions, age_seconds=30, extra=None):
    st = {"schema_version": 1,
          "generated_at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
          "ok": True, "errors": [], "limits": [], "sessions": sessions}
    if extra:
        st.update(extra)
    return st


class FakeRunner:
    """記錄呼叫參數；回傳指定的 stdout / returncode，或丟指定的例外。"""

    def __init__(self, stdout="", returncode=0, raises=None):
        self.stdout = stdout
        self.returncode = returncode
        self.raises = raises
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout,
                               stderr="boom")


def _fetch(stdout="", **kw):
    runner = FakeRunner(stdout=stdout, **kw)
    return peer.fetch_peer(CONFIG, runner=runner, now=NOW), runner


# --- 設定檔 ---------------------------------------------------------------

# 沒有設定檔＝功能關閉；不可以丟例外讓 collector 掛掉
def test_沒有設定檔就回傳_None(tmp_path):
    assert peer.load_config(tmp_path / "nope.json") is None


# 設定檔壞掉或缺 ssh_target 也一樣當作關閉，不可以猜一個預設主機
@pytest.mark.parametrize("content", ["{not json", json.dumps({"label": "M3"}),
                                     json.dumps({"ssh_target": ""}),
                                     json.dumps(["a"])])
def test_設定檔無效就回傳_None(tmp_path, content):
    p = tmp_path / "peer.json"
    p.write_text(content, encoding="utf-8")
    assert peer.load_config(p) is None


def test_設定檔有效就讀出_target_與_label(tmp_path):
    p = tmp_path / "peer.json"
    p.write_text(json.dumps({"ssh_target": "a@b", "label": "Linux"}), encoding="utf-8")
    cfg = peer.load_config(p)
    assert cfg["ssh_target"] == "a@b"
    assert cfg["label"] == "Linux"


# --- ssh 呼叫方式 ---------------------------------------------------------

# argv 用 list、不經 shell：設定檔內容不可以變成 shell 注入的入口。
# BatchMode 讓 ssh 永遠不會停下來問密碼；兩層逾時讓 widget 最多卡 5 秒。
# ssh 用絕對路徑：Übersicht 從 GUI 啟動，PATH 不保證完整（兩台都在 /usr/bin/ssh）。
def test_ssh_呼叫用_argv_list_且有兩層逾時():
    _, runner = _fetch(json.dumps(_peer_state([])))
    assert len(runner.calls) == 1
    args, kwargs = runner.calls[0]
    assert isinstance(args, list)
    assert args[0] == "/usr/bin/ssh"
    assert "BatchMode=yes" in args
    assert "ConnectTimeout=3" in args
    assert "someone@somehost" in args
    assert args[-1] == "cat .cache/claude-usage-widget/state.json"
    assert not kwargs.get("shell", False)
    assert 0 < kwargs["timeout"] <= 5


# --- 正常路徑 -------------------------------------------------------------

def test_正常時帶回對方的_sessions_與_generated_at():
    sessions = [_session("alpha", 10000), _session("beta", 20000)]
    st = _peer_state(sessions)
    result, _ = _fetch(json.dumps(st))
    assert result["ok"] is True
    assert result["error"] is None
    assert result["label"] == "M3"
    assert result["generated_at"] == st["generated_at"]
    assert result["sessions"] == sessions


# 只取對方「自己的」sessions；對方 state 裡的 peer（＝我們自己）絕不可以轉回來，
# 否則兩台互相轉送會形成迴圈、畫面上出現自己的 session。
def test_不可以把對方的_peer_欄位帶回來():
    mine = [_session("from-peer", 11111)]
    echoed = {"label": "Linux", "ok": True, "error": None,
              "generated_at": NOW.isoformat(),
              "sessions": [_session("echo-of-me", 99999)]}
    result, _ = _fetch(json.dumps(_peer_state(mine, extra={"peer": echoed})))
    assert result["sessions"] == mine
    assert "peer" not in result
    assert "echo-of-me" not in json.dumps(result)


# 最多 3 條，取前 3 條（對方已經依活動時間由新到舊排好）
def test_最多取前三條():
    sessions = [_session(f"s{i}", 1000 * (i + 1)) for i in range(5)]
    result, _ = _fetch(json.dumps(_peer_state(sessions)))
    assert [s["project"] for s in result["sessions"]] == ["s0", "s1", "s2"]


# 對方的資料不完全可信：型別不對的整筆丟掉，白名單以外的欄位不帶過來
def test_格式不對的_session_丟掉_多餘欄位不帶過來():
    good = _session("good", 5000)
    with_extra = dict(_session("extra", 6000), secret="leak")
    bad = [
        "not-a-dict",
        dict(_session("x", 1), project=123),
        dict(_session("y", 1), tokens="many"),
    ]
    result, _ = _fetch(json.dumps(_peer_state(bad + [good, with_extra])))
    assert [s["project"] for s in result["sessions"]] == ["good", "extra"]
    assert "secret" not in result["sessions"][1]
    assert result["sessions"][1] == _session("extra", 6000)


# 對方檔案壞掉時不可以把畫面撐爆：字串欄位截到 200 字，取開頭
def test_字串欄位截到_200_字():
    long_name = "頭" + "x" * 300 + "尾"
    result, _ = _fetch(json.dumps(_peer_state([_session(long_name, 1)])))
    assert result["sessions"][0]["project"] == long_name[:200]


# --- 過期判斷：超過 10 分鐘就不顯示 --------------------------------------

def test_剛好_600_秒還不算過期():
    result, _ = _fetch(json.dumps(_peer_state([_session("a", 1)], age_seconds=600)))
    assert result["ok"] is True
    assert len(result["sessions"]) == 1


def test_超過_600_秒就算過期_清空_sessions():
    st = _peer_state([_session("a", 1)], age_seconds=601)
    result, _ = _fetch(json.dumps(st))
    assert result["ok"] is False
    assert result["sessions"] == []
    assert isinstance(result["error"], str) and result["error"]
    assert result["generated_at"] == st["generated_at"]


@pytest.mark.parametrize("bad_ts", [None, "", "yesterday"])
def test_generated_at_缺漏或看不懂就當失敗(bad_ts):
    st = _peer_state([_session("a", 1)])
    st["generated_at"] = bad_ts
    result, _ = _fetch(json.dumps(st))
    assert result["ok"] is False
    assert result["sessions"] == []


# --- 失敗路徑：一律不丟例外 ----------------------------------------------

def test_ssh_非零結束碼回傳失敗():
    result, _ = _fetch("", returncode=255)
    assert result["ok"] is False
    assert result["sessions"] == []
    assert isinstance(result["error"], str) and result["error"]
    assert result["label"] == "M3"


@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired(cmd="ssh", timeout=5),
                                 FileNotFoundError("ssh")])
def test_ssh_逾時或找不到指令不可以丟例外(exc):
    result, _ = _fetch(raises=exc)
    assert result["ok"] is False
    assert result["sessions"] == []
    assert isinstance(result["error"], str) and result["error"]


@pytest.mark.parametrize("stdout", ["not json", "[]", json.dumps({"no": "sessions"})])
def test_對方回傳的不是合法_state_就當失敗(stdout):
    result, _ = _fetch(stdout)
    assert result["ok"] is False
    assert result["sessions"] == []


# --- state.json 接線 ------------------------------------------------------

def test_state_預設_peer_為_None():
    state = main.build_state(None, None, None, None, sessions=[])
    assert "peer" in state
    assert state["peer"] is None


# 對方失敗要「安靜」：只記在 peer.error，不進 state["errors"]
def test_peer_失敗不寫進_state_errors():
    failed = {"label": "M3", "ok": False, "sessions": [], "error": "連不上",
              "generated_at": None}
    state = main.build_state(None, None, None, None, sessions=[], peer=failed)
    assert state["peer"] == failed
    assert all("連不上" not in e for e in state["errors"])
    json.dumps(state, ensure_ascii=False)


# 本機的 sessions 不可以被對方的資料混進去
def test_peer_不影響本機_sessions():
    local = [_session("local", 1)]
    p = {"label": "M3", "ok": True, "sessions": [_session("remote", 2)],
         "error": None, "generated_at": NOW.isoformat()}
    state = main.build_state(None, None, None, None, sessions=local, peer=p)
    assert state["sessions"] == local
    assert state["peer"]["sessions"][0]["project"] == "remote"


# --- 防止兩個 collector 疊在一起跑 -----------------------------------------
# desklet 每輪都 spawn、不等上一輪；加了最長 5 秒的 ssh 之後重疊機率變高。
# 兩個 collector 同時改 file_offsets.json 會把同一段逐字稿算兩次（SPEC §3）。
# 規則：main() 先對 STATE_DIR / "collector.lock" 取「非阻塞」獨占 flock，
# 拿不到就什麼都不做、直接回 0。鎖檔路徑在呼叫當下由 main.STATE_DIR 組出。

def test_鎖被佔用時_main_直接結束不做事(tmp_path, monkeypatch):
    import fcntl
    monkeypatch.setattr(main, "STATE_DIR", tmp_path)
    monkeypatch.setattr(main, "STATE_FILE", tmp_path / "state.json")
    called = []
    monkeypatch.setattr(main, "fetch_usage_throttled",
                        lambda: called.append(1) or (None, "x"))
    with open(tmp_path / "collector.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert main.main() == 0
    assert called == []
    assert not (tmp_path / "state.json").exists()


def test_鎖沒被佔用時_main_照常執行(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "STATE_DIR", tmp_path)
    monkeypatch.setattr(main, "STATE_FILE", tmp_path / "state.json")
    called = []

    def stop(*a, **k):
        called.append(1)
        raise RuntimeError("stop-here")

    monkeypatch.setattr(main, "fetch_usage_throttled", stop)
    with pytest.raises(RuntimeError, match="stop-here"):
        main.main()
    assert called == [1]
