"""Mac 移植：逐字稿目錄在 macOS 是 -Users-<user>-...，不是 Linux 的 -home-<user>-...。

2026-09-15 實測：Mac 上 scan() 因只認 -home- 開頭，195 個逐字稿全被跳過，今日用量恆為 0。
"""
import json
from datetime import datetime, timedelta, timezone

from collector import history, transcript_scan

TW = timezone(timedelta(hours=8))


def _row(ts, out_tokens):
    return json.dumps({"type": "assistant", "timestamp": ts.isoformat(),
                       "message": {"model": "claude-opus-5",
                                   "usage": {"input_tokens": 0, "output_tokens": out_tokens,
                                             "cache_creation_input_tokens": 0,
                                             "cache_read_input_tokens": 0}}}) + "\n"


def test_mac_的目錄也要掃到今日用量(tmp_path):
    proj = tmp_path / "projects" / "-Users-someone-Claude-demo"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(_row(datetime.now(timezone.utc), 42))

    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects")

    assert r["totals"]["today_tokens"] == 42
    assert r["projects"] == [{"name": "demo", "tokens": 42, "percent": 100.0}]


def test_mac_的專案名反解規則與_linux_相同():
    assert transcript_scan._decode_project_name("-Users-someone") == "家目錄"
    assert transcript_scan._decode_project_name("-Users-someone-Claude-my-proj") == "my-proj"
    assert transcript_scan._decode_project_name("-Users-someone-work-thing") == "thing"
    # Linux 規則不能被改壞
    assert transcript_scan._decode_project_name("-home-someone-Claude-my-proj") == "my-proj"


def test_mac_的目錄也要納入歷史補建(tmp_path):
    proj = tmp_path / "projects" / "-Users-someone-Claude-demo"
    proj.mkdir(parents=True)
    old = datetime.now(TW) - timedelta(days=10)
    (proj / "a.jsonl").write_text(_row(old.astimezone(timezone.utc), 700))

    cache = tmp_path / "cache"
    history.rebuild(cache_dir=cache, projects_dir=tmp_path / "projects")

    days = history.load(cache)["days"]
    assert days[old.date().isoformat()]["by_model"]["claude-opus-5"]["output_tokens"] == 700


def test_不是使用者專案的目錄照舊不掃(tmp_path):
    proj = tmp_path / "projects" / "-private-tmp-x"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(_row(datetime.now(timezone.utc), 42))

    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=tmp_path / "projects")

    assert r["totals"]["today_tokens"] == 0
