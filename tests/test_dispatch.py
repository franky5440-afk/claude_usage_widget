"""Dispatch（Claude 桌面版）用量併入 widget（Frank 2026-09-15 拍板：context、子 session、成本與排行全要）。

Dispatch 不寫 ~/.claude/projects，而是：
  <dispatch_dir>/<acct>/<org>/agent/local_ditto_<org>/audit.jsonl   ← 主 session
  <dispatch_dir>/<acct>/<org>/local_<uuid>/audit.jsonl              ← 派出的子 session
assistant 行的 message.usage 與 CLI 同格式；子代理的行帶非 null 的 parent_tool_use_id；
system 行的 model 是模型 id。只認 audit.jsonl，其他 jsonl 一律不讀。
"""
import builtins
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collector import history, main, session_context, transcript_scan

TW = timezone(timedelta(hours=8))


def _usage(inp=0, read=0, create=0, out=0):
    return {"input_tokens": inp, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": create, "output_tokens": out}


def _assistant(usage, ts=None, sub=False, mid="m"):
    ts = ts or datetime.now(timezone.utc)
    return {"type": "assistant", "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "parent_tool_use_id": "toolu_x" if sub else None, "session_id": "s",
            "message": {"id": mid, "model": "claude-opus-5", "usage": usage}}


def _system(model):
    return {"type": "system", "subtype": "init", "model": model, "cwd": "/tmp/outputs",
            "timestamp": datetime.now(timezone.utc).isoformat()}


def _write(path, rows, age_seconds=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    t = time.time() - age_seconds
    os.utime(path, (t, t))
    return path


def _ditto(d):
    return d / "acct" / "org" / "agent" / "local_ditto_org" / "audit.jsonl"


def _child(d, name="local_1111"):
    return d / "acct" / "org" / name / "audit.jsonl"


# --- 成本與專案排行（transcript_scan.scan） ---------------------------------

def test_dispatch_的用量算進今日並以_Dispatch_列入排行(tmp_path):
    d = tmp_path / "dispatch"
    _write(_ditto(d), [_system("claude-opus-5"), _assistant(_usage(out=30), mid="a")])
    _write(_child(d), [_system("claude-opus-5"), _assistant(_usage(out=12), sub=True, mid="b")])

    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects",
                             dispatch_dir=d)

    assert r["totals"]["today_tokens"] == 42, "主 session、子 session、子代理的行都是真的花費"
    assert r["projects"] == [{"name": "Dispatch", "tokens": 42, "percent": 100.0}]
    assert r["totals"]["week_by_model"]["claude-opus-5"]["output_tokens"] == 42


def test_dispatch_與_cli_合併計算(tmp_path):
    d = tmp_path / "dispatch"
    _write(_ditto(d), [_assistant(_usage(out=25), mid="a")])
    proj = tmp_path / "projects" / "-Users-u-Claude-demo"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(json.dumps({
        "type": "assistant", "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": {"model": "claude-opus-5", "usage": _usage(out=75)}}) + "\n")

    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects",
                             dispatch_dir=d)

    assert r["totals"]["today_tokens"] == 100
    assert [p["name"] for p in r["projects"]] == ["demo", "Dispatch"]


def test_dispatch_只讀_audit_jsonl(tmp_path):
    d = tmp_path / "dispatch"
    _write(d / "acct" / "org" / "local_1111" / "other.jsonl", [_assistant(_usage(out=999))])
    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects",
                             dispatch_dir=d)
    assert r["totals"]["today_tokens"] == 0


def test_dispatch_也走增量掃描(tmp_path):
    """SPEC §3：Dispatch 目錄實測 1257 個檔、503MB，不能每次全讀。"""
    d = tmp_path / "dispatch"
    _write(_ditto(d), [_assistant(_usage(out=30), mid="a")])
    cache = tmp_path / "cache"
    first = transcript_scan.scan(cache_dir=cache, projects_dir=tmp_path / "projects", dispatch_dir=d)
    second = transcript_scan.scan(cache_dir=cache, projects_dir=tmp_path / "projects", dispatch_dir=d)
    assert first["bytes_read"] > 0
    assert second["bytes_read"] == 0
    assert second["totals"]["today_tokens"] == 30


def test_本週以前就沒動過的_dispatch_檔不讀(tmp_path):
    """mtime 早於本週一（台灣時間）的檔，裡面不可能有本週用量；503MB 裡絕大多數是這種，不准打開。"""
    d = tmp_path / "dispatch"
    old = datetime.now(timezone.utc) - timedelta(days=9)
    _write(_child(d), [_assistant(_usage(out=500), ts=old, mid="a")], age_seconds=9 * 86400)
    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects",
                             dispatch_dir=d)
    assert r["bytes_read"] == 0
    assert r["totals"]["today_tokens"] == 0


def test_沒有_dispatch_目錄時行為不變(tmp_path):
    for dispatch_dir in (None, tmp_path / "nope"):
        r = transcript_scan.scan(cache_dir=tmp_path / f"cache-{dispatch_dir is None}",
                                 projects_dir=tmp_path / "projects", dispatch_dir=dispatch_dir)
        assert r["totals"]["today_tokens"] == 0 and r["projects"] == []


# --- 歷史週報（history.rebuild） ---------------------------------------------

def test_dispatch_也要納入歷史補建(tmp_path):
    """週報與 widget 的本週金額要對得起來，Dispatch 不能只算一邊。"""
    d = tmp_path / "dispatch"
    old = datetime.now(TW) - timedelta(days=10)
    _write(_child(d), [_assistant(_usage(out=700), ts=old.astimezone(timezone.utc), mid="a")],
           age_seconds=10 * 86400)
    cache = tmp_path / "cache"
    history.rebuild(cache_dir=cache, projects_dir=tmp_path / "projects", dispatch_dir=d)
    day = history.load(cache)["days"][old.date().isoformat()]
    assert day["by_model"]["claude-opus-5"]["output_tokens"] == 700


# --- Session Context（session_context.active_sessions） ----------------------

def test_dispatch_主_session_列入_context(tmp_path):
    d = tmp_path / "dispatch"
    _write(_ditto(d), [
        _system("claude-opus-5"),
        _assistant(_usage(read=100000, create=466, inp=2), mid="a"),
        _assistant(_usage(read=5000), sub=True, mid="b"),
    ])
    out = session_context.active_sessions(tmp_path / "projects", dispatch_dir=d)
    assert out == [{
        "project": "Dispatch", "tokens": 100468, "context_window": 1000000, "percent": 10.0,
        "model": "claude-opus-5", "last_active_at": out[0]["last_active_at"],
    }], "子代理的行（parent_tool_use_id 非 null）不算主線 context"


def test_dispatch_的_opus_5_一律是_1m(tmp_path):
    """Frank 2026-09-15：Dispatch 用的 Opus 5 是 1M context，但 system.model 不帶 [1m] 標記。
    照 CLI 規則套 200K 會算出 110.3% 這種鬼數字（實機看到過）。"""
    d = tmp_path / "dispatch"
    _write(_ditto(d), [_system("claude-opus-5"), _assistant(_usage(read=220600), mid="a")])
    out = session_context.active_sessions(tmp_path / "projects", dispatch_dir=d)
    assert out[0]["context_window"] == 1000000 and out[0]["percent"] == 22.1


def test_dispatch_的其他模型照一般規則(tmp_path):
    d = tmp_path / "dispatch"
    _write(_ditto(d), [_system("claude-sonnet-5"), _assistant(_usage(read=50000), mid="a")])
    out = session_context.active_sessions(tmp_path / "projects", dispatch_dir=d)
    assert out[0]["context_window"] == 200000 and out[0]["percent"] == 25.0


def test_cli_的_opus_5_沒有_1m_標記仍是_200k(tmp_path):
    """1M 的放寬只限 Dispatch，CLI 照舊看 [1m] 標記。"""
    cli = tmp_path / "projects" / "-Users-u-Claude-demo" / "s.jsonl"
    _write(cli, [{"type": "attachment", "attachment": {"type": "model", "identity": {"modelId": "claude-opus-5"}}},
                 {"type": "assistant", "isSidechain": False, "timestamp": "2026-09-15T00:00:00Z",
                  "message": {"model": "claude-opus-5", "usage": _usage(read=50000)}}])
    out = session_context.active_sessions(tmp_path / "projects", dispatch_dir=None)
    assert out[0]["context_window"] == 200000


def test_dispatch_子_session_另外標名(tmp_path):
    d = tmp_path / "dispatch"
    _write(_child(d), [_system("claude-opus-5[1m]"), _assistant(_usage(read=300000), mid="a")])
    out = session_context.active_sessions(tmp_path / "projects", dispatch_dir=d)
    assert out[0]["project"] == "Dispatch 子任務"
    assert out[0]["context_window"] == 1000000 and out[0]["percent"] == 30.0


def test_dispatch_查不到模型時分母留白(tmp_path):
    d = tmp_path / "dispatch"
    _write(_ditto(d), [_assistant(_usage(read=1000), mid="a")])
    out = session_context.active_sessions(tmp_path / "projects", dispatch_dir=d)
    assert out[0]["context_window"] is None and out[0]["percent"] is None


def test_dispatch_與_cli_session_一起排序且共用上限(tmp_path):
    d = tmp_path / "dispatch"
    _write(_ditto(d), [_system("claude-opus-5"), _assistant(_usage(read=1), mid="a")], age_seconds=10)
    _write(_child(d, "local_a"), [_system("claude-opus-5"), _assistant(_usage(read=1), mid="a")], age_seconds=30)
    _write(_child(d, "local_b"), [_system("claude-opus-5"), _assistant(_usage(read=1), mid="a")], age_seconds=50)
    cli = tmp_path / "projects" / "-Users-u-Claude-demo" / "s.jsonl"
    _write(cli, [{"type": "attachment", "attachment": {"type": "model", "identity": {"modelId": "claude-opus-5"}}},
                 {"type": "assistant", "isSidechain": False, "timestamp": "2026-09-15T00:00:00Z",
                  "message": {"model": "claude-opus-5", "usage": _usage(read=1)}}], age_seconds=20)

    out = session_context.active_sessions(tmp_path / "projects", dispatch_dir=d)

    assert [r["project"] for r in out] == ["Dispatch", "demo", "Dispatch 子任務"]


def test_窗口外的_dispatch_檔不得被開啟(tmp_path, monkeypatch):
    d = tmp_path / "dispatch"
    old = _write(_child(d), [_assistant(_usage(read=1), mid="a")], age_seconds=3600)
    opened = []
    real_open = builtins.open

    def spy(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    assert session_context.active_sessions(tmp_path / "projects", dispatch_dir=d) == []
    assert str(old) not in opened


# --- 接線（collector.main） ---------------------------------------------------

def test_main_使用桌面版的_dispatch_目錄():
    assert main.DISPATCH_DIR == (Path.home() / "Library" / "Application Support" / "Claude"
                                 / "local-agent-mode-sessions")
