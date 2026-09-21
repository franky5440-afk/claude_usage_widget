"""2026-09-15 security 審查指出：單一怪行會讓整個 scan／rebuild 拋例外（SPEC §4.2 要可讀的降級），
而 rebuild 失敗會讓帳本停在舊版、每輪全量重掃 503MB。另：快取檔要 0600、Dispatch 找檔只收一般檔案。"""
import json
import os
import stat
from datetime import datetime, timedelta, timezone

from collector import history, transcript_scan

TW = timezone(timedelta(hours=8))

# __TS__ 在寫檔時換成當下時間：寫死日期會讓「算進今日」的斷言隔天就錯
BAD_LINES = [
    "[]", "1", '"x"', "null",
    json.dumps({"type": "assistant", "message": "not a dict"}),
    json.dumps({"type": "assistant", "timestamp": "__TS__",
                "message": {"id": {"nested": 1}, "model": "claude-opus-5",
                            "usage": {"output_tokens": 5}}}),
    '{"type": "assistant", "timestamp": "__TS__", '
    '"message": {"id": "inf", "model": "claude-opus-5", "usage": {"output_tokens": Infinity}}}',
    json.dumps({"type": "assistant", "timestamp": "__TS__",
                "message": {"id": "u", "model": "claude-opus-5", "usage": "oops"}}),
]


def _good(ts, out=100):
    return json.dumps({"type": "assistant", "timestamp": ts.isoformat(),
                       "message": {"id": "good", "model": "claude-opus-5",
                                   "usage": {"input_tokens": 0, "output_tokens": out,
                                             "cache_creation_input_tokens": 0,
                                             "cache_read_input_tokens": 0}}})


def _write_mixed(path, ts):
    path.parent.mkdir(parents=True, exist_ok=True)
    bad = [line.replace("__TS__", ts.isoformat()) for line in BAD_LINES]
    path.write_text("\n".join(bad + [_good(ts)]) + "\n")


def test_怪行不會讓掃描整個失敗(tmp_path):
    now = datetime.now(timezone.utc)
    _write_mixed(tmp_path / "projects" / "-Users-u-Claude-demo" / "s.jsonl", now)
    _write_mixed(tmp_path / "dispatch" / "a" / "o" / "local_1" / "audit.jsonl", now)

    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects",
                             dispatch_dir=tmp_path / "dispatch")

    # 好的行各 100；id 不是字串的那行依 §12.2 當成「沒有 message.id」照算（各 5），其餘怪行跳過
    assert r["totals"]["today_tokens"] == 210, "怪行不得拖垮整輪掃描"
    assert {p["name"] for p in r["projects"]} == {"demo", "Dispatch"}


def test_怪行不會讓歷史補建失敗(tmp_path):
    old = datetime.now(TW) - timedelta(days=10)
    _write_mixed(tmp_path / "projects" / "-Users-u-Claude-demo" / "a.jsonl", old.astimezone(timezone.utc))
    cache = tmp_path / "cache"

    history.rebuild(cache_dir=cache, projects_dir=tmp_path / "projects")

    store = json.loads((cache / history.HISTORY_FILE).read_text())
    assert store["schema_version"] == history.SCHEMA_VERSION
    # 好的行 100＋id 不是字串的那行 5（同 test_怪行不會讓掃描整個失敗 的規則）
    assert store["days"][old.date().isoformat()]["by_model"]["claude-opus-5"]["output_tokens"] == 105


def test_快取與帳本檔權限為_0600(tmp_path):
    now = datetime.now(timezone.utc)
    _write_mixed(tmp_path / "projects" / "-Users-u-Claude-demo" / "s.jsonl", now)
    cache = tmp_path / "cache"
    transcript_scan.scan(cache_dir=cache, projects_dir=tmp_path / "projects")
    history.rebuild(cache_dir=cache, projects_dir=tmp_path / "projects")
    for name in (transcript_scan.CACHE_FILE, transcript_scan.TOTALS_CACHE, history.HISTORY_FILE):
        mode = stat.S_IMODE(os.stat(cache / name).st_mode)
        assert mode == 0o600, f"{name} 是 {oct(mode)}"


def test_dispatch_找檔跳過_symlink_與非一般檔案(tmp_path):
    real = tmp_path / "a" / "o" / "local_ok" / "audit.jsonl"
    real.parent.mkdir(parents=True)
    real.write_text("")
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    link = tmp_path / "a" / "o" / "local_link" / "audit.jsonl"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    fifo = tmp_path / "a" / "o" / "local_fifo" / "audit.jsonl"
    fifo.parent.mkdir(parents=True)
    os.mkfifo(fifo)

    assert [str(p) for p in transcript_scan.dispatch_audit_files(tmp_path)] == [str(real)]
