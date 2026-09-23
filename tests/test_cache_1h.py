"""1 小時 cache 寫入要照 1 小時的價格算（Frank 2026-09-23 裁示）。

官方價目：5 分鐘 cache 寫入＝input × 1.25，1 小時 cache 寫入＝input × 2。
原本全部當 5 分鐘算；2026-09-23 實測兩台近兩天約 2/3 的 cache 寫入是 1 小時的，成本被低估。

逐字稿 usage 的原始格式：
  "cache_creation_input_tokens": 總寫入,
  "cache_creation": {"ephemeral_5m_input_tokens": ..., "ephemeral_1h_input_tokens": ...}

內部拆成「不重疊」的兩塊，讓既有各處 sum(usage.values()) 不必改也不會重複計算：
  cache_creation_input_tokens    ＝ 非 1h 的部分（總寫入 − 1h）
  cache_creation_1h_input_tokens ＝ 1h 的部分
"""
import json
from datetime import datetime, timezone

from collector import history, main, pricing, transcript_scan

ONE_H = "cache_creation_1h_input_tokens"


def _row(mid, create=300, h1=200, m5=100, inp=10, out=20, read=1000, nested=True, ts=None):
    usage = {"input_tokens": inp, "output_tokens": out,
             "cache_creation_input_tokens": create, "cache_read_input_tokens": read}
    if nested:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": m5,
                                   "ephemeral_1h_input_tokens": h1}
    ts = ts or datetime.now(timezone.utc)
    return json.dumps({"type": "assistant", "timestamp": ts.isoformat(),
                       "message": {"id": mid, "model": "claude-opus-5-5", "usage": usage}}) + "\n"


def _proj(tmp_path):
    p = tmp_path / "projects" / "-Users-u-Claude-demo"
    p.mkdir(parents=True)
    return p


def _scan(tmp_path):
    return transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects")


# --- 價格表 -----------------------------------------------------------------

def test_每個模型都有_1h_寫入價且是_input_的兩倍():
    for name, p in pricing.load_table()["models"].items():
        assert p.get("cache_write_1h") == p["input"] * 2, name


def test_成本分別套用_5m_與_1h_寫入價():
    by_model = {"claude-opus-5-5": {
        "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 1_000_000, ONE_H: 1_000_000}}
    per_model, errors = pricing.estimate_cost_by_model(by_model, pricing.load_table())
    assert errors == []
    assert abs(per_model["claude-opus-5-5"] - (5.0 + 8.0)) < 1e-9


def test_只有_1h_寫入的模型不可被當成零用量跳過():
    by_model = {"claude-opus-5-5": {
        "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0, ONE_H: 1_000_000}}
    per_model, _ = pricing.estimate_cost_by_model(by_model, pricing.load_table())
    assert abs(per_model["claude-opus-5-5"] - 8.0) < 1e-9


def test_沒有_1h_欄位的舊資料照舊算():
    """歷史帳本舊資料沒有 1h 欄位，視為 0，全部照 5 分鐘價。"""
    by_model = {"claude-opus-5-5": {
        "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 1_000_000}}
    per_model, _ = pricing.estimate_cost_by_model(by_model, pricing.load_table())
    assert abs(per_model["claude-opus-5-5"] - 5.0) < 1e-9


# --- 掃描 -------------------------------------------------------------------

def test_掃描時把_1h_從總寫入拆出來而且總量不重複計算(tmp_path):
    (_proj(tmp_path) / "s.jsonl").write_text(_row("m1"))
    r = _scan(tmp_path)
    u = r["totals"]["today_by_model"]["claude-opus-5-5"]
    assert u["cache_creation_input_tokens"] == 100
    assert u[ONE_H] == 200
    assert r["totals"]["week_by_model"]["claude-opus-5-5"][ONE_H] == 200
    assert r["totals"]["today_tokens"] == 10 + 20 + 300 + 1000, "1h 是總寫入的一部分，不可再加一次"
    assert r["projects"][0]["tokens"] == 10 + 20 + 300 + 1000


def test_讀回自己的快取時_1h_不會被歸零(tmp_path):
    """快取裡存的是拆好的扁平欄位，沒有巢狀 cache_creation；
    再套一次擷取函式時必須認得扁平欄位，否則第二輪起 1h 全變 0。"""
    f = _proj(tmp_path) / "s.jsonl"
    f.write_text(_row("m1"))
    _scan(tmp_path)
    with open(f, "a") as fh:
        fh.write(_row("m2", create=0, h1=0, m5=0, inp=1, out=0, read=0))
    r = _scan(tmp_path)
    u = r["totals"]["today_by_model"]["claude-opus-5-5"]
    assert u[ONE_H] == 200
    assert u["cache_creation_input_tokens"] == 100


def test_沒有巢狀明細的行全部算_5m(tmp_path):
    (_proj(tmp_path) / "s.jsonl").write_text(_row("m1", nested=False))
    u = _scan(tmp_path)["totals"]["today_by_model"]["claude-opus-5-5"]
    assert u["cache_creation_input_tokens"] == 300
    assert u.get(ONE_H, 0) == 0


def test_明細不合理時不可出現負數或超過總寫入(tmp_path):
    """1h 大於總寫入（資料不一致）→ 1h 以總寫入為上限，非 1h 部分為 0；怪型別當 0。"""
    (_proj(tmp_path) / "s.jsonl").write_text(
        _row("m1", create=300, h1=999) +
        _row("m2", create=50, h1="oops") +
        json.dumps({"type": "assistant", "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": {"id": "m3", "model": "claude-opus-5-5",
                                "usage": {"cache_creation_input_tokens": 40,
                                          "cache_creation": "oops"}}}) + "\n")
    u = _scan(tmp_path)["totals"]["today_by_model"]["claude-opus-5-5"]
    assert u[ONE_H] == 300
    assert u["cache_creation_input_tokens"] == 50 + 40


# --- 歷史帳本 ---------------------------------------------------------------

def test_版本號要升級才會觸發重掃():
    """舊快取與舊帳本裡的 cache 寫入是未拆分的總數，必須作廢重建。"""
    assert transcript_scan.FILE_CACHE_VERSION != 2
    assert history.SCHEMA_VERSION != 2


def test_帳本補建時也拆出_1h_且週報總量不重複(tmp_path):
    (_proj(tmp_path) / "s.jsonl").write_text(_row("m1"))
    history.rebuild(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects")
    days = history.load(tmp_path / "cache")["days"]
    (entry,) = days.values()
    u = entry["by_model"]["claude-opus-5-5"]
    assert u[ONE_H] == 200 and u["cache_creation_input_tokens"] == 100
    (week,) = history.weekly_report(tmp_path / "cache")
    assert week["tokens"] == 10 + 20 + 300 + 1000
    assert week["by_model"]["claude-opus-5-5"][ONE_H] == 200


def test_帳本寫入已拆好的用量時保留_1h(tmp_path):
    """跨日時 collector 把前一天的 today_by_model（已拆好）寫進帳本。"""
    history.record_day(tmp_path, "2026-09-22", {"claude-opus-5-5": {
        "input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3,
        "cache_creation_input_tokens": 4, ONE_H: 5}})
    u = history.load(tmp_path)["days"]["2026-09-22"]["by_model"]["claude-opus-5-5"]
    assert u[ONE_H] == 5 and u["cache_creation_input_tokens"] == 4


# --- 端到端 -----------------------------------------------------------------

def test_state_的成本有算進_1h_的價差(tmp_path):
    (_proj(tmp_path) / "s.jsonl").write_text(
        _row("m1", create=1_000_000, h1=1_000_000, m5=0, inp=0, out=0, read=0))
    scan = _scan(tmp_path)
    state = main.build_state(api_result=None, api_error=None, scan_result=scan, scan_error=None)
    assert state["cost"]["today_usd"] == 8.0, "Opus 5.5 的 1h 寫入是 $8/MTok，不是 5m 的 $5"
