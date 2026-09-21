"""介面契約測試 — 反解有損時改用逐字稿的 cwd 當專案名（Frank 2026-09-21）。

⚠️ builder 不得修改本檔的斷言。測試錯了請回報，不要自己改綠。

背景：Claude Code 把 cwd 的非英數字元一律換成 '-' 當目錄名，
`~/Claude main/業務自動助理` 會變成 `-Users-u-Claude-main-------`，反解只剩 '------'。
"""
import builtins
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector import session_context, transcript_scan  # noqa: E402


def _rows(cwd):
    now = datetime.now(timezone.utc).isoformat()
    return [
        {"type": "user", "cwd": cwd, "timestamp": now, "message": {"role": "user"}},
        {"type": "attachment", "isSidechain": False,
         "attachment": {"type": "model", "identity": {"modelId": "claude-opus-5[1m]"}}},
        {"type": "assistant", "cwd": cwd, "timestamp": now, "isSidechain": False,
         "message": {"model": "claude-opus-5",
                     "usage": {"input_tokens": 1, "output_tokens": 1,
                               "cache_creation_input_tokens": 0,
                               "cache_read_input_tokens": 1000}}},
    ]


def _write(projects_dir, dir_name, cwd, name="s.jsonl"):
    d = projects_dir / dir_name
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    with open(p, "w", encoding="utf-8") as f:
        for r in _rows(cwd):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return d


def test_反解有損時用_cwd_的最後一層(tmp_path):
    d = _write(tmp_path / "projects", "-Users-u-Claude-main-------",
               "/Users/u/Claude main/業務自動助理")
    assert transcript_scan.project_name(d) == "業務自動助理"


def test_英文夾中文的專案名也要還原(tmp_path):
    d = _write(tmp_path / "projects", "-Users-u-Claude-main-Trade-Brief------",
               "/Users/u/Claude main/Trade Brief 電子報專案")
    assert transcript_scan.project_name(d) == "Trade Brief 電子報專案"


def test_cwd_重新編碼對不上目錄名就不採用(tmp_path):
    """cwd 可能是別的目錄（例如中途 cd 過、或資料異常）。對不上就退回原本的反解，
    不能拿不相干的資料夾名頂替。"""
    d = _write(tmp_path / "projects", "-Users-u-Claude-main-------",
               "/Users/u/Claude main/別的專案啦")
    assert transcript_scan.project_name(d) == transcript_scan._decode_project_name(d.name)


def test_沒有逐字稿或沒有_cwd_時退回原本的反解(tmp_path):
    d = tmp_path / "projects" / "-Users-u-Claude-main-------"
    d.mkdir(parents=True)
    assert transcript_scan.project_name(d) == "------"
    (d / "s.jsonl").write_text('{"type": "user"}\n', encoding="utf-8")
    assert transcript_scan.project_name(d) == "------"


@pytest.mark.parametrize("dir_name", [
    "-home-lintzuyang-Claude-linux-claude-usage",
    "-Users-u-Claude-main-claude-usage-widget",
    "-home-lintzuyang",
])
def test_反解沒損失的目錄一個檔都不開(tmp_path, monkeypatch, dir_name):
    """🔴 SPEC §3：純英數專案名本來就對，不准為了查 cwd 多開檔。"""
    d = _write(tmp_path / "projects", dir_name, "/whatever")
    opened = []
    real_open = builtins.open

    def spy(file, *a, **kw):
        opened.append(str(file))
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    assert transcript_scan.project_name(d) == transcript_scan._decode_project_name(dir_name)
    assert opened == []


def test_專案排行用還原後的名字(tmp_path):
    p = tmp_path / "projects"
    _write(p, "-Users-u-Claude-main-------", "/Users/u/Claude main/業務自動助理")
    r = transcript_scan.scan(cache_dir=tmp_path / "cache", projects_dir=p)
    assert [x["name"] for x in r["projects"]] == ["業務自動助理"]


def test_session_context_與專案排行名字一致(tmp_path):
    """同一個 widget 上 C、D 區塊的專案名必須逐字一致。"""
    p = tmp_path / "projects"
    _write(p, "-Users-u-Claude-main-------", "/Users/u/Claude main/業務自動助理")
    out = session_context.active_sessions(p, window_minutes=None)
    assert [s["project"] for s in out] == ["業務自動助理"]
