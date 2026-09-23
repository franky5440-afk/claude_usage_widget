"""同一則回覆只算一次（Frank 2026-09-15 拍板：修，並重建歷史帳本）。

Claude Code 會把一則回覆的每個 content block 各寫一行，每行都帶同一個 message.id 與 usage；
串流途中的行 output_tokens 還沒長完，最後一行才是最終值（2026-09-15 實測：input/cache 相同，只有 output 在長）。
逐行累加導致今日 CLI 用量高估 3.81 倍、Dispatch 高估 1.83 倍。

規則：同一個檔內同一個 message.id 只計一次，以最後出現的那一行 usage 為準；沒有 message.id 的行照舊逐行計。
"""
import json
from datetime import datetime, timedelta, timezone

from collector import history, main, transcript_scan

TW = timezone(timedelta(hours=8))


def _row(mid, out, ts=None, inp=32, create=9487, read=45059):
    ts = ts or datetime.now(timezone.utc)
    msg = {"model": "claude-opus-5",
           "usage": {"input_tokens": inp, "output_tokens": out,
                     "cache_creation_input_tokens": create, "cache_read_input_tokens": read}}
    if mid is not None:
        msg["id"] = mid
    return json.dumps({"type": "assistant", "timestamp": ts.isoformat(), "message": msg}) + "\n"


FINAL = 32 + 1391 + 9487 + 45059


def _proj(tmp_path):
    p = tmp_path / "projects" / "-Users-u-Claude-demo"
    p.mkdir(parents=True)
    return p


def test_同一則回覆拆成多行只算一次且取最後一行(tmp_path):
    f = _proj(tmp_path) / "s.jsonl"
    f.write_text(_row("msg_1", 8) + _row("msg_1", 8) + _row("msg_1", 1391))

    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects")

    assert r["totals"]["today_tokens"] == FINAL
    assert r["totals"]["today_by_model"]["claude-opus-5"]["output_tokens"] == 1391
    assert r["totals"]["week_by_model"]["claude-opus-5"]["output_tokens"] == 1391
    assert r["projects"][0]["tokens"] == FINAL


def test_同一則回覆橫跨兩次增量掃描時以後來那行取代(tmp_path):
    """增量掃描的 offset 可能剛好切在一則回覆的中間，後半段讀進來時要換掉前面算的，不是再加一次。"""
    f = _proj(tmp_path) / "s.jsonl"
    cache = tmp_path / "cache"
    f.write_text(_row("msg_1", 8) + _row("msg_1", 8))
    transcript_scan.scan(cache_dir=cache, projects_dir=tmp_path / "projects")

    with open(f, "a") as fh:
        fh.write(_row("msg_1", 1391) + _row("msg_2", 10, inp=0, create=0, read=0))
    second = transcript_scan.scan(cache_dir=cache, projects_dir=tmp_path / "projects")

    assert second["bytes_read"] > 0
    assert second["totals"]["today_tokens"] == FINAL + 10
    assert second["projects"][0]["tokens"] == FINAL + 10

    third = transcript_scan.scan(cache_dir=cache, projects_dir=tmp_path / "projects")
    assert third["bytes_read"] == 0 and third["totals"]["today_tokens"] == FINAL + 10


def test_不同回覆各自計算(tmp_path):
    f = _proj(tmp_path) / "s.jsonl"
    f.write_text(_row("msg_1", 100, inp=0, create=0, read=0) + _row("msg_2", 50, inp=0, create=0, read=0))
    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects")
    assert r["totals"]["today_tokens"] == 150


def test_沒有_message_id_的行照舊逐行計(tmp_path):
    f = _proj(tmp_path) / "s.jsonl"
    f.write_text(_row(None, 100, inp=0, create=0, read=0) + _row(None, 100, inp=0, create=0, read=0))
    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects")
    assert r["totals"]["today_tokens"] == 200


def test_dispatch_也要去重(tmp_path):
    d = tmp_path / "dispatch" / "acct" / "org" / "local_1" / "audit.jsonl"
    d.parent.mkdir(parents=True)
    d.write_text(_row("msg_1", 8) + _row("msg_1", 1391))
    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects",
                             dispatch_dir=tmp_path / "dispatch")
    assert r["totals"]["today_tokens"] == FINAL


def test_歷史補建也要去重(tmp_path):
    old = datetime.now(TW) - timedelta(days=10)
    ts = old.astimezone(timezone.utc)
    f = _proj(tmp_path) / "a.jsonl"
    f.write_text(_row("msg_1", 8, ts=ts) + _row("msg_1", 8, ts=ts) + _row("msg_1", 1391, ts=ts))
    cache = tmp_path / "cache"
    history.rebuild(cache_dir=cache, projects_dir=tmp_path / "projects")
    day = history.load(cache)["days"][old.date().isoformat()]
    assert day["by_model"]["claude-opus-5"]["output_tokens"] == 1391
    assert day["projects"]["demo"] == FINAL


def test_帳本版本升到_2():
    assert history.SCHEMA_VERSION >= 2


def test_舊版帳本會自動以去重算法重建(tmp_path):
    """已經存進帳本的舊日子是高估值；升版後第一次跑要自動重算，不能讓週報新舊混算。"""
    old = datetime.now(TW) - timedelta(days=10)
    date_str = old.date().isoformat()
    ts = old.astimezone(timezone.utc)
    f = _proj(tmp_path) / "a.jsonl"
    f.write_text(_row("msg_1", 8, ts=ts) + _row("msg_1", 1391, ts=ts))
    cache = tmp_path / "cache"
    cache.mkdir()
    inflated = {"input_tokens": 64, "output_tokens": 1399,
                "cache_creation_input_tokens": 18974, "cache_read_input_tokens": 90118}
    (cache / history.HISTORY_FILE).write_text(json.dumps({
        "schema_version": 1,
        "days": {date_str: {"by_model": {"claude-opus-5": inflated}, "projects": {"demo": 110555}}}}))

    errors = main._sync_history(cache, tmp_path / "projects")

    store = json.loads((cache / history.HISTORY_FILE).read_text())
    assert store["schema_version"] == history.SCHEMA_VERSION
    assert store["days"][date_str]["by_model"]["claude-opus-5"]["output_tokens"] == 1391
    assert store["days"][date_str]["projects"]["demo"] == FINAL
    assert not any("損毀" in e for e in errors), "版本舊不是損毀，不得出現損毀提醒"


def test_現行版本的帳本不會每次重建(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / history.HISTORY_FILE).write_text(json.dumps({"schema_version": history.SCHEMA_VERSION, "days": {}}))
    calls = []
    monkeypatch.setattr(history, "rebuild", lambda *a, **k: calls.append(1) or {})
    main._sync_history(cache, tmp_path / "projects")
    assert calls == [], "SPEC §3：全量補建一輩子只該跑一次"
